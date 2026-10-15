"""Reserva publica con adicionales (decision de Mateo, 2026-10-14).

Un adicional suma PRECIO, nunca tiempo. El turno congela el total
(``price_amount`` = servicio con promo + adicionales), la parte de adicionales
(``addons_amount``) y las lineas elegidas (``addons_snapshot``); la sena
porcentual sale sobre el total. Decisiones de Mateo (2026-10-15): la promo
se aplica al TOTAL (servicio + adicionales) y la sena sale del total con
descuento; ``full`` cobra los adicionales; el link del panel cobra precio de
lista + adicionales congelados.

Caso del diseno: servicio de $27.000 con 30 % de sena, 6 "Strass" de $500 =
$3.000 de adicionales, total $30.000, sena $9.000 (no $8.100).

Lo que se fija:

- el alta congela total, adicionales y snapshot, y el cobro es la sena del
  total; el preview dice lo mismo que cobra el alta;
- un adicional que no es del catalogo vigente del servicio es 422
  ``ADDON_UNAVAILABLE`` sin escribir nada; editar el catalogo no toca un
  turno ya tomado;
- la sena por WhatsApp y las dos reprogramaciones (cliente y panel) mudan
  los adicionales con el turno, y ``carry_manual_deposit`` conserva el
  importe;
- el webhook acredita el total y rechaza por integridad el importe sin
  adicionales;
- agenda, busqueda (saldo restante), mails y aviso al dueno los muestran;
- el link del panel cobra tambien los adicionales congelados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage, Payment, PaymentStatus, WebhookInbox
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_staff,
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon, usar_cola_de_reservas
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)

PRECIO = Decimal("27000")
TOTAL = Decimal("30000.00")
ADICIONALES = Decimal("3000.00")
SENA = Decimal("9000.00")  # 30 % de 30.000
TELEFONO = "+5491155577001"


@dataclass(frozen=True)
class _Tienda:
    store: str
    token: str
    servicio: str
    staff: str
    strass: str
    diseno: str
    dia: datetime


async def _tienda(
    client: AsyncClient,
    slug: str,
    *,
    deposit_mode: str = "required",
    deposit_type: str = "percent",
    deposit_amount: int | None = 30,
    mercadopago: bool = False,
) -> _Tienda:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    whatsapp = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"whatsapp_number": "11 5555 0303"},
    )
    assert whatsapp.status_code == 200, whatsapp.text
    if mercadopago:
        await _enable_payments(client, token)
        await _configure_gateway(client, token)
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Unas",
            "duration_minutes": 60,
            "price": float(PRECIO),
            "deposit_mode": deposit_mode,
            "deposit_type": deposit_type,
            "deposit_amount": deposit_amount,
            "addons": [
                {"name": "Strass", "unit_price": 500, "max_quantity": 10},
                {"name": "Diseno", "unit_price": 1500, "max_quantity": 1},
            ],
        },
    )
    assert res.status_code == 201, res.text
    servicio = cast(str, res.json()["public_id"])
    strass, diseno = (a["id"] for a in res.json()["addons"])
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return _Tienda(store, token, servicio, staff, strass, diseno, dia)


def _slot(t: _Tienda, hora: int) -> datetime:
    return t.dia.replace(hour=hora, minute=0, second=0, microsecond=0)


async def _reservar(
    client: AsyncClient,
    t: _Tienda,
    addons: list[dict[str, Any]],
    *,
    hora: int = 13,
    metodo: str = "manual",
    clave: str | None = None,
    **extra: Any,
) -> Response:
    return await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "staff_id": t.staff,
            "starts_at": _slot(t, hora).isoformat(),
            "client_name": "Cliente Adicionales",
            "client_phone": TELEFONO,
            "client_email": "cliente-adicionales@example.com",
            "payment_method": metodo,
            "accepts_terms": True,
            "idempotency_key": clave or f"adic-{t.store}-{hora}-{metodo}",
            "addons": addons,
            **extra,
        },
    )


def _seis_strass(t: _Tienda) -> list[dict[str, Any]]:
    return [{"addon_id": t.strass, "quantity": 6}]


async def _turno(session: AsyncSession, turno: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()


async def _cobro(session: AsyncSession, turno: str) -> Payment:
    session.expire_all()
    return (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()


def _lineas_congeladas(t: _Tienda) -> list[dict[str, Any]]:
    return [
        {
            "addon_id": t.strass,
            "name": "Strass",
            "unit_price": "500.00",
            "quantity": 6,
            "amount": "3000.00",
        }
    ]


# ---------------------------------------------------------------------------
# Alta y preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_reserva_congela_el_total_y_cobra_la_sena_sobre_el_total(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-congela")

    res = await _reservar(client, t, _seis_strass(t))

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["deposit_channel"] == "whatsapp"
    assert Decimal(str(cuerpo["final_price"])) == TOTAL
    assert Decimal(str(cuerpo["service_price"])) == PRECIO
    assert Decimal(str(cuerpo["addons_amount"])) == ADICIONALES
    assert Decimal(str(cuerpo["payment_amount"])) == SENA
    assert cuerpo["addons"] == [
        {
            "addon_id": t.strass,
            "name": "Strass",
            "unit_price": 500.0,
            "quantity": 6,
            "amount": 3000.0,
        }
    ]
    # Un adicional no estira el turno: la duracion es la del servicio.
    inicio = datetime.fromisoformat(cuerpo["starts_at"])
    assert datetime.fromisoformat(cuerpo["ends_at"]) - inicio == timedelta(hours=1)
    turno = await _turno(test_session, cuerpo["public_id"])
    assert turno.price_amount == TOTAL
    assert turno.addons_amount == ADICIONALES
    assert turno.addons_snapshot == _lineas_congeladas(t)
    cobro = await _cobro(test_session, turno.id)
    assert cobro.amount == SENA
    assert cobro.deposit_rule is not None
    assert cobro.deposit_rule["price"] == "30000.00"
    assert cobro.deposit_rule["addons_amount"] == "3000.00"
    # El aviso al dueno nombra los adicionales.
    test_session.expire_all()
    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type
                    == NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert [a.payload["service_name"] for a in avisos] == ["Unas (+ Strass x6)"]


@pytest.mark.asyncio
async def test_sin_adicionales_la_reserva_es_la_de_siempre(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-sin-elegir")

    res = await _reservar(client, t, [])

    assert res.status_code == 201, res.text
    assert res.json()["addons"] == []
    assert res.json()["addons_amount"] == 0
    assert Decimal(str(res.json()["payment_amount"])) == Decimal("8100.00")
    turno = await _turno(test_session, res.json()["public_id"])
    assert (turno.price_amount, turno.addons_amount) == (PRECIO, Decimal("0.00"))
    assert turno.addons_snapshot is None


@pytest.mark.asyncio
async def test_el_preview_dice_lo_mismo_que_cobra_el_alta(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-preview")
    params: list[tuple[str, Any]] = [
        ("store_public_id", t.store),
        ("service_id", t.servicio),
        ("starts_at", _slot(t, 13).isoformat()),
        ("addon", f"{t.strass}:6"),
        ("addon", f"{t.diseno}:1"),
    ]

    preview = await client.get("/public/deposit/preview", params=params)
    reserva = await _reservar(
        client, t, _seis_strass(t) + [{"addon_id": t.diseno, "quantity": 1}]
    )

    assert preview.status_code == 200, preview.text
    assert reserva.status_code == 201, reserva.text
    # 27.000 + 3.000 + 1.500 = 31.500; 30 % = 9.450.
    assert Decimal(str(preview.json()["price"])) == Decimal("31500")
    assert Decimal(str(preview.json()["addons_amount"])) == Decimal("4500")
    assert Decimal(str(preview.json()["amount"])) == Decimal("9450")
    assert preview.json()["amount"] == reserva.json()["payment_amount"]
    assert preview.json()["price"] == reserva.json()["final_price"]
    # Sin ``addon`` el preview es el de siempre.
    sin = await client.get("/public/deposit/preview", params=params[:3])
    assert Decimal(str(sin.json()["amount"])) == Decimal("8100")
    assert sin.json()["addons_amount"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caso",
    ["desconocido", "otro-servicio", "repetido", "mas-que-el-maximo"],
)
async def test_un_adicional_fuera_del_catalogo_vigente_es_422(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, f"adic-422-{caso}")
    otro = await client.post(
        "/services/",
        headers=auth_headers(t.token),
        json={
            "name": "Pies",
            "duration_minutes": 30,
            "price": 1000,
            "addons": [{"name": "Brillo", "unit_price": 100}],
        },
    )
    de_otro_servicio = otro.json()["addons"][0]["id"]
    elegidos = {
        "desconocido": [{"addon_id": "01J000000000000000000000ZZ", "quantity": 1}],
        "otro-servicio": [{"addon_id": de_otro_servicio, "quantity": 1}],
        "repetido": [
            {"addon_id": t.strass, "quantity": 1},
            {"addon_id": t.strass, "quantity": 2},
        ],
        "mas-que-el-maximo": [{"addon_id": t.diseno, "quantity": 2}],
    }[caso]

    res = await _reservar(client, t, elegidos)
    preview = await client.get(
        "/public/deposit/preview",
        params=[
            ("store_public_id", t.store),
            ("service_id", t.servicio),
            ("starts_at", _slot(t, 13).isoformat()),
            *(("addon", f"{e['addon_id']}:{e['quantity']}") for e in elegidos),
        ],
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "ADDON_UNAVAILABLE"
    assert preview.status_code == 422, preview.text
    assert preview.json()["error_code"] == "ADDON_UNAVAILABLE"
    test_session.expire_all()
    assert (await test_session.execute(select(Appointment))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addon",
    ["sin-cantidad", "x:1:2", "id:100", "id:-1", "id con espacio:1"],
)
async def test_el_preview_rechaza_un_adicional_mal_formado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, addon: str
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-preview-malo")

    res = await client.get(
        "/public/deposit/preview",
        params={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "starts_at": _slot(t, 13).isoformat(),
            "addon": addon,
        },
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_la_reserva_rechaza_cantidades_fuera_de_rango_y_listas_largas(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-rango")

    for addons in (
        [{"addon_id": t.strass, "quantity": 0}],
        [{"addon_id": t.strass, "quantity": 100}],
        [{"addon_id": f"id-{i}", "quantity": 1} for i in range(21)],
        [{"addon_id": "no valido!", "quantity": 1}],
    ):
        res = await _reservar(client, t, addons)
        assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_editar_los_adicionales_no_cambia_un_turno_ya_tomado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-editar")
    reserva = await _reservar(client, t, _seis_strass(t))
    assert reserva.status_code == 201, reserva.text

    cambio = await client.patch(
        f"/services/{t.servicio}",
        headers=auth_headers(t.token),
        json={"price": 50000, "addons": [{"name": "Strass", "unit_price": 900}]},
    )

    assert cambio.status_code == 200, cambio.text
    turno = await _turno(test_session, reserva.json()["public_id"])
    assert (turno.price_amount, turno.addons_amount) == (TOTAL, ADICIONALES)
    assert turno.addons_snapshot == _lineas_congeladas(t)
    assert (await _cobro(test_session, turno.id)).amount == SENA
    # El id viejo ya no esta en el catalogo: una reserva nueva con el es 422.
    otra = await _reservar(client, t, _seis_strass(t), hora=15)
    assert otra.status_code == 422, otra.text
    assert otra.json()["error_code"] == "ADDON_UNAVAILABLE"


async def _promo(t: _Tienda, client: AsyncClient, **valores: Any) -> None:
    promo = await client.post(
        "/promotions/",
        headers=auth_headers(t.token),
        json={"title": "Promo", **valores},
    )
    assert promo.status_code == 201, promo.text


@pytest.mark.asyncio
async def test_la_promo_se_aplica_al_total_y_los_previews_dicen_lo_mismo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision de Mateo (2026-10-15): 10 % sobre 27.000 + 3.000 = 27.000; la
    sena del 30 % es 8.100. El preview de la promo y el de la sena (con los
    mismos adicionales) muestran lo que cobra el alta."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-promo")
    await _promo(t, client, code="VERANO10", promotion_type="percent", value=10)
    comunes: list[tuple[str, Any]] = [
        ("store_public_id", t.store),
        ("service_id", t.servicio),
        ("addon", f"{t.strass}:6"),
    ]

    vista_promo = await client.get(
        "/public/promotions/preview", params=[*comunes, ("code", "VERANO10")]
    )
    vista_sena = await client.get(
        "/public/deposit/preview",
        params=[
            *comunes,
            ("starts_at", _slot(t, 13).isoformat()),
            ("promotion_code", "VERANO10"),
        ],
    )
    res = await _reservar(client, t, _seis_strass(t), promotion_code="VERANO10")

    assert vista_promo.status_code == 200, vista_promo.text
    assert (
        Decimal(str(vista_promo.json()["base_amount"])),
        Decimal(str(vista_promo.json()["discount_amount"])),
        Decimal(str(vista_promo.json()["final_amount"])),
    ) == (TOTAL, Decimal("3000"), Decimal("27000"))
    assert vista_sena.status_code == 200, vista_sena.text
    assert Decimal(str(vista_sena.json()["price"])) == Decimal("27000")
    assert Decimal(str(vista_sena.json()["amount"])) == Decimal("8100")
    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert Decimal(str(cuerpo["final_price"])) == Decimal("27000")
    assert Decimal(str(cuerpo["discount_amount"])) == Decimal("3000")
    assert Decimal(str(cuerpo["service_price"])) == PRECIO
    assert Decimal(str(cuerpo["addons_amount"])) == ADICIONALES
    assert cuerpo["payment_amount"] == vista_sena.json()["amount"]
    assert cuerpo["final_price"] == vista_promo.json()["final_amount"]
    turno = await _turno(test_session, cuerpo["public_id"])
    # El total congelado lleva el descuento; los adicionales, sin descuento.
    assert (turno.price_amount, turno.addons_amount) == (
        Decimal("27000.00"),
        ADICIONALES,
    )
    cobro = await _cobro(test_session, turno.id)
    # Antes de la promo: 30 % de 30.000.
    assert (cobro.original_amount, cobro.amount) == (SENA, Decimal("8100.00"))
    assert cobro.discount_amount == Decimal("900.00")
    # Sin ``addon`` el preview de la promo es el de siempre (solo el servicio).
    sola = await client.get(
        "/public/promotions/preview", params=[*comunes[:2], ("code", "VERANO10")]
    )
    assert Decimal(str(sola.json()["final_amount"])) == Decimal("24300")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deposit_type", "deposit_amount", "sena"),
    [
        ("percent", 30, Decimal("300")),
        ("fixed", 5000, Decimal("1000")),
        ("full", None, Decimal("1000")),
    ],
)
async def test_un_descuento_grande_deja_el_total_debajo_de_los_adicionales(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    deposit_type: str,
    deposit_amount: int | None,
    sena: Decimal,
) -> None:
    """Un fijo de 29.000 sobre 30.000 deja un total de 1.000, menor que los
    3.000 de adicionales: la reserva se toma, ``addons_amount`` queda sin
    descuento (lo que dice el snapshot) y la sena sale del total con descuento
    (percent, fixed acotado al total y full)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(
        client,
        f"adic-promo-grande-{deposit_type}",
        deposit_type=deposit_type,
        deposit_amount=deposit_amount,
    )
    await _promo(t, client, code="GRANDE", promotion_type="fixed", value=29000)

    res = await _reservar(client, t, _seis_strass(t), promotion_code="GRANDE")

    assert res.status_code == 201, res.text
    assert Decimal(str(res.json()["final_price"])) == Decimal("1000")
    assert Decimal(str(res.json()["payment_amount"])) == sena
    turno = await _turno(test_session, res.json()["public_id"])
    assert (turno.price_amount, turno.addons_amount) == (
        Decimal("1000.00"),
        ADICIONALES,
    )
    assert turno.addons_snapshot == _lineas_congeladas(t)


