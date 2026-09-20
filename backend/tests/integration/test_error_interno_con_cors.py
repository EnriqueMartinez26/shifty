"""Un 500 no manejado sale por las mismas capas que cualquier otra respuesta.

AUD2-B7-11 (2026-09-20). `ServerErrorMiddleware` es la capa MAS externa del
stack de Starlette: esta por encima de `CORSMiddleware` y de
`SecurityHeadersMiddleware`, que son solo las mas externas de las de usuario. La
respuesta 500 que arma `unhandled_exception_handler` nacia ahi arriba y por eso
salia sin `access-control-allow-origin`, sin `x-content-type-options`, sin
`x-frame-options` y sin el resto.

Sintoma: un navegador en un origen distinto del de la API (el dev server de
Vite en :5173, o cualquier cliente cross-origin) veia un error de CORS en vez
del sobre canonico, asi que el front no podia ni mostrar "Error interno del
servidor". Peor: el MISMO 500 tenia headers distintos segun por donde saliera,
porque el que arma `dbapi_error_handler` sale por la capa interna y si los
recibe.

En produccion el front y `/api` comparten origen detras de nginx, asi que el
costo directo es bajo; lo que no es bajo es que dos respuestas identicas se
comporten distinto al depurar.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import modules.notifications.tasks as tasks
from main import app
from modules.public_api.service import PublicBookingService
from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_mails_al_cliente import Buzon

ORIGEN_PERMITIDO = "http://localhost:5173"


def _que_reviente(_error: type[Exception]) -> Any:
    async def book(self: PublicBookingService, *args: Any, **kwargs: Any) -> Any:
        raise _error("fallo interno que nadie manejo")

    return book


@pytest.mark.asyncio
async def test_el_500_no_manejado_lleva_cors_y_headers_de_seguridad(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "error-interno-cors")
    monkeypatch.setattr(PublicBookingService, "book", _que_reviente(TypeError))

    transporte = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transporte,
        base_url="http://test",
        headers={"origin": ORIGEN_PERMITIDO},
    ) as sin_reraise:
        res = await sin_reraise.post(
            "/public/appointments", json=_reserva(t, "error-interno-cors-01")
        )

    assert res.status_code == 500, res.text
    assert res.json()["error_code"] == "INTERNAL_SERVER_ERROR"
    assert res.headers.get("access-control-allow-origin") == ORIGEN_PERMITIDO
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert res.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_los_dos_500_salen_con_los_mismos_headers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La asimetria era el sintoma mas confuso: mismo status, otro sobre.

    El 500 de un error de base (que sube re-levantado desde
    `dbapi_error_handler`) y el de cualquier otra excepcion tienen que ser
    indistinguibles desde afuera.
    """
    from sqlalchemy.exc import OperationalError

    from tests.integration.test_deadlock_como_conflicto import _ErrorDelDriver

    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "error-interno-simetria")

    transporte = ASGITransport(app=app, raise_app_exceptions=False)
    headers_por_caso: list[dict[str, str]] = []
    for indice, error in enumerate(
        [
            TypeError("fallo interno que nadie manejo"),
            OperationalError("SELECT 1", {}, _ErrorDelDriver("53300")),
        ]
    ):

        async def book(self: PublicBookingService, *a: Any, **k: Any) -> Any:
            raise error

        monkeypatch.setattr(PublicBookingService, "book", book)
        async with AsyncClient(
            transport=transporte,
            base_url="http://test",
            headers={"origin": ORIGEN_PERMITIDO},
        ) as sin_reraise:
            res = await sin_reraise.post(
                "/public/appointments",
                json=_reserva(t, f"error-interno-simetria-{indice}"),
            )
        assert res.status_code == 500, res.text
        headers_por_caso.append(
            {
                nombre: res.headers.get(nombre, "")
                for nombre in (
                    "access-control-allow-origin",
                    "x-content-type-options",
                    "x-frame-options",
                    "referrer-policy",
                    "cache-control",
                )
            }
        )

    assert headers_por_caso[0] == headers_por_caso[1]
    assert headers_por_caso[0]["access-control-allow-origin"] == ORIGEN_PERMITIDO


@pytest.mark.asyncio
async def test_el_500_sigue_subiendo_para_que_sentry_y_uvicorn_lo_vean(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda de AUD2-B7-01: responder no puede volver a silenciar el error.

    La respuesta se emite desde adentro de las capas, pero la excepcion tiene
    que seguir subiendo hasta `ServerErrorMiddleware` para que uvicorn imprima
    el traceback y el middleware ASGI de Sentry capture el evento.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "error-interno-sube")
    monkeypatch.setattr(PublicBookingService, "book", _que_reviente(TypeError))

    transporte = ASGITransport(app=app, raise_app_exceptions=True)
    async with AsyncClient(transport=transporte, base_url="http://test") as con_reraise:
        with pytest.raises(TypeError, match="fallo interno que nadie manejo"):
            await con_reraise.post(
                "/public/appointments", json=_reserva(t, "error-interno-sube-01")
            )
