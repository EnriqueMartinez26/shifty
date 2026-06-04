from __future__ import annotations

import json
import os
from base64 import b64decode
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import Request

from core.config import settings


class VercelQueueError(RuntimeError):
    """Raised when a Vercel Queue operation fails."""


@dataclass(slots=True)
class QueueMessage:
    message_id: str
    receipt_handle: str
    delivery_count: int
    body: dict[str, Any]


def extract_vercel_oidc_token(request: Request | None = None) -> str | None:
    if request is not None:
        token = request.headers.get("x-vercel-oidc-token")
        if token:
            return token
    return os.getenv("VERCEL_OIDC_TOKEN")


def queue_is_enabled() -> bool:
    return bool(settings.VERCEL_QUEUE_REGION)


def _queue_headers(oidc_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {oidc_token}",
        "Content-Type": "application/json",
    }


def _queue_base_url(topic: str) -> str:
    if not settings.VERCEL_QUEUE_REGION:
        raise VercelQueueError("VERCEL_QUEUE_REGION no está configurado")
    return f"https://{settings.VERCEL_QUEUE_REGION}.vercel-queue.com/api/v3/topic/{topic}"


async def publish_json_message(
    *,
    topic: str,
    payload: dict[str, Any],
    oidc_token: str,
    delay_seconds: int = 0,
    retention_seconds: int = 86400,
    idempotency_key: str | None = None,
) -> None:
    headers = _queue_headers(oidc_token)
    headers["Content-Type"] = "application/json"
    if delay_seconds > 0:
        headers["Vqs-Delay-Seconds"] = str(delay_seconds)
    if retention_seconds > 0:
        headers["Vqs-Retention-Seconds"] = str(retention_seconds)
    if idempotency_key:
        headers["Vqs-Idempotency-Key"] = idempotency_key

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _queue_base_url(topic),
            headers=headers,
            content=json.dumps(payload).encode("utf-8"),
        )
    if response.status_code not in {200, 201, 202}:
        raise VercelQueueError(
            f"No se pudo publicar en Vercel Queue '{topic}': "
            f"{response.status_code} {response.text}"
        )


async def receive_json_messages(
    *,
    topic: str,
    consumer: str,
    oidc_token: str,
    max_messages: int,
    visibility_timeout_seconds: int = 60,
) -> list[QueueMessage]:
    headers = _queue_headers(oidc_token)
    headers["Accept"] = "application/x-ndjson"
    headers["Vqs-Max-Messages"] = str(max_messages)
    headers["Vqs-Visibility-Timeout-Seconds"] = str(visibility_timeout_seconds)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_queue_base_url(topic)}/consumer/{consumer}",
            headers=headers,
        )
    if response.status_code == 204:
        return []
    if response.status_code != 200:
        raise VercelQueueError(
            f"No se pudo recibir mensajes de '{topic}': "
            f"{response.status_code} {response.text}"
        )

    messages: list[QueueMessage] = []
    for line in response.text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            body = json.loads(b64decode(item["body"]).decode("utf-8"))
        except Exception as exc:  # pragma: no cover - depende de API externa
            raise VercelQueueError("Respuesta inválida de Vercel Queue") from exc
        messages.append(
            QueueMessage(
                message_id=item["messageId"],
                receipt_handle=item["receiptHandle"],
                delivery_count=int(item.get("deliveryCount", 0)),
                body=body,
            )
        )
    return messages


async def ack_message(
    *,
    topic: str,
    consumer: str,
    receipt_handle: str,
    oidc_token: str,
) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.delete(
            f"{_queue_base_url(topic)}/consumer/{consumer}/lease/{quote(receipt_handle, safe='')}",
            headers=_queue_headers(oidc_token),
        )
    if response.status_code not in {200, 204}:
        raise VercelQueueError(
            f"No se pudo confirmar el mensaje de '{topic}': "
            f"{response.status_code} {response.text}"
        )