@pytest.mark.asyncio
async def test_full_cobra_tambien_los_adicionales(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision de Mateo (2026-10-15)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-full", deposit_type="full", deposit_amount=None)

    res = await _reservar(client, t, _seis_strass(t))

    assert res.status_code == 201, res.text
    assert Decimal(str(res.json()["payment_amount"])) == TOTAL


# ---------------------------------------------------------------------------
# Reprogramar
# ---------------------------------------------------------------------------


async def _verificar_cliente(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, t: _Tienda
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": t.store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": t.store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text


@pytest.mark.asyncio
async def test_la_sena_por_whatsapp_se_muda_con_sus_adicionales(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-reprograma-cliente")
    reserva = await _reservar(client, t, _seis_strass(t))
    assert reserva.status_code == 201, reserva.text
    await _verificar_cliente(client, monkeypatch, t)

    res = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": _slot(t, 16).isoformat(),
            "idempotency_key": "adic-reprograma-cliente-0001",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["addons"] == reserva.json()["addons"]
    assert res.json()["addons_amount"] == 3000.0
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.status == AppointmentStatus.PENDING_PAYMENT.value
    assert (nuevo.price_amount, nuevo.addons_amount) == (TOTAL, ADICIONALES)
    assert nuevo.addons_snapshot == _lineas_congeladas(t)
    # ``carry_manual_deposit``: la misma sena, sin re-tarifar.
    nuevo_id = nuevo.id
    cobro = await _cobro(test_session, nuevo_id)
    assert (cobro.provider, cobro.status, cobro.amount) == ("manual", "pending", SENA)
    test_session.expire_all()
    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type
                    == NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
                )
            )
        )
        .scalars()
        .all()
    )
    del_nuevo = [a for a in avisos if a.payload["appointment_id"] == nuevo_id]
    assert [a.payload["service_name"] for a in del_nuevo] == ["Unas (+ Strass x6)"]


