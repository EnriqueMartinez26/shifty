from __future__ import annotations

from typing import Literal, cast

from core.crypto import encrypt_secret
from modules.payments.model import EVENT_EMAIL_SEND, JsonValue, OutboxMessage

EmailPriority = Literal["critical", "high", "medium", "low"]


def encrypted_email_outbox_message(
    *,
    store_id: str | None,
    to: str,
    subject: str,
    body: str,
    priority: EmailPriority,
    guard: dict[str, str] | None = None,
) -> OutboxMessage:
    """Create an email event with its body encrypted at rest."""
    encrypted_body = encrypt_secret(body)
    if encrypted_body is None:
        raise ValueError("email outbox body encryption returned no payload")
    arguments: dict[str, JsonValue] = {
        "to": to,
        "subject": subject,
        "encrypted_body": encrypted_body,
        "priority": priority,
    }
    payload: dict[str, JsonValue] = {
        "mail": "encrypted_body",
        "args": arguments,
    }
    if guard is not None:
        payload["guard"] = cast(JsonValue, guard)
    return OutboxMessage(
        store_id=store_id,
        event_type=EVENT_EMAIL_SEND,
        payload=payload,
    )
