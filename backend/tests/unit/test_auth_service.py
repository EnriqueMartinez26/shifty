from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Generator, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, AuthenticationException
from modules.auth import service
from modules.auth.schemas import ChangePasswordRequest, ForgotPasswordRequest
from modules.users.model import User


class ScalarResult:
    def __init__(
        self,
        value: SimpleNamespace | None = None,
        values: list[SimpleNamespace] | None = None,
    ) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self) -> SimpleNamespace | None:
        return self.value

    def scalars(self) -> "ScalarResult":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self.values


class FakeDb:
    def __init__(self, *execute_results: ScalarResult) -> None:
        self.execute_results = list(execute_results)
        self.added: list[Any] = []
        self.commit_count = 0

    async def execute(self, _statement: object) -> ScalarResult:
        if self.execute_results:
            return self.execute_results.pop(0)
        # Consultas auxiliares (p. ej. revocacion de sesiones): vacio.
        return ScalarResult(values=[])

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.fixture(autouse=True)
def skip_tenant_sql(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    async def noop(_db: object) -> None:
        return None

    async def sin_fallos(_key: str) -> int:
        return 0

    async def registrar_noop(_key: str) -> None:
        return None

    monkeypatch.setattr(service, "_apply_tenant_context", noop)
    monkeypatch.setattr(service, "_login_failures", sin_fallos)
    monkeypatch.setattr(service, "_register_login_failure", registrar_noop)
    monkeypatch.setattr(service, "_clear_login_failures", registrar_noop)
    yield


def make_user(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "id": "user-1",
        "public_id": "user-public-1",
        "email": "owner@example.com",
        "hashed_password": "hashed",
        "store_id": "store-1",
        "role": "admin",
        "is_global_admin": False,
        "is_active": True,
        "password_reset_token_hash": None,
        "password_reset_expires_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_normalize_email_strips_whitespace_and_lowercases() -> None:
    assert service.normalize_email("  OWNER@Example.COM  ") == "owner@example.com"


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials_without_creating_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb(ScalarResult(value=make_user()))
    monkeypatch.setattr(service, "verify_password", lambda *_args: False)

    with pytest.raises(AuthenticationException):
        await service.login_user(
            "owner@example.com",
            "wrong-password",
            cast(AsyncSession, db),
            service.SessionClientContext(user_agent="pytest", ip_address="127.0.0.1"),
        )

    assert db.added == []
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_login_creates_refresh_session_and_returns_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    db = FakeDb(ScalarResult(value=user))
    monkeypatch.setattr(service, "verify_password", lambda *_args: True)
    monkeypatch.setattr(
        service, "access_token_for_user", lambda _user, _sid: "access-token"
    )
    monkeypatch.setattr(service, "generate_refresh_token", lambda: "refresh-token")

    tokens = await service.login_user(
        " OWNER@example.com ",
        "correct-password",
        cast(AsyncSession, db),
        service.SessionClientContext(user_agent="pytest", ip_address="127.0.0.1"),
    )

    assert tokens.access_token == "access-token"
    assert tokens.refresh_token == "refresh-token"
    assert db.commit_count == 1
    assert len(db.added) == 1
    session = db.added[0]
    assert session.user_id == user.id
    assert session.store_id == user.store_id
    assert session.refresh_token_hash == service.hash_token("refresh-token")
    assert session.user_agent == "pytest"
    assert session.ip_address == "127.0.0.1"


@pytest.mark.asyncio
async def test_refresh_revokes_existing_session_and_creates_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(id="user-1")
    existing_session = SimpleNamespace(
        user_id=user.id,
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db = FakeDb(ScalarResult(value=existing_session), ScalarResult(value=user))
    monkeypatch.setattr(
        service, "access_token_for_user", lambda _user, _sid: "new-access"
    )
    monkeypatch.setattr(service, "generate_refresh_token", lambda: "new-refresh")

    tokens = await service.refresh_session(
        "old-refresh",
        cast(AsyncSession, db),
        service.SessionClientContext(user_agent="pytest", ip_address="10.0.0.2"),
    )

    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"
    assert existing_session.revoked_at is not None
    assert db.commit_count == 1
    assert len(db.added) == 1
    assert db.added[0].refresh_token_hash == service.hash_token("new-refresh")


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    db = FakeDb()
    monkeypatch.setattr(service, "verify_password", lambda *_args: False)

    with pytest.raises(AppException) as exc:
        await service.change_password(
            ChangePasswordRequest(
                current_password="wrong-password", new_password="new-password9"
            ),
            cast(User, user),
            cast(AsyncSession, db),
        )

    assert exc.value.error_code == "INCORRECT_PASSWORD"
    assert user.hashed_password == "hashed"
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_change_password_hashes_new_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    db = FakeDb()
    # La actual verifica bien; la nueva NO coincide con el hash vigente (el
    # servicio ahora rechaza reutilizar la misma contraseña).
    monkeypatch.setattr(
        service,
        "verify_password",
        lambda password, _hashed: password == "old-password",
    )
    monkeypatch.setattr(service, "hash_password", lambda password: f"hashed:{password}")

    result = await service.change_password(
        ChangePasswordRequest(
            current_password="old-password", new_password="new-password9"
        ),
        cast(User, user),
        cast(AsyncSession, db),
    )

    assert result == {"message": "Contraseña actualizada correctamente"}
    assert user.hashed_password == "hashed:new-password9"
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_request_password_reset_returns_email_and_persists_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(email="owner@example.com")
    db = FakeDb(ScalarResult(value=user))
    monkeypatch.setattr(service, "generate_password_reset_token", lambda: "reset-token")
    monkeypatch.setattr(
        service.settings,
        "FRONTEND_URL",
        "https://app.example.com/",
        raising=False,
    )
    monkeypatch.setattr(
        service.settings,
        "FRONTEND_RESET_PASSWORD_PATH",
        "/reset-password",
        raising=False,
    )

    reset_email = await service.request_password_reset(
        ForgotPasswordRequest(email=" OWNER@example.com "), cast(AsyncSession, db)
    )

    assert reset_email is not None
    assert reset_email.email_to == "owner@example.com"
    assert (
        reset_email.reset_url
        == "https://app.example.com/reset-password?token=reset-token"
    )
    assert user.password_reset_token_hash == service.hash_password_reset_token(
        "reset-token"
    )
    assert user.password_reset_expires_at is not None
    assert db.commit_count == 1