@pytest.mark.asyncio
async def test_reprogramar_desde_el_panel_conserva_los_adicionales(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(
        client, "adic-reprograma-panel", deposit_mode="none", deposit_amount=None
    )
    reserva = await _reservar(client, t, _seis_strass(t))
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["payment_required"] is False

    res = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": _slot(t, 16).isoformat(),
            "idempotency_key": "adic-reprograma-panel-0001",
        },
    )

    assert res.status_code == 200, res.text
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.id != reserva.json()["public_id"]
    assert (nuevo.price_amount, nuevo.addons_amount) == (TOTAL, ADICIONALES)
    assert nuevo.addons_snapshot == _lineas_congeladas(t)


# ---------------------------------------------------------------------------
# Mercado Pago: webhook y link del panel
# ---------------------------------------------------------------------------


def _mercadopago(monkeypatch: pytest.MonkeyPatch, remoto: dict[str, Any]) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-adicionales",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=a",
            }
        return remoto

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _webhook(client: AsyncClient, store: str, pago: str) -> None:
    respuesta = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}",
        json={"id": f"evt-{pago}", "type": "payment", "data": {"id": pago}},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id=pago,
            request_id=f"req-{pago}",
            ts="1710000000",
        ),
    )
    assert respuesta.status_code == 200, respuesta.text


