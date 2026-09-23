"""Los caminos de ``/staff/`` y ``/stores/me`` invalidan la disponibilidad.

AUD2-B3-05, 2026-09-20. Sintoma: ``CLAUDE.md`` (Fase 0) manda que TODO camino
que cambia la agenda invalide el cache con ``core/availability_cache``, y la
generacion por tienda (``invalidate_store_availability``, B6-08) la llamaba un
solo sitio: ``modules/services/router.py``. No la llamaba ninguno de los que
cambian los DOS insumos de la grilla --el personal y las reglas del local--:
alta, correccion y borrado de franjas horarias, baja o desactivacion del
profesional, asignacion servicio-profesional, ni ``PATCH /stores/me`` con
``buffer_minutes`` / ``min_booking_notice_hours`` / ``business_hours``.

El dueno borraba la franja del sabado o daba de baja a un profesional y durante
hasta ``SLOTS_TTL_SECONDS`` (300 s) el portal publico seguia ofreciendo esos
horarios; el cliente elegia uno y el alta se lo rechazaba al revalidar el
horario del profesional. Un 4xx sin sentido, no una reserva mala.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
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


async def _alta_de_franja(
    client: AsyncClient, token: str, staff: str, dia: datetime
) -> str:
    res = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "06:00:00",
            "end_time": "18:00:00",
        },
    )
    assert res.status_code == 200, res.text
    return cast(str, res.json()["public_id"])


async def _tienda(
    client: AsyncClient, slug: str, *, dias: int = 60
) -> tuple[str, str, str, str, str, datetime]:
    """Tienda con un profesional, un servicio y una franja en un dia futuro."""
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@e.com")
    dia = datetime.now(timezone.utc) + timedelta(days=dias)
    schedule = await _alta_de_franja(client, token, staff, dia)
    return store, token, service, staff, schedule, dia


@pytest.mark.asyncio
async def test_borrar_la_franja_saca_los_horarios_al_instante(
    client: AsyncClient,
) -> None:
    store, token, service, staff, schedule, dia = await _tienda(client, "b3-05-del")
    assert await _slots(client, store, service, dia), "el dia tiene que tener horarios"

    res = await client.delete(
        f"/staff/{staff}/schedules/{schedule}", headers=auth_headers(token)
    )
    assert res.status_code == 204, res.text

    assert await _slots(client, store, service, dia) == [], (
        "la franja borrada se sigue ofreciendo hasta que vence el TTL"
    )


@pytest.mark.asyncio
async def test_corregir_la_franja_se_ve_al_instante(client: AsyncClient) -> None:
    store, token, service, staff, schedule, dia = await _tienda(client, "b3-05-pat")
    antes = await _slots(client, store, service, dia)
    assert antes

    res = await client.patch(
        f"/staff/{staff}/schedules/{schedule}",
        headers=auth_headers(token),
        json={"end_time": "08:00:00"},
    )
    assert res.status_code == 200, res.text

    despues = await _slots(client, store, service, dia)
    assert despues and len(despues) < len(antes), (
        "la franja acortada no se refleja: el portal sigue con la grilla vieja"
    )


@pytest.mark.asyncio
async def test_dar_de_baja_al_profesional_lo_saca_de_la_grilla(
    client: AsyncClient,
) -> None:
    store, token, service, staff, _schedule, dia = await _tienda(client, "b3-05-baja")
    assert await _slots(client, store, service, dia)

    res = await client.delete(f"/staff/{staff}", headers=auth_headers(token))
    assert res.status_code == 204, res.text

    assert await _slots(client, store, service, dia) == []


@pytest.mark.asyncio
async def test_desactivar_al_profesional_por_patch_tambien_invalida(
    client: AsyncClient,
) -> None:
    store, token, service, staff, _schedule, dia = await _tienda(client, "b3-05-off")
    assert await _slots(client, store, service, dia)

    res = await client.patch(
        f"/staff/{staff}", headers=auth_headers(token), json={"is_active": False}
    )
    assert res.status_code == 200, res.text
    assert await _slots(client, store, service, dia) == []

    res = await client.patch(
        f"/staff/{staff}", headers=auth_headers(token), json={"is_active": True}
    )
    assert res.status_code == 200, res.text
    assert await _slots(client, store, service, dia)


@pytest.mark.asyncio
async def test_quitarle_el_servicio_al_profesional_lo_saca_de_ese_servicio(
    client: AsyncClient,
) -> None:
    """La asignacion servicio-profesional es tambien un insumo de la grilla."""
    store, token, service, staff, _schedule, dia = await _tienda(client, "b3-05-svc")
    assert await _slots(client, store, service, dia)

    res = await client.patch(
        f"/staff/{staff}/services", headers=auth_headers(token), json=[]
    )
    assert res.status_code == 200, res.text

    assert await _slots(client, store, service, dia) == []


@pytest.mark.asyncio
async def test_cambiar_la_antelacion_minima_del_local_se_ve_al_instante(
    client: AsyncClient,
) -> None:
    store, token, service, _staff, _schedule, dia = await _tienda(
        client, "b3-05-tienda", dias=2
    )
    antes = await _slots(client, store, service, dia)
    assert antes and all(slot["reason"] is None for slot in antes)

    # 168 horas = una semana, el maximo del schema: el dia +2 queda adentro de
    # la antelacion minima y deja de ser reservable. Con ``force_all`` los
    # slots se siguen listando, pero con el motivo del rechazo.
    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"min_booking_notice_hours": 168},
    )
    assert res.status_code == 200, res.text

    despues = await _slots(client, store, service, dia)
    assert despues and all(slot["reason"] for slot in despues), (
        "la regla nueva del local no se refleja hasta que vence el TTL"
    )


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_la_edicion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La invalidacion es best-effort y va DESPUES del commit."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    import modules.staff.service as staff_service
    import modules.stores.router as stores_router

    async def _redis_caido(*_args: object) -> None:
        raise RedisConnectionError("redis caido")

    monkeypatch.setattr(staff_service, "invalidate_store_availability", _redis_caido)
    monkeypatch.setattr(stores_router, "invalidate_store_availability", _redis_caido)
    store, token, _service, staff, schedule, _dia = await _tienda(client, "b3-05-red")
    assert store

    res = await client.delete(
        f"/staff/{staff}/schedules/{schedule}", headers=auth_headers(token)
    )
    assert res.status_code == 204, res.text

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 10}
    )
    assert res.status_code == 200, res.text
    assert res.json()["buffer_minutes"] == 10
