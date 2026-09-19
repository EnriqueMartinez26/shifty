"""Readiness responde 503 si la base o Redis no responden, y compose lo usa.

2026-09-18, hallazgo B5-17: ``/ops/health/ready`` devolvia 200 con
``"status": "degraded"`` aunque Postgres o Redis estuvieran caidos, y nadie lo
consultaba (ningun ``healthcheck:`` en compose apuntaba al backend). Un
readiness que siempre da 200 no puede sacar la instancia de rotacion.

Decision (OK global del usuario, sugerencia del brief): readiness responde
503 cuando algun componente no responde (cuerpo en la forma canonica de
error, ``SERVICE_NOT_READY``, con el mismo detalle de antes en ``detail``), y
se cablea como ``healthcheck`` del servicio ``backend`` en
``docker-compose.yml``. El liveness (``/ops/health/live``) no cambia.

Revision (V-diff, 2026-09-18): la primera version recibia la sesion por
``Depends(get_db)``, que abre la conexion (``_apply_tenant_context``) ANTES del
``try``: con Postgres caido la respuesta era 500, no 503, y el test lo tapaba
con una sesion falsa que fallaba recien en ``execute``. Ademas nada acotaba el
tiempo: asyncpg espera hasta 60 s la conexion y Redis reintenta. Estos tests
usan conexiones REALES contra un puerto cerrado (rechazo inmediato) y contra
un servidor TCP que acepta y nunca contesta (cuelgue), y exigen 503 en ~2 s.
Regla 20: ni el 503 ni el 200 filtran la excepcion.
"""

import asyncio
import socket
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import core.database
import core.redis
from core.redis import get_redis
from main import app

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
# Tope del chequeo (2 s) + margen para el arranque de la request en CI.
TOPE_SEGUNDOS = 3.5


class _RedisSano:
    async def ping(self) -> bool:
        return True


def _puerto_cerrado() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture
async def puerto_mudo() -> AsyncIterator[int]:
    """Servidor TCP que acepta la conexion y nunca contesta: un cuelgue real."""

    async def no_contestar(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(no_contestar, "127.0.0.1", 0)
    yield int(server.sockets[0].getsockname()[1])
    server.close()


def _usar_redis(monkeypatch: pytest.MonkeyPatch, cliente: object) -> None:
    async def dar_cliente() -> object:
        return cliente

    monkeypatch.setattr(core.redis, "get_redis", dar_cliente)
    app.dependency_overrides[get_redis] = dar_cliente


def _usar_postgres_en(monkeypatch: pytest.MonkeyPatch, puerto: int) -> None:
    engine = create_async_engine(
        f"postgresql+asyncpg://nadie:nada@127.0.0.1:{puerto}/nada",
        poolclass=NullPool,
    )
    monkeypatch.setattr(core.database, "SessionLocal", async_sessionmaker(engine))
    # La version vieja tomaba la sesion de get_db: sin el override del
    # cliente de tests, get_db usa el SessionLocal parcheado (camino real).
    app.dependency_overrides.pop(core.database.get_db, None)


async def _ready(client: AsyncClient) -> tuple[Response, float]:
    inicio = time.monotonic()
    res = await client.get("/ops/health/ready")
    return res, time.monotonic() - inicio


def _es_503_neutro(res: Response, *prohibidos: str) -> None:
    assert res.status_code == 503, res.text
    cuerpo = res.json()
    assert cuerpo["error_code"] == "SERVICE_NOT_READY"
    assert cuerpo["detail"]["status"] == "degraded"
    for texto in prohibidos:
        assert texto not in res.text


@pytest.mark.asyncio
async def test_readiness_da_200_con_base_y_redis_sanos(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _usar_redis(monkeypatch, _RedisSano())
    res, _ = await _ready(client)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_503_si_postgres_rechaza_la_conexion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _usar_redis(monkeypatch, _RedisSano())
    puerto = _puerto_cerrado()
    _usar_postgres_en(monkeypatch, puerto)
    res, demora = await _ready(client)
    _es_503_neutro(res, str(puerto), "ConnectionRefused", "OSError")
    assert demora < TOPE_SEGUNDOS


@pytest.mark.asyncio
async def test_503_en_2_segundos_si_postgres_no_contesta(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, puerto_mudo: int
) -> None:
    _usar_redis(monkeypatch, _RedisSano())
    _usar_postgres_en(monkeypatch, puerto_mudo)
    res, demora = await _ready(client)
    _es_503_neutro(res, "Timeout")
    assert demora < TOPE_SEGUNDOS, demora


@pytest.mark.asyncio
async def test_503_si_redis_rechaza_la_conexion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    puerto = _puerto_cerrado()
    redis = Redis.from_url(f"redis://127.0.0.1:{puerto}/0")
    _usar_redis(monkeypatch, redis)
    try:
        res, demora = await _ready(client)
    finally:
        await redis.aclose()
    _es_503_neutro(res, str(puerto), "ConnectionError")
    assert demora < TOPE_SEGUNDOS


@pytest.mark.asyncio
async def test_503_en_2_segundos_si_redis_no_contesta(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, puerto_mudo: int
) -> None:
    # Sin timeouts propios del cliente: si el chequeo no acotara el tiempo,
    # este ping esperaria para siempre.
    redis = Redis.from_url(f"redis://127.0.0.1:{puerto_mudo}/0")
    _usar_redis(monkeypatch, redis)
    try:
        res, demora = await _ready(client)
    finally:
        await redis.aclose()
    _es_503_neutro(res, "Timeout")
    assert demora < TOPE_SEGUNDOS, demora


@pytest.mark.asyncio
async def test_liveness_no_cambia_aunque_todo_este_caido(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _usar_redis(monkeypatch, Redis.from_url(f"redis://127.0.0.1:{_puerto_cerrado()}"))
    _usar_postgres_en(monkeypatch, _puerto_cerrado())
    res = await client.get("/ops/health/live")
    assert res.status_code == 200, res.text


def test_compose_usa_readiness_como_healthcheck_del_backend() -> None:
    servicios = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    healthcheck = servicios["backend"].get("healthcheck")
    assert healthcheck, "el backend no declara healthcheck"
    comando = " ".join(str(parte) for parte in healthcheck["test"])
    assert "/ops/health/ready" in comando
    # curl -f: un 503 tiene que hacer fallar el chequeo.
    assert "curl" in comando and "-f" in comando
