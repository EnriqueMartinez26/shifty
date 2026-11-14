from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.auth.service as auth_service
import modules.notifications.outbox as email_outbox
import modules.notifications.tasks as notification_tasks
import modules.payments.jobs as payment_jobs
from core.crypto import decrypt_secret
from core.security import hash_password_reset_token
from modules.auth.schemas import ForgotPasswordRequest
from modules.payments.model import EVENT_EMAIL_SEND, OutboxMessage
from modules.otp.model import OtpVerification
from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    seed_store_and_admin,
)


@pytest.mark.asyncio
async def test_reset_outbox_token_is_atomic_and_only_decrypts_for_current_token(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "reset-secret-1234567890"
    monkeypatch.setattr(auth_service, "generate_password_reset_token", lambda: token)
    await seed_store_and_admin(
        slug="auth-outbox-current", email="outbox-reset@example.com"
    )

    response = await client.post(
        "/auth/forgot-password", json={"email": "outbox-reset@example.com"}
    )
    assert response.status_code == 200
    user = (
        await test_session.scalars(
            select(User).where(User.email == "outbox-reset@example.com")
        )
    ).one()
    message = (
        await test_session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == EVENT_EMAIL_SEND)
        )
    ).one()
    assert user.password_reset_token_hash == hash_password_reset_token(token)
    payload = message.payload
    assert token not in str(payload)
    arguments = payload["args"]
    assert isinstance(arguments, dict)
    encrypted_body = str(arguments["encrypted_body"])
    assert token not in encrypted_body
    assert payload["guard"] == {
        "kind": "password_reset",
        "user_id": user.id,
        "token_hash": user.password_reset_token_hash,
    }

    sent: list[str] = []

    class Smtp:
        last_budget_decision: str | None = None
        last_delivery_retryable = False

        async def send(self, _to: str, _subject: str, body: str, *_args: Any) -> bool:
            sent.append(body)
            return True

    smtp = Smtp()
    assert (
        await payment_jobs._send_one_pending_email(message, smtp, db=test_session)
        is None
    )
    assert len(sent) == 1
    assert token in sent[0]
    assert decrypt_secret(encrypted_body) == sent[0]


@pytest.mark.parametrize("state", ["replaced", "consumed", "expired"])
@pytest.mark.asyncio
async def test_reset_outbox_does_not_send_stale_or_used_token(
    state: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "reset-secret-1234567890"
    monkeypatch.setattr(auth_service, "generate_password_reset_token", lambda: token)
    await seed_store_and_admin(
        slug=f"auth-outbox-{state}", email="stale-reset@example.com"
    )
    response = await client.post(
        "/auth/forgot-password", json={"email": "stale-reset@example.com"}
    )
    assert response.status_code == 200

    user = (
        await test_session.scalars(
            select(User).where(User.email == "stale-reset@example.com")
        )
    ).one()
    message = (
        await test_session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == EVENT_EMAIL_SEND)
        )
    ).one()
    if state == "replaced":
        user.password_reset_token_hash = hash_password_reset_token("replacement")
    elif state == "consumed":
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
    else:
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
    await test_session.commit()

    async def must_not_send(*_args: Any, **_kwargs: Any) -> bool:
        pytest.fail("stale reset email reached SMTP")

    monkeypatch.setattr(notification_tasks, "_send_email", must_not_send)
    smtp = SimpleNamespace(last_budget_decision=None, last_delivery_retryable=False)
    assert (
        await payment_jobs._send_one_pending_email(message, smtp, db=test_session)
        is None
    )


