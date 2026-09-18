"""Link de pago del panel: commit -> llamada a MP -> compensacion.

2026-09-17, hallazgo B2-10: ``POST /payments/preferences/{appointment_id}``
sostenia la transaccion abierta durante el POST a Mercado Pago (timeout 20 s):
entre el ``flush`` que inserta el ``Payment`` y el ``commit`` del router la
conexion del pool quedaba tomada y la fila nueva bloqueada.

2026-09-18, revision del arreglo (dos defectos que traia la primera version
a dos fases):

- Link con importe viejo: la fase 1 re-tarifaba un cobro existente y
  commiteaba; la fase 2 ya no veia cambio de importe y, con un link real, no
  pedia uno nuevo. El cobro quedaba con el importe nuevo y el link de MP con
  el viejo: el webhook rechaza el importe y el turno no se confirma nunca
  (misma clase que el bug del 2026-09-11).
- Cobro huerfano: con MP caido, el cobro que creo la fase 1 quedaba PENDING
  con placeholder, inflaba la conciliacion y el job lo consultaba a MP en
  cada corrida. Ahora se compensa (se borra junto con su outbox), como
  ``_revert_failed_booking`` en public_api. Un cobro que ya existia no se
  borra: queda con placeholder y el reintento lo refresca.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import _reprice_existing_payment
from modules.services.model import Service

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

LIMITE_DE_LINEAS = 80  # CLAUDE.md regla 29


async def _turno_con_cobro_online(
    client: AsyncClient, token: str, slug: str
) -> tuple[str, str]:
    """(servicio, turno) de una tienda con cobros y gateway configurados."""
    await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return servicio, cast(str, reserva.json()["public_id"])


def _mercadopago_que_anota(
    monkeypatch: pytest.MonkeyPatch, importes: list[float]
) -> None:
    """MP de prueba: anota el unit_price de cada preferencia y da ids distintos."""

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert path.startswith("/checkout/preferences"), path
        items = (json_body or {})["items"]
        importes.append(float(items[0]["unit_price"]))
        n = len(importes)
        return {
            "id": f"pref-real-{n}",
            "init_point": f"https://www.mercadopago.com/checkout/v1/redirect?pref={n}",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _mercadopago_caido(monkeypatch: pytest.MonkeyPatch) -> None:
    async def caido(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Mercado Pago no responde")

    monkeypatch.setattr(payments_service, "create_mercadopago_preference", caido)


@pytest.mark.asyncio
async def test_regenerar_el_link_tras_cambiar_el_precio_pide_uno_con_el_importe_nuevo(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, token = await register_and_login(
        client, slug="panel-reprecio", email="panel-reprecio@test.com"
    )
    servicio, turno = await _turno_con_cobro_online(client, token, "panel-reprecio")
    importes: list[float] = []
    _mercadopago_que_anota(monkeypatch, importes)

    primero = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert primero.status_code == 200, primero.text
    assert importes == [3000.0]  # 30% de 10000
    assert primero.json()["preference_id"] == "pref-real-1"

    # El dueno sube el precio del servicio y regenera el link desde el panel.
    await test_session.execute(
        update(Service).where(Service.public_id == servicio).values(price=20000)
    )
    await test_session.commit()

    segundo = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert segundo.status_code == 200, segundo.text
    # MP se volvio a llamar, con el importe NUEVO, y el cobro quedo con el
    # link nuevo. Antes: una sola llamada y el link viejo de 3000.
    assert importes == [3000.0, 6000.0]
    assert Decimal(segundo.json()["amount"]) == Decimal("6000.00")
    assert segundo.json()["preference_id"] == "pref-real-2"


@pytest.mark.asyncio
async def test_mp_caido_sobre_un_turno_sin_cobro_no_deja_cobro_ni_outbox(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, token = await register_and_login(
        client, slug="panel-huerfano", email="panel-huerfano@test.com"
    )
    _servicio, turno = await _turno_con_cobro_online(client, token, "panel-huerfano")
    _mercadopago_caido(monkeypatch)

    respuesta = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert respuesta.status_code == 502, respuesta.text

    # Compensacion: la fase 1 commiteo el cobro, pero al fallar MP se borro
    # en una transaccion propia junto con su outbox. Sin cobro huerfano que
    # infle la conciliacion.
    await test_session.rollback()
    cobros = (
        (
            await test_session.execute(
                select(Payment).where(Payment.appointment_id == turno)
            )
        )
        .scalars()
        .all()
    )
    assert cobros == []
    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == "payment.preference.created"
                )
            )
        )
        .scalars()
        .all()
    )
    assert avisos == []


@pytest.mark.asyncio
async def test_mp_caido_sobre_un_cobro_existente_no_lo_borra(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, token = await register_and_login(
        client, slug="panel-existente", email="panel-existente@test.com"
    )
    servicio, turno = await _turno_con_cobro_online(client, token, "panel-existente")
    importes: list[float] = []
    _mercadopago_que_anota(monkeypatch, importes)
    primero = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert primero.status_code == 200, primero.text

    await test_session.execute(
        update(Service).where(Service.public_id == servicio).values(price=20000)
    )
    await test_session.commit()
    _mercadopago_caido(monkeypatch)

    respuesta = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert respuesta.status_code == 502, respuesta.text

    await test_session.rollback()
    [cobro] = (
        (
            await test_session.execute(
                select(Payment).where(Payment.appointment_id == turno)
            )
        )
        .scalars()
        .all()
    )
    # El cobro ya existia: no se borra. Queda con el importe nuevo y el link
    # invalidado a placeholder, asi el reintento pide uno nuevo en vez de
    # dejar vivo el link de MP que cobra el importe viejo.
    assert cobro.status == PaymentStatus.PENDING.value
    assert cobro.amount == Decimal("6000.00")
    assert cobro.preference_id == f"pref_{turno}"
    assert cobro.payment_link == f"https://payments.shifty.local/pay/{turno}"


def test_ensure_payment_preference_entra_en_el_limite_de_lineas() -> None:
    """Regla 29: 106 lineas eran deuda declarada, no permiso."""
    fuente = Path(inspect.getsourcefile(payments_service) or "").read_text(
        encoding="utf-8"
    )
    arbol = ast.parse(fuente)
    funcion = next(
        nodo
        for nodo in arbol.body
        if isinstance(nodo, ast.AsyncFunctionDef)
        and nodo.name == "ensure_payment_preference"
    )
    largo = (funcion.end_lineno or funcion.lineno) - funcion.lineno + 1
    assert largo <= LIMITE_DE_LINEAS, f"{largo} lineas"


def test_un_cobro_con_deposit_rule_conserva_su_importe() -> None:
    """La guarda de 2026-09-11 sigue viva dentro de _reprice_existing_payment.

    Regenerar el link desde el panel no re-tarifa un cobro que nacio con la
    regla de sena: pisar el monto dejaba el snapshot mintiendo y rompia para
    siempre la validacion de importe del webhook.
    """
    pago = Payment(
        store_id="tienda",
        appointment_id="turno",
        amount=Decimal("300.00"),
        deposit_rule={"amount": "300.00"},
    )
    cambio = _reprice_existing_payment(
        pago,
        amount=Decimal("150.00"),
        original_amount=Decimal("150.00"),
        discount_amount=Decimal("0.00"),
        promotion_code=None,
        keep_existing_amount=True,
    )
    assert cambio is False
    assert pago.amount == Decimal("300.00")

    # Sin snapshot de regla, el importe si se recalcula (camino del panel para
    # un cobro comun).
    sin_regla = Payment(
        store_id="tienda", appointment_id="otro", amount=Decimal("300.00")
    )
    assert (
        _reprice_existing_payment(
            sin_regla,
            amount=Decimal("150.00"),
            original_amount=Decimal("150.00"),
            discount_amount=Decimal("0.00"),
            promotion_code=None,
            keep_existing_amount=True,
        )
        is True
    )
    assert sin_regla.amount == Decimal("150.00")
