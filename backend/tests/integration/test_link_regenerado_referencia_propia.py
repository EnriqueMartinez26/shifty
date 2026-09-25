"""Un pago del link viejo no se aplica al cobro regenerado, aunque MP no mande
``preference_id`` (revision de perf/f4-pay, 2026-09-25, hallazgo sobre 5d41644).

El pago de Mercado Pago no trae ``preference_id`` (``tests/e2e/README.md``):
la unica senal que distinguia un link del otro no llega. Antes, un
``approved`` tardio del link viejo pasaba la integridad (mismo
``external_reference`` = turno, misma ``metadata``) y el cobro regenerado
quedaba ``approved`` con el link NUEVO vivo: el cliente podia pagar dos veces.

Ahora cada link lleva su nonce en la ``external_reference``
(``<turno>:<Payment.link_ref>``) y la integridad exige la referencia del link
VIGENTE. Un cobro sin ``link_ref`` (link creado antes del deploy) sigue
matcheando con el id del turno solo. La generacion del nonce la prende
``MERCADOPAGO_LINK_REF_ENABLED`` (expand/contract; apagado, todo sigue como
antes).
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from core.config import settings
from modules.payments.model import Payment, PaymentStatus
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado


class _MP:
    """Preferencias nuevas en cada POST, anotando su ``external_reference``."""

    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.referencias: dict[str, str] = {}

    async def __call__(
        self,
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST" and path == "/checkout/preferences"
        assert json_body is not None
        preferencia = f"pref-ref-{next(self._n)}"
        self.referencias[preferencia] = str(json_body["external_reference"])
        return {
            "id": preferencia,
            "init_point": f"https://www.mercadopago.com/checkout?pref={preferencia}",
        }


def _pago_de_mp(cobro: Payment, *, referencia: str, externo: str) -> dict[str, Any]:
    """Un pago como lo manda MP: SIN ``preference_id``."""
    return {
        "status": "approved",
        "data": {
            "id": externo,
            "status": "approved",
            "external_reference": referencia,
            "transaction_amount": float(cobro.amount),
            "currency_id": "ARS",
            "metadata": {
                "appointment_id": cobro.appointment_id,
                "payment_id": cobro.id,
                "store_id": cobro.store_id,
            },
        },
    }


async def _aplicar(
    session: AsyncSession, cobro: Payment, payload: dict[str, Any]
) -> bool:
    try:
        aplicado = await apply_mercadopago_webhook_payload(
            session, store_id=cobro.store_id, payload=payload
        )
    except RuntimeError:
        await session.rollback()
        return False
    await session.commit()
    return aplicado


async def _regenerado(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> tuple[str, _MP, str, str]:
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    t = await _tienda(client, monkeypatch, slug, sena=False)
    mp = _MP()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    turno = await _confirmado(client, t, 13)
    primero = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert primero.status_code == 200, primero.text
    cobro = await _cobro(session, turno)
    vieja = str(cobro.preference_id)
    assert cobro.apply_status(PaymentStatus.EXPIRED.value)
    await session.commit()
    segundo = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert segundo.status_code == 200, segundo.text
    nueva = str((await _cobro(session, turno)).preference_id)
    return turno, mp, vieja, nueva


@pytest.mark.asyncio
async def test_cada_link_tiene_su_referencia_y_todas_apuntan_al_turno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, nueva = await _regenerado(
        client, test_session, monkeypatch, "ref-distinta"
    )

    assert mp.referencias[vieja] != mp.referencias[nueva]
    assert all(r.split(":")[0] == turno for r in mp.referencias.values())
    cobro = await _cobro(test_session, turno)
    assert cobro.current_external_reference == mp.referencias[nueva]


@pytest.mark.asyncio
async def test_un_approved_tardio_del_link_viejo_sin_preference_id_no_se_aplica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, nueva = await _regenerado(
        client, test_session, monkeypatch, "ref-vieja-tarde"
    )
    cobro = await _cobro(test_session, turno)

    aplicado = await _aplicar(
        test_session,
        cobro,
        _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-viejo-1"),
    )

    assert aplicado is False
    cobro = await _cobro(test_session, turno)
    # El link nuevo sigue siendo el unico vivo: el cobro no se acredito.
    assert (cobro.status, cobro.preference_id) == (PaymentStatus.PENDING.value, nueva)
    vencidas = {
        e.payload["preference_id"] for e in await _vencimientos(test_session, turno)
    }
    assert vieja in vencidas and nueva not in vencidas


@pytest.mark.asyncio
async def test_un_approved_del_link_vigente_sin_preference_id_se_aplica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, _vieja, nueva = await _regenerado(
        client, test_session, monkeypatch, "ref-vigente"
    )
    cobro = await _cobro(test_session, turno)

    aplicado = await _aplicar(
        test_session,
        cobro,
        _pago_de_mp(cobro, referencia=mp.referencias[nueva], externo="mp-nuevo-1"),
    )

    assert aplicado is True
    assert (await _cobro(test_session, turno)).status == PaymentStatus.APPROVED.value


@pytest.mark.asyncio
async def test_un_link_de_antes_del_deploy_sigue_matcheando_con_el_turno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un cobro sin ``link_ref`` (link creado antes del deploy) usa la
    referencia de siempre: el id del turno."""
    t = await _tienda(client, monkeypatch, "ref-legada", sena=False)
    turno = await _confirmado(client, t, 13)
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert link.status_code == 200, link.text
    cobro = await _cobro(test_session, turno)
    cobro.link_ref = None
    await test_session.commit()

    aplicado = await _aplicar(
        test_session,
        cobro,
        _pago_de_mp(cobro, referencia=turno, externo="mp-legado-1"),
    )

    assert aplicado is True
    assert (await _cobro(test_session, turno)).status == PaymentStatus.APPROVED.value


@pytest.mark.asyncio
async def test_con_el_flag_apagado_la_referencia_sigue_siendo_el_turno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Primer release (expand): entiende los dos formatos, genera el legado."""
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", False)
    t = await _tienda(client, monkeypatch, "ref-flag-apagado", sena=False)
    mp = _MP()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    turno = await _confirmado(client, t, 13)

    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert link.status_code == 200, link.text
    assert list(mp.referencias.values()) == [turno]
    assert (await _cobro(test_session, turno)).link_ref is None