async def _reserva_por_mp(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> tuple[_Tienda, Payment]:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago(monkeypatch, {})
    t = await _tienda(client, slug, mercadopago=True)
    reserva = await _reservar(client, t, _seis_strass(t), metodo="mercadopago")
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["deposit_channel"] == "mercadopago"
    cobro = await _cobro(test_session, reserva.json()["public_id"])
    assert cobro.amount == SENA
    return t, cobro


def _pago_remoto(cobro: Payment, *, pago: str, importe: Decimal) -> dict[str, Any]:
    return {
        "id": pago,
        "status": "approved",
        "external_reference": cobro.current_external_reference,
        "preference_id": cobro.preference_id,
        "transaction_amount": float(importe),
        "currency_id": cobro.currency,
    }


@pytest.mark.asyncio
async def test_el_webhook_acredita_la_sena_del_total(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, cobro = await _reserva_por_mp(client, test_session, monkeypatch, "adic-mp-ok")
    _mercadopago(monkeypatch, _pago_remoto(cobro, pago="mp-total", importe=SENA))

    await _webhook(client, t.store, "mp-total")

    cobro = await _cobro(test_session, cobro.appointment_id)
    assert cobro.status == PaymentStatus.APPROVED.value
    turno = await _turno(test_session, cobro.appointment_id)
    assert turno.status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_el_webhook_rechaza_la_sena_sin_adicionales(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un pago por la sena del servicio solo (30 % de 27.000 = 8.100) no
    coincide con el cobro: integridad, no se acredita."""
    t, cobro = await _reserva_por_mp(client, test_session, monkeypatch, "adic-mp-no")
    _mercadopago(
        monkeypatch,
        _pago_remoto(cobro, pago="mp-sin-adic", importe=Decimal("8100.00")),
    )

    await _webhook(client, t.store, "mp-sin-adic")

    cobro = await _cobro(test_session, cobro.appointment_id)
    assert cobro.status == PaymentStatus.PENDING.value
    turno = await _turno(test_session, cobro.appointment_id)
    assert turno.status == AppointmentStatus.PENDING_PAYMENT.value
    test_session.expire_all()
    inbox = (await test_session.execute(select(WebhookInbox))).scalar_one()
    assert inbox.processed_at is None
    assert "importe" in (inbox.error or "").lower(), inbox.error


@pytest.mark.asyncio
async def test_el_link_del_panel_cobra_tambien_los_adicionales_congelados(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin sena en el servicio, el link del panel cobra el turno entero:
    precio de lista + adicionales congelados (decision de Mateo, 2026-10-15;
    antes, solo el precio de lista)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago(monkeypatch, {})
    t = await _tienda(
        client,
        "adic-link-panel",
        deposit_mode="none",
        deposit_amount=None,
        mercadopago=True,
    )
    reserva = await _reservar(client, t, _seis_strass(t))
    assert reserva.status_code == 201, reserva.text

    link = await client.post(
        f"/payments/preferences/{reserva.json()['public_id']}",
        headers=auth_headers(t.token),
    )

    assert link.status_code == 200, link.text
    assert (await _cobro(test_session, reserva.json()["public_id"])).amount == TOTAL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("con_adicionales", "precio_congelado"),
    [(True, Decimal("27000.00")), (False, Decimal("24300.00"))],
)
async def test_el_link_del_panel_nunca_cobra_mas_que_el_total_con_promo(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    con_adicionales: bool,
    precio_congelado: Decimal,
) -> None:
    """Re-revision de la PR #187 (dinero): un turno con promo congela el total
    con descuento. El link del panel cobraba lista + adicionales SIN descuento
    (30.000 en vez de 27.000) y el saldo, que no baja de cero, lo escondia.
    Ahora se acota al precio congelado, aunque la lista haya subido despues."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago(monkeypatch, {})
    t = await _tienda(
        client,
        f"adic-link-promo-{con_adicionales}",
        deposit_mode="none",
        deposit_amount=None,
        mercadopago=True,
    )
    await _promo(t, client, code="VERANO10", promotion_type="percent", value=10)
    reserva = await _reservar(
        client,
        t,
        _seis_strass(t) if con_adicionales else [],
        promotion_code="VERANO10",
    )
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]
    assert (await _turno(test_session, turno)).price_amount == precio_congelado
    subio = await client.patch(
        f"/services/{t.servicio}", headers=auth_headers(t.token), json={"price": 40000}
    )
    assert subio.status_code == 200, subio.text

    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.token)
    )

    assert link.status_code == 200, link.text
    assert (await _cobro(test_session, turno)).amount == precio_congelado


