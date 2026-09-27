"""Id del request en cada log (``request_id``), el mismo que registra nginx.

nginx manda ``X-Edge-Request-Id`` con su ``$request_id`` (que tambien va a su
access log como ``rid``). Esta capa lo liga al contexto de structlog
(``merge_contextvars`` en ``core/logging.py``), asi cada evento del backend se
cruza con su linea del borde sin pasarlo a mano. Sin el header -un request que
no paso por nginx- se genera un ULID. El header lo puede mandar cualquiera que
llegue directo al backend: se acepta solo con forma de id, para que no inyecte
texto en los logs. Al terminar el request el contexto vuelve a como estaba.
"""

from __future__ import annotations

import re

import ulid
from starlette.types import ASGIApp, Receive, Scope, Send
from structlog.contextvars import bound_contextvars

EDGE_REQUEST_ID_HEADER = b"x-edge-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _request_id(scope: Scope) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == EDGE_REQUEST_ID_HEADER:
            candidate = bytes(value).decode("latin-1")
            if _VALID_REQUEST_ID.match(candidate):
                return candidate
            break
    return str(ulid.ULID())


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with bound_contextvars(request_id=_request_id(scope)):
            await self.app(scope, receive, send)