@pytest.mark.asyncio
async def test_dispatcher_retries_when_auth_guard_query_fails_before_smtp(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_service, "generate_password_reset_token", lambda: "retry-token"
    )
    await seed_store_and_admin(
        slug="auth-outbox-guard-retry", email="retry-reset@example.com"
    )
    response = await client.post(
        "/auth/forgot-password", json={"email": "retry-reset@example.com"}
    )
    assert response.status_code == 200
    user = (
        await test_session.scalars(
            select(User).where(User.email == "retry-reset@example.com")
        )
    ).one()
    message = (
        await test_session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == EVENT_EMAIL_SEND)
        )
    ).one()

    async def fail_guard(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("temporary database failure")

    monkeypatch.setattr(payment_jobs, "_auth_email_guard_is_current", fail_guard)
    smtp = SimpleNamespace(last_budget_decision=None, last_delivery_retryable=False)

    @asynccontextmanager
    async def fake_smtp_session() -> AsyncIterator[Any]:
        yield smtp

    monkeypatch.setattr(payment_jobs, "smtp_session", fake_smtp_session)
    await payment_jobs._dispatch_pending_emails(test_session, store_id=user.store_id)

    await test_session.refresh(message)
    assert message.processed_at is None
    assert message.attempts == 1
    assert message.error == "auth_guard:RuntimeError"


@pytest.mark.asyncio
async def test_reset_encryption_failure_rolls_back_hash_and_outbox(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "reset-secret-1234567890"
    monkeypatch.setattr(auth_service, "generate_password_reset_token", lambda: token)
    await seed_store_and_admin(
        slug="auth-outbox-atomic", email="atomic-reset@example.com"
    )

    def fail_encrypt(_body: str) -> str:
        raise RuntimeError("encryption failed before persistence")

    monkeypatch.setattr(email_outbox, "encrypt_secret", fail_encrypt)
    with pytest.raises(RuntimeError, match="encryption failed"):
        await auth_service.request_password_reset(
            ForgotPasswordRequest(email="atomic-reset@example.com"),
            test_session,
        )

    async with AsyncSession(test_engine) as verify_db:
        user = (
            await verify_db.scalars(
                select(User).where(User.email == "atomic-reset@example.com")
            )
        ).one()
        messages = (
            await verify_db.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_EMAIL_SEND
                )
            )
        ).all()
    assert user.password_reset_token_hash is None
    assert user.password_reset_expires_at is None
    assert messages == []


@pytest.mark.asyncio
async def test_otp_code_and_encrypted_email_share_the_commit(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_store_and_admin(slug="otp-outbox-atomic", email="otp-admin@example.com")
    store = (await test_session.scalars(select(Store))).one()
    store_id = store.id
    response = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": store.public_id,
            "phone": "+54 9 11 5555-0199",
            "channel": "email",
            "email": "otp-destination@example.com",
        },
    )
    assert response.status_code == 200, response.text
    code = response.json()["data"]["debug_code"]
    messages = (
        await test_session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == EVENT_EMAIL_SEND)
        )
    ).all()
    assert len(messages) == 1
    message = messages[0]
    message_id = message.id
    payload = message.payload
    assert code not in str(payload)
    arguments = payload["args"]
    assert isinstance(arguments, dict)
    body = decrypt_secret(str(arguments["encrypted_body"]))
    assert body is not None and code in body
    guard = payload["guard"]
    assert isinstance(guard, dict)
    assert guard.get("kind") == "otp"
    otp_id = guard.get("otp_id")
    assert isinstance(otp_id, str)
    otp = await test_session.get(OtpVerification, otp_id)
    assert otp is not None
    sent: list[str] = []

    class Smtp:
        last_budget_decision: str | None = None
        last_delivery_retryable = False

        async def send(
            self, _to: str, _subject: str, mail_body: str, *_args: Any
        ) -> bool:
            sent.append(mail_body)
            return True

    smtp = Smtp()
    assert (
        await payment_jobs._send_one_pending_email(message, smtp, db=test_session)
        is None
    )
    assert len(sent) == 1 and code in sent[0]

    otp.consumed_at = datetime.now(timezone.utc)
    await test_session.commit()
    assert (
        await payment_jobs._send_one_pending_email(message, smtp, db=test_session)
        is None
    )
    assert len(sent) == 1

    # If encryption fails after the old code lock/update, the request's
    # transaction rolls back rather than persisting an undeliverable OTP.
    def fail_encrypt(_body: str) -> str:
        raise RuntimeError("encryption failed before persistence")

    monkeypatch.setattr(email_outbox, "encrypt_secret", fail_encrypt)
    with pytest.raises(RuntimeError, match="encryption failed"):
        await client.post(
            "/public/otp/request",
            headers={"x-raw-response": "false"},
            json={
                "store_public_id": store.public_id,
                "phone": "+54 9 11 5555-0200",
                "channel": "email",
                "email": "otp-destination@example.com",
            },
        )

    async with AsyncSession(test_session.bind) as verify_db:
        otps = (
            await verify_db.scalars(
                select(OtpVerification).where(OtpVerification.store_id == store_id)
            )
        ).all()
        persisted_messages = (
            await verify_db.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_EMAIL_SEND
                )
            )
        ).all()
    assert len(otps) == 1
    assert len(persisted_messages) == 1
    assert persisted_messages[0].id == message_id
