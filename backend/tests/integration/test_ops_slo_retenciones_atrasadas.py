"""``GET /ops/slo`` mide la retencion vencida mas vieja que sigue sin liberarse.

Seguimiento W2 de la PR #104 (2026-10-03). El job de retenciones vencidas
corre cada minuto: una retencion cuyo ``expires_at`` paso hace mas de unos
minutos es un job que no da abasto (MP lento, retenidos que llenan las
paginas) o que no corre. ``/ops/slo`` no lo mostraba en ningun lado.

``oldest_overdue_hold_seconds``: antiguedad de la retencion vencida mas vieja
con un cobro vivo o sin cobro, la MISMA condicion que ``_expired_holds_query``.
No cuenta los cobros estacionados por integridad (``integrity_held_at``):
esos ya avisaron a Sentry una vez por pago y esperan a una persona; contarlos
dejaria la metrica en rojo para siempre y taparia justo lo que mide.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from modules.payments.model import Payment
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_mercadopago
from tests.integration.test_vencimiento_con_cobro_rechazado import _retencion_vencida


async def _token_de_superadmin(
    client: AsyncClient, session: AsyncSession, slug: str
) -> str:
    _store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    usuario = (
        await session.execute(select(User).where(User.email == f"{slug}@test.com"))
    ).scalar_one()
    usuario.is_global_admin = True
    await session.commit()
    return token


@pytest.mark.asyncio
async def test_el_slo_mide_la_retencion_vencida_mas_vieja_sin_liberar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    umbral = settings.SLO_MAX_OLDEST_OVERDUE_HOLD_SECONDS
    atrasada = await _retencion_vencida(
        client,
        test_session,
        "slo-hold-a",
        vencio_hace=timedelta(seconds=umbral + 300),
    )
    # Estacionada por integridad y mas vieja: no cuenta.
    estacionada = await _retencion_vencida(
        client, test_session, "slo-hold-b", vencio_hace=timedelta(hours=6)
    )
    await test_session.execute(
        update(Payment)
        .where(Payment.id == estacionada.cobro)
        .values(integrity_held_at=datetime.now(timezone.utc))
    )
    await test_session.commit()
    token = await _token_de_superadmin(client, test_session, "slo-hold-sa")

    res = await client.get("/ops/slo", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    segundos = cuerpo["metrics"]["oldest_overdue_hold_seconds"]
    assert umbral + 300 <= segundos < umbral + 360, (segundos, atrasada)
    assert cuerpo["thresholds"]["oldest_overdue_hold_seconds"] == umbral
    alerta = next(a for a in cuerpo["alerts"] if a["code"] == "overdue_hold_lag_high")
    assert alerta["severity"] == "warning"
    assert cuerpo["status"] == "degraded"


@pytest.mark.asyncio
async def test_el_admin_solo_ve_las_retenciones_de_su_tienda(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    # Otra tienda con una retencion atrasada.
    await _retencion_vencida(
        client, test_session, "slo-hold-otra", vencio_hace=timedelta(hours=2)
    )
    _store, token = await register_and_login(
        client, slug="slo-hold-mia", email="slo-hold-mia@test.com"
    )

    res = await client.get("/ops/slo", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    assert res.json()["metrics"]["oldest_overdue_hold_seconds"] == 0
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_una_retencion_que_todavia_no_vencio_no_es_atraso(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    await _retencion_vencida(
        client, test_session, "slo-hold-viva", vencio_hace=timedelta(minutes=-10)
    )
    token = await _token_de_superadmin(client, test_session, "slo-hold-viva-sa")

    res = await client.get("/ops/slo", headers=auth_headers(token))

    assert res.json()["metrics"]["oldest_overdue_hold_seconds"] == 0


async def _estacionar_cobro(session: AsyncSession, cobro: str) -> None:
    await session.execute(
        update(Payment)
        .where(Payment.id == cobro)
        .values(integrity_held_at=datetime.now(timezone.utc))
    )
    await session.commit()


@pytest.mark.asyncio
async def test_el_slo_cuenta_los_cobros_estacionados_sin_alertar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision S3 (2026-10-03): ``oldest_overdue_hold_seconds`` no cuenta
    los cobros estacionados por integridad, asi que un turno pagado trabado en
    ``pending_payment`` dejaba de verse en cuanto se resolvia el issue de
    Sentry. ``integrity_held_holds`` los cuenta, sin umbral ni alerta, con el
    mismo alcance por tienda."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    mia = await _retencion_vencida(
        client, test_session, "slo-est-mia", vencio_hace=timedelta(hours=3)
    )
    otra = await _retencion_vencida(
        client, test_session, "slo-est-otra", vencio_hace=timedelta(hours=2)
    )
    # Vencida sin estacionar: atraso, no estacionada.
    await _retencion_vencida(
        client, test_session, "slo-est-libre", vencio_hace=timedelta(minutes=1)
    )
    for retencion in (mia, otra):
        await _estacionar_cobro(test_session, retencion.cobro)
    login = await client.post(
        "/auth/login",
        json={"email": "slo-est-mia@test.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    token_admin = login.json()["access_token"]
    token_sa = await _token_de_superadmin(client, test_session, "slo-est-sa")

    global_ = (await client.get("/ops/slo", headers=auth_headers(token_sa))).json()
    tienda = (await client.get("/ops/slo", headers=auth_headers(token_admin))).json()

    assert global_["metrics"]["integrity_held_holds"] == 2, global_["metrics"]
    assert tienda["metrics"]["integrity_held_holds"] == 1, tienda["metrics"]
    # Sin umbral ni alerta: ya avisaron a Sentry una vez por pago.
    assert "integrity_held_holds" not in global_["thresholds"]
    assert all("held" not in a["code"] for a in global_["alerts"]), global_
    # La de la tienda del admin esta estacionada: no es atraso.
    assert tienda["metrics"]["oldest_overdue_hold_seconds"] == 0
