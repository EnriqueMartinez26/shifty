"""Un cobro que no pasa la integridad no frena el vencimiento de las demas.

Revision 4R de la PR #104 (2026-10-02, CRITICO, R1 y R4). El job de
retenciones vencidas le aplica a cada cobro el pago que devuelve Mercado Pago
(``_apply_remote_payment``) para rescatar un turno pagado cuyo webhook se
perdio. Las compuertas nuevas de integridad levantan ``RuntimeError`` (en
produccion un aprobado con ``live_mode`` falso, sin importe, sin collector o
con la tienda sin ``oauth_user_id``) y ese error revertia el lote ENTERO
antes del commit. Como ``_expired_holds_query`` toma los mas viejos primero,
el mismo turno encabezaba cada corrida. Sintoma: un smoke test en produccion
con un vendedor de prueba de MP (aprobado, ``live_mode = false``) frenaba
para siempre el vencimiento de TODAS las tiendas.

Ahora cada cobro va en su savepoint. El que falla no se rescata ni se vence
(si MP lo cobro, liberar el cupo perderia una reserva pagada): queda para una
persona, cuenta como ``held`` y, si MP lo dio por aprobado, llega a Sentry una
vez por (pago de MP, motivo). La corrida sigue con la pagina siguiente para
que los retenidos no tapen al resto.

SQLite alcanza para el aislamiento y la paginacion; la version contra
Postgres (savepoints con ``FOR UPDATE SKIP LOCKED`` y RLS) esta en
``tests/postgres/test_pg_vencimiento_con_cobro_rechazado.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.processing as processing
import modules.payments.service as payments_service
from core.config import Environment, settings
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.jobs import expire_unpaid_appointments
from modules.payments.model import Payment, PaymentGatewayConfig, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)

CUENTA = "COLLECTOR-TIENDA"


@dataclass(frozen=True)
class _Retencion:
    turno: str
    cobro: str
    referencia: str
    importe: float
    moneda: str


async def _retencion_vencida(
    client: AsyncClient,
    session: AsyncSession,
    slug: str,
    *,
    vencio_hace: timedelta,
) -> _Retencion:
    """Una tienda con MP y un turno con sena pendiente cuya retencion vencio."""
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix=slug, hour=10, staff_email=f"pro-{slug}@t.com"
    )
    cobro = (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()
    retencion = _Retencion(
        turno=turno,
        cobro=cobro.id,
        referencia=cobro.current_external_reference,
        importe=float(cobro.amount),
        moneda=cobro.currency,
    )
    await session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(expires_at=datetime.now(timezone.utc) - vencio_hace)
    )
    await session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == cobro.store_id)
        .values(oauth_user_id=CUENTA)
    )
    await session.commit()
    return retencion


def _aprobado_de_prueba(retencion: _Retencion) -> dict[str, Any]:
    """Lo que MP devuelve para el pago de un vendedor de prueba: aprobado,
    completo y con ``live_mode = false``."""
    return {
        "id": f"mp-{retencion.turno}",
        "status": "approved",
        "external_reference": retencion.referencia,
        "transaction_amount": retencion.importe,
        "currency_id": retencion.moneda,
        "collector_id": CUENTA,
        "live_mode": False,
    }


def _mp_por_turno(
    monkeypatch: pytest.MonkeyPatch, remotos: dict[str, dict[str, Any]]
) -> list[str]:
    """La busqueda de MP devuelve el pago del turno que nombra la referencia;
    el resto, ninguno. Devuelve las rutas consultadas."""
    consultas: list[str] = []

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        consultas.append(path)
        for turno, remoto in remotos.items():
            if turno in path:
                return {"results": [remoto]}
        return {"results": []}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)
    return consultas


def _sentry(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    avisos: list[dict[str, Any]] = []

    def fake_report(exc: BaseException, **contexto: Any) -> None:
        avisos.append({"error": str(exc), **contexto})

    monkeypatch.setattr(processing, "report_exception", fake_report)
    return avisos


async def _estado(session: AsyncSession, retencion: _Retencion) -> tuple[str, str]:
    session.expire_all()
    turno = (
        await session.execute(
            select(Appointment.status).where(Appointment.id == retencion.turno)
        )
    ).scalar_one()
    cobro = (
        await session.execute(
            select(Payment.status).where(Payment.id == retencion.cobro)
        )
    ).scalar_one()
    return turno, cobro


@pytest.mark.asyncio
async def test_un_aprobado_de_prueba_en_produccion_no_frena_el_vencimiento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    pagada = await _retencion_vencida(
        client, test_session, "venc-prueba-a", vencio_hace=timedelta(hours=2)
    )
    impaga = await _retencion_vencida(
        client, test_session, "venc-prueba-b", vencio_hace=timedelta(minutes=5)
    )
    _mp_por_turno(monkeypatch, {pagada.turno: _aprobado_de_prueba(pagada)})
    avisos = _sentry(monkeypatch)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    resultado = await expire_unpaid_appointments(test_session)

    assert resultado["expired"] == 1, resultado
    assert resultado["held"] == 1, resultado
    assert resultado["rescued"] == 0, resultado
    # La otra tienda vencio: el cupo vuelve a estar libre.
    assert await _estado(test_session, impaga) == (
        AppointmentStatus.EXPIRED.value,
        PaymentStatus.EXPIRED.value,
    )
    # El de prueba ni se rescato ni se libero: queda para una persona.
    assert await _estado(test_session, pagada) == (
        AppointmentStatus.PENDING_PAYMENT.value,
        PaymentStatus.PENDING.value,
    )
    # Llego a Sentry, solo con ids.
    assert len(avisos) == 1, avisos
    assert avisos[0]["motivo"] == "modo_prueba"
    assert set(avisos[0]) == {
        "error",
        "motivo",
        "store_id",
        "payment_id",
        "mp_payment_id",
    }
    assert avisos[0]["payment_id"] == pagada.cobro
    assert avisos[0]["mp_payment_id"] == f"mp-{pagada.turno}"


@pytest.mark.asyncio
async def test_los_retenidos_no_tapan_a_los_que_siguen_en_la_cola(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con ``limit`` = 1 el retenido ocupa toda la primera pagina: la corrida
    pide la siguiente sin el y vence la otra retencion. Y la corrida
    siguiente no vuelve a avisar a Sentry por el mismo pago y motivo."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    pagada = await _retencion_vencida(
        client, test_session, "venc-cola-a", vencio_hace=timedelta(hours=2)
    )
    impaga = await _retencion_vencida(
        client, test_session, "venc-cola-b", vencio_hace=timedelta(minutes=5)
    )
    _mp_por_turno(monkeypatch, {pagada.turno: _aprobado_de_prueba(pagada)})
    avisos = _sentry(monkeypatch)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    primera = await expire_unpaid_appointments(test_session, limit=1)
    segunda = await expire_unpaid_appointments(test_session, limit=1)

    assert (primera["held"], primera["expired"]) == (1, 1), primera
    assert (segunda["held"], segunda["expired"]) == (1, 0), segunda
    turno, _cobro = await _estado(test_session, impaga)
    assert turno == AppointmentStatus.EXPIRED.value
    assert (await _estado(test_session, pagada))[0] == (
        AppointmentStatus.PENDING_PAYMENT.value
    )
    assert len(avisos) == 1, "una alerta por (pago de MP, motivo), no una por corrida"


@pytest.mark.asyncio
async def test_un_pendiente_de_prueba_tambien_queda_retenido_y_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retenido aunque MP no lo de por aprobado: el turno no se libera solo,
    asi que una persona se entera por Sentry (una vez)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    retenida = await _retencion_vencida(
        client, test_session, "venc-pendiente", vencio_hace=timedelta(hours=1)
    )
    remoto = {**_aprobado_de_prueba(retenida), "status": "pending"}
    _mp_por_turno(monkeypatch, {retenida.turno: remoto})
    avisos = _sentry(monkeypatch)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    resultado = await expire_unpaid_appointments(test_session)
    await expire_unpaid_appointments(test_session)

    assert resultado["held"] == 1, resultado
    assert await _estado(test_session, retenida) == (
        AppointmentStatus.PENDING_PAYMENT.value,
        PaymentStatus.PENDING.value,
    )
    assert [a["motivo"] for a in avisos] == ["modo_prueba"], avisos