@pytest.mark.asyncio
async def test_el_link_del_panel_sin_promo_sigue_re_tarifando_con_adicionales(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin promo se conserva el comportamiento deliberado: el link cobra la
    lista de HOY + los adicionales congelados (``test_cobro_del_panel_dos_fases``
    lo fija sin adicionales)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago(monkeypatch, {})
    t = await _tienda(
        client,
        "adic-link-sin-promo",
        deposit_mode="none",
        deposit_amount=None,
        mercadopago=True,
    )
    reserva = await _reservar(client, t, _seis_strass(t))
    assert reserva.status_code == 201, reserva.text
    subio = await client.patch(
        f"/services/{t.servicio}", headers=auth_headers(t.token), json={"price": 40000}
    )
    assert subio.status_code == 200, subio.text

    link = await client.post(
        f"/payments/preferences/{reserva.json()['public_id']}",
        headers=auth_headers(t.token),
    )

    assert link.status_code == 200, link.text
    cobro = await _cobro(test_session, reserva.json()["public_id"])
    assert cobro.amount == Decimal("43000.00")


# ---------------------------------------------------------------------------
# Agenda, busqueda y mails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agenda_y_busqueda_muestran_los_adicionales_y_el_saldo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-agenda")
    reserva = await _reservar(client, t, _seis_strass(t))
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]
    sena = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.token), json={}
    )
    assert sena.status_code == 200, sena.text

    agenda = await client.get(
        f"/appointments/?date={_slot(t, 13).date().isoformat()}",
        headers=auth_headers(t.token),
    )
    busqueda = await client.get("/appointments/search", headers=auth_headers(t.token))

    assert agenda.status_code == 200, agenda.text
    (item,) = [a for a in agenda.json() if a["public_id"] == turno]
    assert item["addons"] == [{"name": "Strass", "quantity": 6}]
    assert busqueda.status_code == 200, busqueda.text
    (resultado,) = [r for r in busqueda.json()["results"] if r["public_id"] == turno]
    assert Decimal(resultado["price_amount"]) == TOTAL
    assert Decimal(resultado["addons_amount"]) == ADICIONALES
    assert Decimal(resultado["payment_amount"]) == SENA
    # Saldo = total - sena: los adicionales tambien se deben.
    assert Decimal(resultado["remaining_amount"]) == TOTAL - SENA


