"""B6-08 (2026-09-19): editar o borrar un servicio no invalidaba la disponibilidad.

Sintoma: ``PATCH /services/{id} {"duration_minutes": 60}`` sobre un servicio de
30 minutos dejaba a la pagina publica ofreciendo los slots de 30 minutos ya
cacheados para ese servicio durante hasta 300 s (``SLOTS_TTL_SECONDS``); y un
servicio borrado se seguia ofreciendo. ``modules/services`` era el unico
camino que cambia la agenda sin tocar el cache.

Un servicio afecta TODOS los dias, y la invalidacion por dia no alcanza (la
disponibilidad publica acepta cualquier fecha; los links de reoferta llegan a
45 dias). Por eso hay una generacion por tienda en la clave de los slots: un
solo INCR la cambia para todos los dias. Los dias se prueban a +60.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _slots(
    client: AsyncClient, store: str, service: str, dia: datetime
) -> list[dict[str, Any]]:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.date().isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    return list(res.json())


def _duraciones(slots: list[dict[str, Any]]) -> set[timedelta]:
    return {
        datetime.fromisoformat(s["ends_at"]) - datetime.fromisoformat(s["starts_at"])
        for s in slots
    }


async def _tienda_con_dia_lejano(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@e.com")
    dia = datetime.now(timezone.utc) + timedelta(days=60)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return store, token, service, dia


@pytest.mark.asyncio
async def test_editar_la_duracion_se_ve_al_instante_en_un_dia_lejano(
    client: AsyncClient,
) -> None:
    store, token, service, dia = await _tienda_con_dia_lejano(client, "b6-08-dur")
    antes = await _slots(client, store, service, dia)
    assert antes, "el dia tiene que tener horarios"
    assert _duraciones(antes) == {timedelta(minutes=30)}

    res = await client.patch(
        f"/services/{service}",
        headers=auth_headers(token),
        json={"duration_minutes": 60},
    )
    assert res.status_code == 200, res.text

    assert _duraciones(await _slots(client, store, service, dia)) == {
        timedelta(minutes=60)
    }


@pytest.mark.asyncio
async def test_borrar_el_servicio_deja_de_ofrecerlo_al_instante(
    client: AsyncClient,
) -> None:
    store, token, service, dia = await _tienda_con_dia_lejano(client, "b6-08-del")
    assert await _slots(client, store, service, dia)

    res = await client.delete(f"/services/{service}", headers=auth_headers(token))
    assert res.status_code == 204, res.text

    assert await _slots(client, store, service, dia) == []


@pytest.mark.asyncio
async def test_desactivar_por_patch_tambien_invalida(client: AsyncClient) -> None:
    """El evento es "el servicio cambio", no "cambio la duracion".

    El precio no viaja en los slots: lo que se prueba es que cualquier PATCH
    (aca precio + ``is_active``) hace recalcular con el estado vigente.
    """
    store, token, service, dia = await _tienda_con_dia_lejano(client, "b6-08-pat")
    assert await _slots(client, store, service, dia)

    res = await client.patch(
        f"/services/{service}",
        headers=auth_headers(token),
        json={"is_active": False, "price": 12345},
    )
    assert res.status_code == 200, res.text
    assert await _slots(client, store, service, dia) == []

    res = await client.patch(
        f"/services/{service}", headers=auth_headers(token), json={"is_active": True}
    )
    assert res.status_code == 200, res.text
    assert await _slots(client, store, service, dia)


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_la_edicion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La invalidacion es best-effort despues del commit."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    import modules.services.router as services_router

    async def _redis_caido(*_args: object) -> None:
        raise RedisConnectionError("redis caido")

    monkeypatch.setattr(services_router, "invalidate_store_availability", _redis_caido)
    store, token, service, _ = await _tienda_con_dia_lejano(client, "b6-08-red")

    res = await client.patch(
        f"/services/{service}",
        headers=auth_headers(token),
        json={"duration_minutes": 45},
    )
    assert res.status_code == 200, res.text
    assert res.json()["duration_minutes"] == 45

    res = await client.delete(f"/services/{service}", headers=auth_headers(token))
    assert res.status_code == 204, res.text
