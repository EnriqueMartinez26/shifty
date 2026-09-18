"""Rafagas sobre endpoints que cobran o crean promociones, contra Postgres (B2-16).

2026-09-17, hallazgo B2-16: CLAUDE.md §4 pide prueba de rafaga para todo
endpoint que reserva, cobra o cambia estado (N a la vez sobre el mismo
recurso: 1 exito, el resto conflictos, cero 5xx). Ninguno de ``/payments``,
``/promotions`` ni ``/ledger`` la tenia: los ``asyncio.gather`` de la suite
estaban todos en reservas, bloqueos, lista de espera y recordatorios.

- ``POST /promotions/`` con el mismo codigo: el pre-chequeo de duplicados no
  es atomico; la ultima defensa es el indice unico parcial
  ``uq_store_promotions_active_code`` (IntegrityError -> 409 neutro).
- ``POST /payments/preferences/{id}`` sobre el mismo turno: la ultima defensa
  es ``uq_payments_store_appointment`` (una sola fila de cobro por turno) y el
  optimistic locking de ``Payment.version`` (StaleDataError -> 409).
- ``POST /payments/{turno}/manual-confirm`` y ``POST /payments/{cobro}/refund``
  sobre el mismo recurso: sin lock de fila, la guarda es la version del
  Payment. Ahi se fija el invariante final (una transicion, un reembolso,
  cero 5xx) en lugar del codigo HTTP de cada respuesta.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
    _stub_preference,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


@pytest.mark.asyncio
async def test_rafaga_de_altas_con_el_mismo_codigo_crea_una_sola_promocion(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-promo-rafaga", email="pg-promo-rafaga@demo.com"
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/promotions/",
                headers=auth_headers(token),
                json={"code": "RAFAGA10", "title": f"Promo {i}", "value": 10},
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert set(codigos) <= {201, 409}, codigos

    async with owner_engine.connect() as conn:
        activas = (
            await conn.execute(
                text(
                    "select count(*) from store_promotions "
                    "where code = 'RAFAGA10' and is_active"
                )
            )
        ).scalar_one()
    assert activas == 1


async def _turno_con_cobro(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str]:
    _store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    # Activar cobros exige la politica de sena publicada (DEPOSIT_POLICY_REQUIRED).
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "deposit_policy": "La sena se descuenta del total y se devuelve con 24hs de aviso."
        },
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return token, cast(str, reserva.json()["public_id"])


@pytest.mark.asyncio
async def test_rafaga_de_links_de_pago_del_mismo_turno_deja_un_solo_cobro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_preference(monkeypatch)
    token, turno = await _turno_con_cobro(client, app_sessions, "pg-cobro-rafaga")

    respuestas = await asyncio.gather(
        *(
            client.post(f"/payments/preferences/{turno}", headers=auth_headers(token))
            for _ in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    # El endpoint es un upsert: los que llegan despues del primer commit
    # reusan el cobro (200); los que chocan en el INSERT o en la version del
    # Payment salen 409. Nunca dos cobros para el mismo turno.
    assert 200 in codigos, codigos
    assert set(codigos) <= {200, 409}, codigos

    async with owner_engine.connect() as conn:
        cobros = (
            await conn.execute(
                # El public_id de un turno es su id (propiedad, no columna).
                text("select count(*) from payments where appointment_id = :turno"),
                {"turno": turno},
            )
        ).scalar_one()
    assert cobros == 1


async def _cobros_del_turno(owner_engine: AsyncEngine, turno: str) -> list[str]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text("select status from payments where appointment_id = :turno"),
            {"turno": turno},
        )
        return [cast(str, estado) for estado in filas.scalars()]


async def _eventos(owner_engine: AsyncEngine, event_type: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text("select count(*) from outbox_messages where event_type = :tipo"),
                {"tipo": event_type},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_rafaga_de_confirmaciones_manuales_del_mismo_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """N confirmaciones manuales simultaneas: una transicion, cero 5xx.

    Se fija el INVARIANTE final y no el codigo de cada respuesta: el grafo
    admite manual_confirmed -> manual_confirmed (``can_apply_payment_status``
    devuelve True si ``attempted == current``), asi que un pedido que llega
    despues del primer commit es un no-op idempotente (200), mientras que uno
    que corre a la par choca con ``uq_payments_store_appointment`` o con la
    version del Payment (409). Ninguna de las dos es un 5xx.

    No se afirma la cantidad de eventos ``payment.manual_confirmed``: cada
    no-op lo republica (hallazgo B2-17, pregunta abierta para el dueno).
    """
    token, turno = await _turno_con_cobro(client, app_sessions, "pg-manual-rafaga")

    respuestas = await asyncio.gather(
        *(
            client.post(
                f"/payments/{turno}/manual-confirm",
                headers=auth_headers(token),
                json={"notes": f"efectivo {i}"},
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert 200 in codigos, codigos
    assert set(codigos) <= {200, 409}, codigos
    # Un solo cobro y un solo estado final: la transicion se aplico una vez.
    assert await _cobros_del_turno(owner_engine, turno) == ["manual_confirmed"]
    pagados = {r.json()["paid_at"] for r in respuestas if r.status_code == 200}
    assert len(pagados) == 1, pagados  # paid_at se sello una sola vez


@pytest.mark.asyncio
async def test_rafaga_de_reembolsos_del_mismo_cobro_registra_uno_solo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """N reembolsos simultaneos del mismo cobro: un reembolso, cero 5xx.

    El primero en commitear pasa el cobro a ``refunded`` (terminal). Los que
    lo leyeron antes chocan con la version del Payment (StaleDataError ->
    409); los que lo leen despues ya no lo ven acreditado (422). Se afirma el
    invariante: un solo evento ``payment.refunded`` y estado final unico.
    """
    token, turno = await _turno_con_cobro(client, app_sessions, "pg-refund-rafaga")
    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={},
    )
    assert confirmado.status_code == 200, confirmado.text
    cobro = confirmado.json()["public_id"]

    respuestas = await asyncio.gather(
        *(
            client.post(
                f"/payments/{cobro}/refund",
                headers=auth_headers(token),
                json={"manual": True, "reason": f"devolucion {i}"},
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    assert set(codigos) <= {200, 409, 422}, codigos
    assert await _cobros_del_turno(owner_engine, turno) == ["refunded"]
    assert await _eventos(owner_engine, "payment.refunded") == 1