@pytest.mark.asyncio
async def test_el_mail_de_reserva_lista_los_adicionales(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda(client, "adic-mail")

    con = await _reservar(client, t, _seis_strass(t))
    sin = await _reservar(client, t, [], hora=16)
    assert con.status_code == sin.status_code == 201
    await cola.entregar()

    assert len(buzon.enviados) == 2
    (cuerpo_con, cuerpo_sin) = (cuerpo for _para, _asunto, cuerpo in buzon.enviados)
    assert "Adicionales: Strass x6 ($ 3.000) · Total $ 30.000" in cuerpo_con
    assert "Adicionales:" not in cuerpo_sin


@pytest.mark.asyncio
async def test_editar_el_servicio_no_invalida_los_ids_de_una_reserva_en_vuelo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de la PR #187: el panel manda la lista entera en cada edicion.
    Con el mismo precio el id se conserva y el cliente que tenia el catalogo
    abierto (o cacheado en el borde) reserva igual."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-en-vuelo")
    catalogo = await client.get(
        f"/services/{t.servicio}", headers=auth_headers(t.token)
    )
    formulario = [
        {k: a[k] for k in ("id", "name", "unit_price", "max_quantity")}
        for a in catalogo.json()["addons"]
    ]
    editado = await client.patch(
        f"/services/{t.servicio}",
        headers=auth_headers(t.token),
        json={"description": "Con descripcion nueva", "addons": formulario},
    )
    assert editado.status_code == 200, editado.text

    res = await _reservar(client, t, _seis_strass(t))

    assert res.status_code == 201, res.text
    assert Decimal(str(res.json()["final_price"])) == TOTAL


