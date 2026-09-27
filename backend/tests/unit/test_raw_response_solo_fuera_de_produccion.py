"""`x-raw-response` es un interruptor de tests, no un contrato publico (B7-08).

2026-09-19. Sintoma: cualquier cliente que mandara `x-raw-response: true`
recibia la respuesta sin el sobre canonico `{success, data}`, tambien en
produccion. Y la misma decision estaba implementada dos veces con reglas
distintas: en el middleware (`CanonicalJsonMiddleware`, que exigia ademas que
no hubiera `content-disposition`) y en el handler de `CanonicalRoute`, con dos
desenvolturas distintas; `core/router.py` habia tenido que reimplementar la
preservacion de los `Set-Cookie` duplicados.

Decision (OK global del usuario, sugerencia del brief): el header queda
restringido a tests. Una sola capa decide el sobre (el middleware, con
`raw_response_requested`), y con `ENV=production` el header se ignora.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, FastAPI, Response
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from core.config import Environment, settings
from core.responses import CanonicalJsonMiddleware
from core.router import CanonicalAPIRouter

CORE = Path(__file__).resolve().parents[2] / "core"
RAW = {"x-raw-response": "true"}


class Item(BaseModel):
    nombre: str


def _app() -> FastAPI:
    router = CanonicalAPIRouter(prefix="/items")

    @router.get("/uno", response_model=Item)
    async def uno() -> Item:
        return Item(nombre="uno")

    @router.post("/login", response_model=Item)
    async def login(response: Response) -> Item:
        response.set_cookie("access", "a")
        response.set_cookie("refresh", "r")
        return Item(nombre="sesion")

    app = FastAPI()

    @app.get("/plano")
    async def plano() -> dict[str, str]:
        return {"nombre": "plano"}

    app.include_router(router)
    app.add_middleware(CanonicalJsonMiddleware)
    return app


@pytest_asyncio.fixture
async def cliente() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_fuera_de_produccion_el_header_desenvuelve(cliente: AsyncClient) -> None:
    envuelto = (await cliente.get("/items/uno")).json()
    assert envuelto["success"] is True
    assert envuelto["data"] == {"nombre": "uno"}
    assert (await cliente.get("/items/uno", headers=RAW)).json() == {"nombre": "uno"}
    assert (await cliente.get("/plano", headers=RAW)).json() == {"nombre": "plano"}


@pytest.mark.asyncio
async def test_en_produccion_el_header_se_ignora(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    for ruta in ("/items/uno", "/plano"):
        cuerpo = (await cliente.get(ruta, headers=RAW)).json()
        assert cuerpo["success"] is True, (ruta, cuerpo)
        assert "data" in cuerpo


@pytest.mark.asyncio
async def test_desenvolver_conserva_los_set_cookie_duplicados(
    cliente: AsyncClient,
) -> None:
    respuesta = await cliente.post("/items/login", headers=RAW)

    assert respuesta.json() == {"nombre": "sesion"}
    cookies = respuesta.headers.get_list("set-cookie")
    assert any(c.startswith("access=") for c in cookies), cookies
    assert any(c.startswith("refresh=") for c in cookies), cookies


def test_una_sola_capa_lee_el_header() -> None:
    """La decision vive en core/responses.py; core/router.py no la repite."""
    assert "x-raw-response" not in (CORE / "router.py").read_text(encoding="utf-8")
    lecturas = (
        (CORE / "responses.py").read_text(encoding="utf-8").count('"x-raw-response"')
    )
    assert lecturas == 1, lecturas


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [Environment.DEVELOPMENT, Environment.PRODUCTION])
async def test_un_4xx_con_el_header_conserva_el_sobre_de_error(
    env: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regla 20: el header nunca desenvuelve un error, en ningun entorno.

    Contra la app real: el 404 lo arma el handler global de `main.py`
    (`error_response`), y el sobre `{success: false, error_code, message}`
    tiene que llegar igual con `x-raw-response: true`.
    """
    import main

    monkeypatch.setattr(settings, "ENV", env)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        respuesta = await client.get("/no-existe-b7-08", headers=RAW)

    assert respuesta.status_code == 404
    cuerpo = respuesta.json()
    assert cuerpo["success"] is False
    assert cuerpo["error_code"] == "NOT_FOUND"
    assert "message" in cuerpo


def _app_con_tarea(ejecutadas: list[str]) -> FastAPI:
    """Endpoint con una BackgroundTask detras del middleware real.

    El caso real: el envio del OTP y los mails de `/auth/forgot-password`
    salen como `BackgroundTasks`, despues de la respuesta.
    """
    router = CanonicalAPIRouter(prefix="/items")

    @router.post("/con-tarea", response_model=Item)
    async def con_tarea(tareas: BackgroundTasks) -> Item:
        tareas.add_task(ejecutadas.append, "tarea")
        return Item(nombre="ok")

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(CanonicalJsonMiddleware)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [RAW, {}], ids=["con-header", "sin-header"])
async def test_desenvolver_no_descarta_las_background_tasks(
    headers: dict[str, str],
) -> None:
    """2026-09-19 (V-diff de B7-08): el desenvuelto de `core/router.py` armaba un
    `JSONResponse` nuevo sin `background` y las tareas se descartaban en
    silencio. Envuelto o desenvuelto, la tarea tiene que correr."""
    ejecutadas: list[str] = []
    transport = ASGITransport(app=_app_con_tarea(ejecutadas))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        respuesta = await client.post("/items/con-tarea", headers=headers)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo if headers else cuerpo["data"]) == {"nombre": "ok"}
    assert ejecutadas == ["tarea"]
