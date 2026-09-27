"""La busqueda en MP de links retirados tiene tope por cobro y respeta el presupuesto.

Revision de e5579b6..3b977a9 (2026-09-25, #1, RECHAZO). ``_fetch_remote_payment``
hacia 1 + N busquedas en Mercado Pago por cobro (la referencia vigente y las
de TODOS sus links retirados de la ultima semana) y el presupuesto de la fase
A (60 s) solo se miraba entre cobros: un cobro con muchos links retirados
podia pasarse del presupuesto y de los limites de Celery. El job de
vencimiento de retenciones ni siquiera tenia presupuesto.

Ahora:
- se buscan como mucho los ``RETIRED_LINK_SEARCH_MAX`` (2) links retirados
  mas recientes de cada cobro: a lo sumo 3 busquedas por cobro;
- el presupuesto se mira ANTES de cada consulta a MP, tambien a mitad de un
  cobro; un cobro cortado no cuenta como consultado y queda para la corrida
  siguiente;
- el job de vencimiento usa el mismo presupuesto, y un turno cuyo cobro no
  se llego a consultar no se vence en esta corrida.

El reloj es falso: cada busqueda en MP "tarda" 30 s sin dormir de verdad.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.links import RETIRED_LINK_SEARCH_MAX
from modules.payments.model import Payment
from tests.integration.test_expiracion_mp_fuera_del_lock import (
    _mercadopago_que_registra,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)
from tests.integration.test_lotes_mp_con_presupuesto import _Reloj
from tests.integration.test_mails_al_cliente import Buzon

DEMORA_DE_MP = 30.0


def _cobro(numero: int) -> Payment:
    return Payment(
        id=f"cobro-{numero}",
        store_id="tienda-acotada",
        appointment_id=f"turno-{numero}",
        amount=Decimal("100"),
        link_ref=f"vigente-{numero}",
        provider="mercadopago",
    )


def _mp_que_cuenta(
    monkeypatch: pytest.MonkeyPatch, reloj: _Reloj | None = None
) -> list[str]:
    busquedas: list[str] = []

    async def buscar(
        _db: Any, *, external_reference: str, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        busquedas.append(external_reference)
        if reloj is not None:
            reloj.ahora += DEMORA_DE_MP
        return []

    monkeypatch.setattr(jobs, "search_mercadopago_payments", buscar)
    return busquedas


@pytest.mark.asyncio
async def test_un_cobro_con_cinco_links_retirados_hace_como_mucho_tres_busquedas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    busquedas = _mp_que_cuenta(monkeypatch)
    cobro = _cobro(1)
    retiradas = {cobro.id: [f"turno-1:retirado-{i}" for i in range(5)]}

    _remotos, fallidos, consultados = await jobs._remote_payments_for_reconciliation(
        None,  # type: ignore[arg-type]
        [cobro],
        {},
        retiradas,
    )

    assert RETIRED_LINK_SEARCH_MAX == 2
    # La vigente y los dos retirados mas recientes (la lista viene ordenada).
    assert busquedas == [
        "turno-1:vigente-1",
        "turno-1:retirado-0",
        "turno-1:retirado-1",
    ]
    assert (fallidos, consultados) == (0, [cobro.id])


@pytest.mark.asyncio
async def test_el_presupuesto_corta_a_mitad_de_un_cobro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reloj = _Reloj()
    monkeypatch.setattr(jobs, "_reloj", reloj)
    busquedas = _mp_que_cuenta(monkeypatch, reloj)
    primero, segundo = _cobro(1), _cobro(2)
    retiradas = {primero.id: ["turno-1:retirado-0", "turno-1:retirado-1"]}

    _remotos, _fallidos, consultados = await jobs._remote_payments_for_reconciliation(
        None,  # type: ignore[arg-type]
        [primero, segundo],
        {},
        retiradas,
    )

    # 0 s -> 30 s -> 60 s: la tercera busqueda del primer cobro ya no empieza.
    assert busquedas == ["turno-1:vigente-1", "turno-1:retirado-0"]
    assert reloj.transcurrido <= jobs.MP_PHASE_A_BUDGET_SECONDS
    # Cortado a mitad: no cuenta como consultado y lo toma la corrida siguiente.
    assert consultados == []


async def _tres_retenciones_vencidas(
    client: AsyncClient, session: AsyncSession
) -> list[str]:
    tienda, token = await register_and_login(
        client, slug="vence-presupuesto", email="vence-presupuesto@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    profesional = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, profesional, target_date=dia)
    ids: list[str] = []
    for i in range(3):
        alta = await client.post(
            "/public/appointments",
            json={
                "store_public_id": tienda,
                "service_id": servicio,
                "staff_id": profesional,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911555000{i:02d}",
                "payment_method": "mercadopago",
                "accepts_terms": True,
                "idempotency_key": f"vence-presupuesto-{i}",
            },
        )
        assert alta.status_code == 201, alta.text
        ids.append(str(alta.json()["public_id"]))
    await session.execute(
        update(Appointment)
        .where(Appointment.id.in_(ids))
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    )
    await session.commit()
    return ids


@pytest.mark.asyncio
async def test_el_vencimiento_de_retenciones_tiene_presupuesto_y_no_vence_lo_no_consultado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_que_registra(monkeypatch, [], remoto=None)
    ids = await _tres_retenciones_vencidas(client, test_session)
    reloj = _Reloj()
    monkeypatch.setattr(jobs, "_reloj", reloj)
    busquedas = _mp_que_cuenta(monkeypatch, reloj)

    stats = await jobs.expire_unpaid_appointments(test_session)

    # 60 s de presupuesto / 30 s por busqueda: dos cobros consultados.
    assert len(busquedas) == 2, busquedas
    assert stats["expired"] == 2, stats
    test_session.expire_all()
    estados = []
    for turno_id in ids:
        turno = await test_session.get(Appointment, turno_id)
        assert turno is not None
        estados.append(turno.status)
    assert estados.count(AppointmentStatus.EXPIRED.value) == 2
    # El que no se consulto sigue retenido: lo decide la corrida siguiente.
    assert estados.count(AppointmentStatus.PENDING_PAYMENT.value) == 1, estados


@pytest.mark.asyncio
async def test_una_retencion_que_aparece_entre_las_fases_no_se_vence_sin_consultar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de 3b977a9..6c84d46 (#2). La fase B vuelve a leer las
    retenciones vencidas con ``SKIP LOCKED``: una que vencio mientras la fase
    A le preguntaba a MP por las otras (o que entro en el ``limit``) no estaba
    ni en ``remotos`` ni en los cortados por presupuesto, y se vencia sin
    consultar a MP: un turno pagado cuyo webhook no llego se perdia. Ahora la
    fase B solo decide sobre los cobros que la fase A consulto (mas los
    turnos sin cobro de MP) y el resto espera a la corrida siguiente."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_que_registra(monkeypatch, [], remoto=None)
    ids = await _tres_retenciones_vencidas(client, test_session)
    tardio = ids[-1]
    # Todavia no vencio cuando arranca la corrida.
    await test_session.execute(
        update(Appointment)
        .where(Appointment.id == tardio)
        .values(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    )
    await test_session.commit()
    fase_a = jobs._fetch_remote_payments

    async def fase_a_y_vence_otro(*args: Any, **kwargs: Any) -> Any:
        resultado = await fase_a(*args, **kwargs)
        # Vence mientras la fase A le preguntaba a MP por las otras.
        await test_session.execute(
            update(Appointment)
            .where(Appointment.id == tardio)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await AsyncSession.commit(test_session)
        return resultado

    monkeypatch.setattr(jobs, "_fetch_remote_payments", fase_a_y_vence_otro)

    stats = await jobs.expire_unpaid_appointments(test_session)

    assert stats["expired"] == 2, stats
    test_session.expire_all()
    turno = await test_session.get(Appointment, tardio)
    assert turno is not None
    assert turno.status == AppointmentStatus.PENDING_PAYMENT.value
