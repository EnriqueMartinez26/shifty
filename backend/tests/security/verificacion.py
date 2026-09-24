"""Chequeos que se aplican a CADA respuesta de la suite de seguridad.

- Un error (4xx/5xx) sale en el sobre canonico de ``core/responses.py``
  (``success``, ``error_code``, ``message`` y opcionalmente ``detail``).
- Ningun cuerpo de error lleva traza, SQL ni nombres internos (regla 20).
- Ninguna respuesta lleva datos de la OTRA tienda que el request no haya
  mandado (devolver el id que uno mismo mando no es una fuga).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import Response

import modules.payments.router as payments_router
import modules.payments.service as payments_service
from core.config import settings
from tests.security.mundo import Llamada, fugas

CLAVES_DEL_SOBRE = {"success", "error_code", "message", "detail"}
# Huellas de una excepcion o una consulta filtrada al cliente. Mayusculas y
# con espacio a proposito: los mensajes de la app estan en castellano.
HUELLAS_INTERNAS = (
    "Traceback",
    'File "',
    "sqlalchemy",
    "sqlite3",
    "asyncpg",
    "psycopg",
    "SELECT ",
    "INSERT INTO",
    "UPDATE ",
    "DELETE FROM",
    " WHERE ",
    "IntegrityError",
    "OperationalError",
    "ProgrammingError",
    "KeyError",
    "AttributeError",
    "TypeError",
    "NoneType",
    "/modules/",
    "\\modules\\",
    '.py"',
)


class Defecto(AssertionError):
    """La app hizo lo que la suite dice que no puede hacer.

    Los ``xfail`` de defectos conocidos llevan ``raises=Defecto``: si el test
    falla por otra cosa (una fabrica rota, un dato de preparacion), el xfail
    no lo tapa y el test falla de verdad.
    """


def exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise Defecto(mensaje)


def xfail_de(motivo: str | None) -> list[pytest.MarkDecorator]:
    if not motivo:
        return []
    return [pytest.mark.xfail(strict=True, raises=Defecto, reason=motivo)]


def cuerpo_json(res: Response) -> Any:
    try:
        return res.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        return None


def problemas_del_error(res: Response) -> list[str]:
    """Lo que esta mal en el cuerpo de un 4xx/5xx (lista vacia: esta bien)."""
    if res.status_code < 400:
        return []
    cuerpo = cuerpo_json(res)
    problemas: list[str] = []
    if not isinstance(cuerpo, dict):
        return [f"cuerpo de error fuera del sobre canonico: {res.text[:200]!r}"]
    if cuerpo.get("success") is not False:
        problemas.append("success no es false")
    if not isinstance(cuerpo.get("error_code"), str) or not cuerpo["error_code"]:
        problemas.append("falta error_code")
    if not isinstance(cuerpo.get("message"), str):
        problemas.append("falta message")
    extra = set(cuerpo) - CLAVES_DEL_SOBRE
    if extra:
        problemas.append(f"claves fuera del sobre: {sorted(extra)}")
    texto = res.text
    problemas.extend(
        f"huella interna {huella!r}" for huella in HUELLAS_INTERNAS if huella in texto
    )
    return problemas


def revisar_respuesta(
    res: Response, llamada: Llamada, marcadores_ajenos: set[str]
) -> None:
    """Sobre canonico en los errores y ninguna fuga de la otra tienda."""
    problemas = problemas_del_error(res)
    exigir(
        not problemas,
        f"{llamada.method} {llamada.url} -> {res.status_code}: {problemas}\n"
        f"{res.text[:500]}",
    )
    filtrado = fugas(res, marcadores_ajenos, llamada.textos_enviados())
    exigir(
        not filtrado,
        f"{llamada.method} {llamada.url} -> {res.status_code} devolvio datos de "
        f"la otra tienda: {filtrado}\n{res.text[:500]}",
    )


async def _mercadopago_falso(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mercado Pago sin red: crea preferencias y falla todo lo demas.

    El webhook enriquece el evento con ``GET /v1/payments/{id}``; ese camino
    ya tolera la falla del proveedor (``processing.py``), que es lo que se
    ejercita.
    """
    if method == "POST" and path == "/checkout/preferences":
        return {
            "id": "pref-suite-seguridad",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?pref=x",
            "sandbox_init_point": "https://sandbox.mercadopago.com/redirect?pref=x",
        }
    raise RuntimeError("Mercado Pago no disponible en la suite de seguridad")


async def _refresh_oauth_falso(db: Any, *, config: Any) -> Any:
    return config


@contextmanager
def pagos_sin_red() -> Iterator[None]:
    """La pasarela configurada para que cada ruta de pagos pueda responder
    2xx sin salir a la red (ni al Mercado Pago real ni a un timeout)."""
    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(payments_service, "_mercadopago_api_request", _mercadopago_falso)
        parche.setattr(
            payments_router,
            "refresh_mercadopago_oauth_connection",
            _refresh_oauth_falso,
        )
        parche.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "cliente-suite")
        parche.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "secreto-suite")
        parche.setattr(
            settings,
            "MERCADOPAGO_OAUTH_REDIRECT_URI",
            "https://api.shifty.test/payments/mercadopago/oauth/callback",
        )
        parche.setattr(
            settings,
            "MERCADOPAGO_OAUTH_AUTH_URL",
            "https://auth.mercadopago.com/authorization",
        )
        yield
