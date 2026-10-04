"""Un cobro retenido por integridad no se le vuelve a preguntar a MP cada minuto.

Seguimiento W2 de la PR #104 (2026-10-03). Desde #104/#112/#113 el job de
retenciones vencidas retiene el turno cuyo pago remoto MP da por APROBADO pero
no pasa la integridad (``_rescatar_o_retener``) y avisa a Sentry una vez por
pago. Pero el turno seguia en ``_expired_holds_query`` y se le volvia a
preguntar a MP en CADA corrida (cada minuto), con el mismo presupuesto de la
fase A (``MP_PHASE_A_BUDGET_SECONDS``) que el resto. Con decenas de retenidos
(una tienda con credenciales de prueba) los retenidos llenaban las paginas de
la corrida, las retenciones nuevas dejaban de vencer y nada avisaba.

Ahora el job sella ``payments.integrity_held_at`` al retener por integridad y
la consulta no vuelve a tomar ese cobro hasta ``EXPIRE_HELD_RECHECK_INTERVAL``
(una hora): una persona que arregla la tienda ve el rescate en la corrida de
la hora siguiente, sin tocar nada. Y si una retencion vencida no se libera
igual (``oldest_overdue_hold_seconds`` de ``/ops/slo`` pasa su umbral), el
job avisa a Sentry.

La version contra Postgres esta en
``tests/postgres/test_pg_vencimiento_retenidos_sin_reconsultar.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from core.config import Environment, settings
from core.observability import OncePer
from modules.appointments.model import AppointmentStatus
from modules.payments.jobs import expire_unpaid_appointments
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_mercadopago
from tests.integration.test_vencimiento_con_cobro_rechazado import (
    _aprobado_de_prueba,
    _estado,
    _mp_por_turno,
    _retencion_vencida,
    _sentry,
)


async def _sellado(session: AsyncSession, cobro: str) -> datetime | None:
    session.expire_all()
    return (
        await session.execute(
            select(Payment.integrity_held_at).where(Payment.id == cobro)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_un_retenido_por_integridad_no_se_reconsulta_en_cada_corrida(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    retenida = await _retencion_vencida(
        client, test_session, "venc-lento-a", vencio_hace=timedelta(hours=2)
    )
    consultas = _mp_por_turno(
        monkeypatch, {retenida.turno: _aprobado_de_prueba(retenida)}
    )
    _sentry(monkeypatch)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    primera = await expire_unpaid_appointments(test_session)
    consultas_primera = sum(retenida.turno in path for path in consultas)
    segunda = await expire_unpaid_appointments(test_session)

    assert primera["held"] == 1, primera
    assert consultas_primera >= 1, "la primera corrida no le pregunto a MP"
    assert await _sellado(test_session, retenida.cobro) is not None
    # La segunda corrida, un minuto despues, ni lo toma ni le pregunta a MP.
    assert (segunda["held"], segunda["inspected"]) == (0, 0), segunda
    assert sum(retenida.turno in path for path in consultas) == consultas_primera
    # Sigue retenido: ni rescatado ni liberado.
    assert await _estado(test_session, retenida) == (
        AppointmentStatus.PENDING_PAYMENT.value,
        PaymentStatus.PENDING.value,
    )


@pytest.mark.asyncio
async def test_la_reconsulta_lenta_toma_el_arreglo_de_una_persona(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pasada la hora, el cobro vuelve a la consulta: si la tienda ya se
    arreglo (aca: MP devuelve el pago real), el turno se rescata solo."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    retenida = await _retencion_vencida(
        client, test_session, "venc-lento-b", vencio_hace=timedelta(hours=3)
    )
    remotos = {retenida.turno: _aprobado_de_prueba(retenida)}
    _mp_por_turno(monkeypatch, remotos)
    _sentry(monkeypatch)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)
    assert (await expire_unpaid_appointments(test_session))["held"] == 1

    # La persona arregla la tienda; antes de la hora, todavia no se mira.
    remotos[retenida.turno] = {**remotos[retenida.turno], "live_mode": True}
    antes = await expire_unpaid_appointments(test_session)
    assert antes["rescued"] == 0, antes
    await test_session.execute(
        update(Payment)
        .where(Payment.id == retenida.cobro)
        .values(
            integrity_held_at=datetime.now(timezone.utc)
            - jobs.EXPIRE_HELD_RECHECK_INTERVAL
            - timedelta(seconds=1)
        )
    )
    await test_session.commit()

    despues = await expire_unpaid_appointments(test_session)

    assert despues["rescued"] == 1, despues
    turno, cobro = await _estado(test_session, retenida)
    assert cobro == PaymentStatus.APPROVED.value
    assert turno != AppointmentStatus.EXPIRED.value


@pytest.mark.asyncio
async def test_muchos_retenidos_no_frenan_a_las_retenciones_nuevas(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mas retenidos que lo que entra en una corrida (``limit`` x paginas):
    antes la corrida se gastaba en ellos y la retencion nueva no vencia
    nunca. Ahora cada retenido se mira una vez y la nueva vence."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(jobs, "EXPIRE_MAX_PAGES", 1)
    _stub_mercadopago(monkeypatch, remote_payment=None)
    retenidas = [
        await _retencion_vencida(
            client, test_session, f"venc-muchos-{n}", vencio_hace=timedelta(hours=5 - n)
        )
        for n in range(2)
    ]
    nueva = await _retencion_vencida(
        client, test_session, "venc-muchos-nueva", vencio_hace=timedelta(minutes=5)
    )
    _mp_por_turno(monkeypatch, {r.turno: _aprobado_de_prueba(r) for r in retenidas})
    _sentry(monkeypatch)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    corridas = [
        await expire_unpaid_appointments(test_session, limit=1) for _ in range(3)
    ]

    assert [c["held"] for c in corridas] == [1, 1, 0], corridas
    assert [c["expired"] for c in corridas] == [0, 0, 1], corridas
    assert (await _estado(test_session, nueva))[0] == AppointmentStatus.EXPIRED.value
    for retenida in retenidas:
        assert (await _estado(test_session, retenida))[0] == (
            AppointmentStatus.PENDING_PAYMENT.value
        )


@pytest.mark.asyncio
async def test_un_error_inesperado_no_se_estaciona(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Solo la integridad estaciona: un deadlock o un timeout puede pasar
    solo, y ese cobro se vuelve a mirar en la corrida siguiente, como antes."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    retenida = await _retencion_vencida(
        client, test_session, "venc-inesperado", vencio_hace=timedelta(hours=1)
    )
    remoto = {**_aprobado_de_prueba(retenida), "live_mode": True}
    _mp_por_turno(monkeypatch, {retenida.turno: remoto})
    _sentry(monkeypatch)

    async def explota(*_args: Any, **_kwargs: Any) -> bool:
        raise ValueError("deadlock simulado")

    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", explota)

    primera = await expire_unpaid_appointments(test_session)
    segunda = await expire_unpaid_appointments(test_session)

    assert (primera["held"], segunda["held"]) == (1, 1), (primera, segunda)
    assert await _sellado(test_session, retenida.cobro) is None


@pytest.mark.asyncio
async def test_una_retencion_vencida_que_no_se_libera_avisa_a_sentry(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El job mide su propio atraso al terminar: si la retencion vencida mas
    vieja que no esta estacionada pasa el umbral del SLO, avisa a Sentry, a
    lo sumo una vez por intervalo."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    umbral = settings.SLO_MAX_OLDEST_OVERDUE_HOLD_SECONDS
    trabada = await _retencion_vencida(
        client,
        test_session,
        "venc-atraso",
        vencio_hace=timedelta(seconds=umbral + 600),
    )
    _mp_por_turno(
        monkeypatch,
        {trabada.turno: {**_aprobado_de_prueba(trabada), "live_mode": True}},
    )
    _sentry(monkeypatch)

    async def explota(*_args: Any, **_kwargs: Any) -> bool:
        raise ValueError("bug al aplicar")

    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", explota)
    avisos: list[dict[str, Any]] = []
    monkeypatch.setattr(
        jobs,
        "report_exception",
        lambda exc, **contexto: avisos.append(
            {"error": type(exc).__name__, **contexto}
        ),
    )
    monkeypatch.setattr(jobs, "_AVISO_DE_ATRASO", OncePer(3600))

    await expire_unpaid_appointments(test_session)
    await expire_unpaid_appointments(test_session)

    assert len(avisos) == 1, avisos
    assert avisos[0]["error"] == "OverdueHoldsLagging"
    assert avisos[0]["oldest_overdue_hold_seconds"] > umbral
    assert avisos[0]["threshold"] == umbral


@pytest.mark.asyncio
async def test_sin_atraso_no_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    await _retencion_vencida(
        client, test_session, "venc-al-dia", vencio_hace=timedelta(minutes=2)
    )
    _mp_por_turno(monkeypatch, {})
    avisos: list[Any] = []
    monkeypatch.setattr(jobs, "report_exception", lambda exc, **c: avisos.append(c))
    monkeypatch.setattr(jobs, "_AVISO_DE_ATRASO", OncePer(3600))

    resultado = await expire_unpaid_appointments(test_session)

    assert resultado["expired"] == 1, resultado
    assert avisos == []
