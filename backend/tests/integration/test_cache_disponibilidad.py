"""La disponibilidad publica refleja al instante reservas, cancelaciones y bloqueos.

Regresion (2026-09-10): la invalidacion del cache nunca coincidia con la clave
escrita; con el Redis de tests (que persiste dentro del test) estos casos
mostraban el estado viejo despues de reservar, cancelar o bloquear.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _estado_del_slot(
    client: AsyncClient, store: str, service: str, staff: str, slot: datetime
) -> str:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": slot.date().isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    objetivo = slot.isoformat()
    for s in res.json():
        if s["staff_id"] == staff and datetime.fromisoformat(s["starts_at"]) == slot:
            return str(s["status"])
    raise AssertionError(f"slot {objetivo} no aparece en la disponibilidad")


async def _tienda(
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


@pytest.mark.asyncio
async def test_reservar_y_cancelar_se_ven_al_instante(client: AsyncClient) -> None:
    store, token, service, staff, slot = await _tienda(client, "cache-rc")
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cache",
            "client_phone": "+5491155550055",
            "idempotency_key": "cache-reserva-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "booked"

    cancel = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/cancel",
        headers=auth_headers(token),
    )
    assert cancel.status_code == 200, cancel.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"


@pytest.mark.asyncio
async def test_bloquear_y_desbloquear_se_ven_al_instante(client: AsyncClient) -> None:
    store, token, service, staff, slot = await _tienda(client, "cache-bl")
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"

    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
            "reason": "Vacaciones",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "blocked"

    borrado = await client.delete(
        f"/appointment-blocks/{bloqueo.json()['public_id']}",
        headers=auth_headers(token),
    )
    assert borrado.status_code in {200, 204}, borrado.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"


@pytest.mark.asyncio
async def test_reserva_revertida_por_falla_de_mp_libera_el_slot_al_instante(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1-10 (2026-09-18): la compensacion no invalidaba la disponibilidad.

    El alta publica commitea el turno, invalida el cache (el slot pasa a
    "booked") y recien despues le pide el link a Mercado Pago. Si MP falla,
    ``_revert_failed_booking`` borraba el turno sin invalidar: quien hubiera
    leido la disponibilidad mientras tanto dejaba cacheado "booked" y el
    cliente que reintentaba veia su horario ocupado hasta que vencia el TTL
    (5 minutos). Aca el visitante concurrente se simula leyendo la
    disponibilidad desde adentro de la llamada a MP que falla.
    """
    import modules.payments.service as payments_service

    store, token = await register_and_login(
        client, slug="cache-mp", email="cache-mp@example.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert gateway.status_code == 200, gateway.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local

    visto_durante_mp: list[str] = []

    async def mp_que_falla(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del access_token, method, path, json_body
        visto_durante_mp.append(
            await _estado_del_slot(client, store, service, staff, slot)
        )
        raise RuntimeError("timeout upstream")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_que_falla)

    assert await _estado_del_slot(client, store, service, staff, slot) == "available"
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cache MP",
            "client_phone": "+5491155550066",
            "payment_method": "mercadopago",
            "idempotency_key": "cache-mp-falla-0001",
        },
    )
    assert reserva.status_code == 502, reserva.text
    # El visitante concurrente vio el turno ya commiteado...
    assert visto_durante_mp == ["booked"]
    # ...y al revertirse, el slot vuelve a estar libre sin esperar el TTL.
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"


@pytest.mark.asyncio
async def test_redis_caido_en_la_compensacion_no_convierte_el_502_en_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1-10, revision 2026-09-18: la invalidacion de la compensacion es best-effort.

    ``invalidate_availability`` no atrapa ``RedisError`` (lo decide el
    llamador). Sin el try/except, un Redis caido justo en la compensacion
    hacia salir la excepcion despues del commit: se salteaba
    ``idempotency_release`` y el cliente recibia un 500 en vez del 502 con
    ``PAYMENT_LINK_CREATION_FAILED``.
    """
    from redis.exceptions import RedisError

    import modules.payments.service as payments_service
    from core.redis import get_redis
    from main import app

    redis_de_test = await app.dependency_overrides[get_redis]()
    incr_original = redis_de_test.incr
    redis_caido = False

    async def incr_que_puede_fallar(key: str) -> int:
        if redis_caido:
            raise RedisError("redis caido")
        return int(await incr_original(key))

    monkeypatch.setattr(redis_de_test, "incr", incr_que_puede_fallar)

    store, token = await register_and_login(
        client, slug="cache-mp-redis", email="cache-mp-redis@example.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert gateway.status_code == 200, gateway.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    async def mp_que_falla_y_tira_redis(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del access_token, method, path, json_body
        nonlocal redis_caido
        redis_caido = True  # Redis se cae justo antes de la compensacion
        raise RuntimeError("timeout upstream")

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", mp_que_falla_y_tira_redis
    )

    clave = "cache-mp-redis-0001"
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Redis Caido",
            "client_phone": "+5491155550077",
            "payment_method": "mercadopago",
            "idempotency_key": clave,
        },
    )

    assert reserva.status_code == 502, reserva.text
    assert reserva.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    # La idempotencia se libero: un reintento no queda trabado.
    assert await redis_de_test.get(f"idempotency:{clave}") is None
    redis_caido = False
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"