@pytest.mark.asyncio
async def test_cambiar_el_precio_de_un_adicional_invalida_su_id_viejo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regla de dinero: con otro precio el id rota, y el id viejo (el de un
    catalogo cacheado) es 422 en vez de cotizar el precio nuevo."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "adic-precio-nuevo")
    editado = await client.patch(
        f"/services/{t.servicio}",
        headers=auth_headers(t.token),
        json={
            "addons": [
                {
                    "id": t.strass,
                    "name": "Strass",
                    "unit_price": 900,
                    "max_quantity": 10,
                },
                {"id": t.diseno, "name": "Diseno", "unit_price": 1500},
            ]
        },
    )
    assert editado.status_code == 200, editado.text
    nuevo_strass = editado.json()["addons"][0]["id"]
    assert nuevo_strass != t.strass
    assert editado.json()["addons"][1]["id"] == t.diseno

    viejo = await _reservar(client, t, _seis_strass(t))
    nuevo = await _reservar(
        client, t, [{"addon_id": nuevo_strass, "quantity": 6}], hora=15
    )

    assert viejo.status_code == 422, viejo.text
    assert viejo.json()["error_code"] == "ADDON_UNAVAILABLE"
    assert nuevo.status_code == 201, nuevo.text
    turno = await _turno(test_session, nuevo.json()["public_id"])
    assert (turno.price_amount, turno.addons_amount) == (
        Decimal("32400.00"),
        Decimal("5400.00"),
    )
