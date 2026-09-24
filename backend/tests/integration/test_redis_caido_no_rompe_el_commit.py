"""Un Redis caido DESPUES del commit no convierte la reserva en un 500.

AUD2-B7-03 (2026-09-20). ``invalidate_availability`` prometia en su docstring
que "nunca falla la operacion de negocio por un Redis caido: el llamador decide
si envuelve en try/except". De los siete llamadores, cuatro no envolvian, y los
cuatro estan DESPUES del ``commit()``. Sintoma: con Redis caido, el alta publica
levantaba ``ConnectionError`` con el turno YA creado en la base, antes de
generar el link de Mercado Pago y antes del mail "reserva registrada". El
cliente veia un 500 y quedaba una reserva fantasma, sin cobro ni aviso.

La tolerancia pasa a vivir adentro de las funciones de invalidacion, asi que un
llamador nuevo nace cubierto (mismo criterio que ``block_writes_when_suspended``
a nivel router). Es best-effort explicito: se loguea con contexto y se reporta a
Sentry, y la respuesta sale 2xx. El caso contrario tambien se prueba: un error
que NO es de Redis sigue subiendo, para que la tolerancia no se vuelva un
silenciador general.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

import core.availability_cache as availability_cache
import modules.notifications.tasks as tasks
from core.redis import get_availability_cache, get_redis
from main import app
from tests.conftest import MockRedis
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


class RedisQueFallaAlInvalidar(MockRedis):
    """Redis que responde lecturas y muere en el ``INCR`` de la invalidacion."""

    async def incr(self, key: str) -> int:
        raise RedisConnectionError(
            "Error 111 connecting to redis:6379. Connection refused."
        )


class RedisQueFallaFeo(MockRedis):
    """Un error que NO es de Redis: tiene que seguir subiendo."""

    async def incr(self, key: str) -> int:
        raise TypeError("bug de programacion, no un Redis caido")


def _usar_redis(doble: MockRedis) -> None:
    async def fake_get_redis() -> MockRedis:
        return doble

    # La invalidacion va al Redis de cache (F0-15): el doble ocupa los dos.
    app.dependency_overrides[get_redis] = fake_get_redis
    app.dependency_overrides[get_availability_cache] = fake_get_redis


async def _tienda_reservable(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    return store, token, service, staff, slot


def _reserva(store: str, service: str, staff: str, slot: datetime) -> dict[str, str]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Carla Ruiz",
        "client_phone": "+5491155550091",
        "accepts_terms": True,
        # Con email real: sin el, el alta inventa uno tecnico .noreply que por
        # contrato no recibe nada, y el test no podria ver el mail.
        "client_email": "carla@example.com",
        "idempotency_key": "redis-caido-000001",
    }


@pytest.mark.asyncio
async def test_alta_publica_con_redis_caido_devuelve_201_y_manda_el_mail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, _token, service, staff, slot = await _tienda_reservable(client, "redis-201")
    _usar_redis(RedisQueFallaAlInvalidar())

    res = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )

    assert res.status_code == 201, res.text
    assert res.json()["public_id"]
    # El mail sale DESPUES de la invalidacion: si esta levanta, nunca se manda.
    assert buzon.enviados, "la reserva quedo sin el mail 'reserva registrada'"


@pytest.mark.asyncio
async def test_cancelar_desde_el_panel_con_redis_caido_devuelve_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda_reservable(client, "redis-200")
    reserva = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )
    assert reserva.status_code == 201, reserva.text
    _usar_redis(RedisQueFallaAlInvalidar())

    cancel = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/cancel",
        headers=auth_headers(token),
    )

    assert cancel.status_code == 200, cancel.text


@pytest.mark.asyncio
async def test_la_invalidacion_fallida_se_loguea_y_se_reporta(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Best-effort no es silencio: queda el log con contexto y el evento."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda_reservable(client, "redis-log")
    _usar_redis(RedisQueFallaAlInvalidar())

    avisos: list[dict[str, Any]] = []
    reportados: list[BaseException] = []
    monkeypatch.setattr(
        availability_cache.logger,
        "warning",
        lambda evento, **kw: avisos.append({"evento": evento, **kw}),
    )
    monkeypatch.setattr(
        availability_cache,
        "report_exception",
        lambda exc, **kw: reportados.append(exc),
    )

    res = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )

    assert res.status_code == 201, res.text
    assert avisos, "la invalidacion fallida no dejo rastro"
    assert avisos[0]["evento"] == "availability_cache_invalidation_failed"
    # store_id interno (RLS), no el public_id de la URL: es el que sirve para
    # ir a buscar las claves en Redis.
    assert avisos[0]["store_id"]
    assert avisos[0]["error_type"] == "ConnectionError"
    assert reportados, "la invalidacion fallida no llego a Sentry"


@pytest.mark.asyncio
async def test_un_error_que_no_es_de_redis_sigue_subiendo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La tolerancia es para Redis caido, no para tapar bugs."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda_reservable(client, "redis-bug")
    _usar_redis(RedisQueFallaFeo())

    with pytest.raises(TypeError):
        await client.post(
            "/public/appointments", json=_reserva(store, service, staff, slot)
        )


@pytest.mark.asyncio
async def test_con_redis_sano_la_invalidacion_sigue_subiendo_la_version(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda sigue viva: sin fallo, el INCR se hace igual que siempre."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    doble = MockRedis()
    _usar_redis(doble)
    store, _token, service, staff, slot = await _tienda_reservable(client, "redis-ok")
    antes = dict(doble.store)

    res = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )

    assert res.status_code == 201, res.text
    versiones = [k for k in doble.store if k.startswith("availability:v:")]
    assert versiones, doble.store
    assert any(doble.store[k] != antes.get(k) for k in versiones)
