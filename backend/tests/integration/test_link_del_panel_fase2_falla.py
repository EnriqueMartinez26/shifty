"""Los caminos de falla de la fase 2 del link del panel no dejan un link vivo.

Revision de perf/f4-pay (2026-09-25, #3). Dos caminos que no tenian test:

- Choque de version DESPUES de que Mercado Pago creo la preferencia nueva
  (otra escritura toco el cobro mientras MP respondia): el rollback dejaba la
  preferencia nueva viva en MP sin que nadie la registrara. Ahora se manda a
  vencer (``payment.preference.expire``) antes de responder.
- Falla de Mercado Pago al regenerar el link de un cobro vencido: el cobro
  queda ``expired`` con el placeholder (no hay cobro vivo sin link) y el
  vencimiento del link VIEJO, publicado en la fase 1, queda commiteado.

Revision de 7abb9b4..e5579b6 (#7):

- Si MP devolvio un id de preferencia y el codigo falla despues (sin
  ``init_point``), esa preferencia existe en MP: tambien se manda a vencer.
- Si vencer el link sin sellar falla, se loguea y sale el error ORIGINAL.
- Los vencimientos se leen con OTRA sesion despues de un rollback: la del
  test es la misma que la de la app, y una fila solo agregada (o solo
  flusheada) se veia igual aunque nunca se hubiera commiteado.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs

import modules.payments.service as payments_service
from modules.payments.model import (
    EVENT_PREFERENCE_EXPIRE,
    OutboxMessage,
    Payment,
    PaymentStatus,
    is_placeholder_preference_id,
)
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado
from tests.integration.test_regenerar_link_de_cobro_vencido import _con_cobro_vencido


async def _vencimientos_commiteados(
    session: AsyncSession, engine: AsyncEngine
) -> list[str]:
    """Preferencias con ``payment.preference.expire`` COMMITEADO.

    El rollback descarta lo que la sesion compartida con la app tuviera sin
    commitear (agregado o flusheado); la lectura va por otra sesion. En SQLite
    en memoria el engine es StaticPool (una sola conexion): sin el rollback,
    otra sesion veria igual una fila flusheada y no commiteada.
    """
    await session.rollback()
    async with AsyncSession(engine) as otra:
        filas = await otra.execute(
            select(OutboxMessage.payload).where(
                OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
            )
        )
        return [str(p.get("preference_id")) for p in filas.scalars()]


def _mp_que_choca(
    session: AsyncSession, turno: str, creadas: list[str], preferencia: str
) -> Any:
    async def mp(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST"
        # Otra escritura del cobro commiteada mientras MP respondia.
        await session.execute(
            update(Payment)
            .where(Payment.appointment_id == turno)
            .values(version=Payment.version + 1)
            .execution_options(synchronize_session=False)
        )
        await AsyncSession.commit(session)
        creadas.append(preferencia)
        return {
            "id": preferencia,
            "init_point": f"https://www.mercadopago.com/checkout?pref={preferencia}",
        }

    return mp


@pytest.mark.asyncio
async def test_si_la_fase_2_choca_con_la_version_el_link_nuevo_se_vence(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "fase2-version"
    )
    monkeypatch.setattr(
        payments_service,
        "_mercadopago_api_request",
        _mp_que_choca(test_session, turno, creadas, "pref-fase2-huerfana"),
    )

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    assert "pref-fase2-huerfana" in await _vencimientos_commiteados(
        test_session, test_engine
    )
    cobro = await _cobro(test_session, turno)
    assert cobro.preference_id != "pref-fase2-huerfana"


@pytest.mark.asyncio
async def test_si_vencer_el_link_sin_sellar_falla_sale_el_error_original(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "fase2-vencer-falla"
    )
    monkeypatch.setattr(
        payments_service,
        "_mercadopago_api_request",
        _mp_que_choca(test_session, turno, creadas, "pref-fase2-sin-vencer"),
    )

    async def outbox_caido(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("outbox caido")

    monkeypatch.setattr(payments_service, "_discard_unsealed_link", outbox_caido)

    with capture_logs() as logs:
        res = await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
        )

    # El choque de version (409), no el fallo de la compensacion.
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "CONCURRENT_MODIFICATION", res.text
    fallos = [e for e in logs if e["event"] == "panel_link_unsealed_drop_failed"]
    assert len(fallos) == 1, logs
    assert fallos[0]["preference_id"] == "pref-fase2-sin-vencer"


@pytest.mark.asyncio
@pytest.mark.parametrize("cobro_previo", ["nuevo", "vencido"])
async def test_una_preferencia_sin_init_point_se_manda_a_vencer(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    cobro_previo: str,
) -> None:
    """MP creo la preferencia pero no devolvio un link de checkout usable: se
    responde 502 como antes y ademas esa preferencia se vence (existe en MP
    y nadie la registra). Con cobro nuevo el cobro se compensa borrandolo;
    con uno vencido queda con su placeholder."""
    slug = f"fase2-sin-init-{cobro_previo}"
    if cobro_previo == "vencido":
        t, turno, _creadas = await _con_cobro_vencido(
            client, test_session, monkeypatch, slug
        )
    else:
        t = await _tienda(client, monkeypatch, slug, sena=False)
        turno = await _confirmado(client, t, 13)

    async def mp_sin_init_point(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"id": f"pref-sin-link-{cobro_previo}"}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_sin_init_point)

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 502, res.text
    assert f"pref-sin-link-{cobro_previo}" in await _vencimientos_commiteados(
        test_session, test_engine
    )
    cobros = (
        (
            await test_session.execute(
                select(Payment).where(Payment.appointment_id == turno)
            )
        )
        .scalars()
        .all()
    )
    if cobro_previo == "nuevo":
        assert cobros == []
    else:
        assert is_placeholder_preference_id(cobros[0].preference_id)


@pytest.mark.asyncio
async def test_si_mp_falla_al_regenerar_el_cobro_queda_vencido_con_placeholder(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "fase2-mp-caido"
    )
    (vieja,) = creadas

    async def mp_caido(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("mercado pago caido")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_caido)

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 502, res.text
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.EXPIRED.value
    assert is_placeholder_preference_id(cobro.preference_id)
    assert vieja in [
        e.payload["preference_id"] for e in await _vencimientos(test_session, turno)
    ]
