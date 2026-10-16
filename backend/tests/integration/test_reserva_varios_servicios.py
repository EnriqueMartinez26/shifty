"""Varios servicios del mismo profesional en UN turno (decision de Mateo, 2026-10-16).

Contrato fijo con el front (``extra_service_ids`` en el alta,
``extra_service_id`` repetible en disponibilidad y previews, ``extra_services``
y ``services_label`` en las respuestas, flag ``multi_service_booking``) y las
reglas de la decision:

- el turno dura la suma y cuesta la suma; ``service_id`` es el principal (el
  primero elegido) y los demas se congelan en ``extra_services_snapshot``;
- hasta 3 servicios (422 ``TOO_MANY_SERVICES``) y 480 minutos (422
  ``SERVICES_TOO_LONG``); con el flag apagado, 422 ``MULTI_SERVICE_DISABLED``;
- la sena es la regla MAS ALTA entre los servicios con sena, sobre el TOTAL
  (servicios + adicionales, con la promo): Corte $10.000 con 50 % + Barba
  $5.000 sin sena -> $7.500. Los previews dicen lo mismo que cobra el alta;
- un solo profesional que haga TODOS; las dos reprogramaciones conservan la
  duracion y las lineas; el link del panel cobra la lista de hoy de cada linea;
- los reportes cuentan el principal y los mails dicen "Corte + Barba".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.utils import ARGENTINA_TZ
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage, Payment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon, usar_cola_de_reservas
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)
from tests.integration.test_reserva_con_adicionales import _verificar_cliente

TELEFONO = "+5491155577001"
CORTE_PRECIO = Decimal("10000")
BARBA_PRECIO = Decimal("5000")
TOTAL = Decimal("15000.00")
SENA = Decimal("7500.00")  # 50 % del total, la regla del Corte
DURACION = timedelta(minutes=50)  # 30 + 20


@dataclass(frozen=True)
class _Tienda:
    slug: str
    store: str
    token: str
    corte: str
    barba: str
    color: str
    diseno: str
    aceite: str
    brillo: str
    ana: str
    beto: str
    dia: datetime


async def _servicio(
    client: AsyncClient, token: str, nombre: str, minutos: int, precio: Decimal,
    *, modo: str = "none", tipo: str = "percent", monto: int | None = None,
    adicional: tuple[str, int, int] | None = None,
) -> tuple[str, str | None]:  # fmt: skip
    cuerpo: dict[str, Any] = {
        "name": nombre,
        "duration_minutes": minutos,
        "price": float(precio),
        "deposit_mode": modo,
        "deposit_type": tipo,
        "deposit_amount": monto,
    }
    if adicional:
        cuerpo["addons"] = [
            {
                "name": adicional[0],
                "unit_price": adicional[1],
                "max_quantity": adicional[2],
            }
        ]
    res = await client.post("/services/", headers=auth_headers(token), json=cuerpo)
    assert res.status_code == 201, res.text
    addons = res.json().get("addons") or []
    return cast(str, res.json()["public_id"]), (addons[0]["id"] if addons else None)


async def _profesional(
    client: AsyncClient, token: str, nombre: str, servicios: list[str], email: str
) -> str:
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": nombre,
            "first_name": nombre,
            "last_name": "Demo",
            "email": email,
            "service_ids": servicios,
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _prender_flag(client: AsyncClient, token: str, prendido: bool = True) -> None:
    res = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"multi_service_booking": prendido},
    )
    assert res.status_code == 200, res.text
    assert res.json()["flags"]["multi_service_booking"] is prendido


async def _tienda(
    client: AsyncClient,
    slug: str,
    *,
    flag: bool = True,
    corte_modo: str = "required",
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
    corte, diseno = await _servicio(
        client, token, "Corte", 30, CORTE_PRECIO, modo=corte_modo, monto=50,
        adicional=("Diseno", 1000, 1),
    )  # fmt: skip
    barba, aceite = await _servicio(
        client, token, "Barba", 20, BARBA_PRECIO, adicional=("Aceite", 500, 3)
    )
    color, brillo = await _servicio(
        client, token, "Color", 60, Decimal("8000"), modo="optional", tipo="fixed",
        monto=3000, adicional=("Brillo", 700, 1),
    )  # fmt: skip
    assert diseno and aceite and brillo
    ana = await _profesional(
        client, token, "Ana", [corte, barba, color], f"ana-{slug}@t.com"
    )
    beto = await _profesional(client, token, "Beto", [corte], f"beto-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    for staff in (ana, beto):
        await add_staff_schedule(client, token, staff, target_date=dia)
    if flag:
        await _prender_flag(client, token)
    return _Tienda(
        slug, store, token, corte, barba, color, diseno, aceite, brillo, ana, beto, dia
    )


def _slot(t: _Tienda, hora: int) -> datetime:
    return t.dia.replace(hour=hora, minute=0, second=0, microsecond=0)


def _dia_local(t: _Tienda) -> date:
    return _slot(t, 13).astimezone(ARGENTINA_TZ).date()


async def _reservar(
    client: AsyncClient,
    t: _Tienda,
    extras: list[str],
    *,
    principal: str | None = None,
    hora: int = 13,
    staff: str | None = "ana",
    addons: list[dict[str, Any]] | None = None,
    clave: str | None = None,
    **extra: Any,
) -> Response:
    return await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": principal or t.corte,
            "staff_id": {"ana": t.ana, "beto": t.beto}.get(staff or "", None),
            "starts_at": _slot(t, hora).isoformat(),
            "client_name": "Cliente Varios",
            "client_phone": TELEFONO,
            "client_email": "cliente-varios@example.com",
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": clave or f"varios-{t.slug}-{hora}-{len(extras)}",
            "extra_service_ids": extras,
            "addons": addons or [],
            **extra,
        },
    )


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


async def _turnos(session: AsyncSession) -> list[Appointment]:
    session.expire_all()
    return list((await session.execute(select(Appointment))).scalars().all())


def _barba(t: _Tienda) -> list[dict[str, Any]]:
    return [{"public_id": t.barba, "name": "Barba", "duration_minutes": 20}]


# ---------------------------------------------------------------------------
# Flag de la tienda
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_flag_nace_apagado_y_la_vitrina_lo_expone(client: AsyncClient) -> None:
    t = await _tienda(client, "varios-flag", flag=False)
    vitrina = await client.get(f"/public/stores/{t.slug}")
    assert vitrina.status_code == 200, vitrina.text
    assert vitrina.json()["feature_flags"]["multi_service_booking"] is False

    await _prender_flag(client, t.token)

    vitrina = await client.get(f"/public/stores/{t.slug}")
    assert vitrina.json()["feature_flags"] == {
        "payments": False,
        "otp_booking": False,
        "multi_service_booking": True,
    }


@pytest.mark.asyncio
async def test_con_el_flag_apagado_los_extras_son_422_en_todos_lados(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-apagado", flag=False)
    extra = ("extra_service_id", t.barba)
    base = [("store_public_id", t.store), ("service_id", t.corte)]

    respuestas = [
        await _reservar(client, t, [t.barba]),
        await client.get(
            "/public/availability",
            params=[*base, ("date", _dia_local(t).isoformat()), extra],
        ),
        await client.get(
            "/appointments/availability",
            params=[
                ("service_id", t.corte),
                ("date", _dia_local(t).isoformat()),
                extra,
            ],
            headers=auth_headers(t.token),
        ),
        await client.get(
            "/appointments/availability",
            params=[
                ("service_id", t.corte),
                ("date", _dia_local(t).isoformat()),
                extra,
            ],
        ),
        await client.get(
            "/public/deposit/preview",
            params=[*base, ("starts_at", _slot(t, 13).isoformat()), extra],
        ),
        await client.get(
            "/public/promotions/preview", params=[*base, ("code", "NOEXISTE"), extra]
        ),
    ]

    for res in respuestas:
        assert res.status_code == 422, res.text
        assert res.json()["error_code"] == "MULTI_SERVICE_DISABLED"
    assert await _turnos(test_session) == []
    # Sin extras, la reserva de siempre.
    sola = await _reservar(client, t, [])
    assert sola.status_code == 201, sola.text
    assert sola.json()["extra_services"] == []
    assert sola.json()["services_label"] == "Corte"


# ---------------------------------------------------------------------------
# Alta, sena y previews
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corte_y_barba_suman_duracion_y_precio_y_cobran_la_regla_mas_alta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-alta")

    res = await _reservar(client, t, [t.barba])

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["service_id"] == t.corte
    assert cuerpo["extra_services"] == _barba(t)
    assert cuerpo["services_label"] == "Corte + Barba"
    assert cuerpo["deposit_channel"] == "whatsapp"
    assert Decimal(str(cuerpo["final_price"])) == TOTAL
    assert Decimal(str(cuerpo["payment_amount"])) == SENA
    inicio = datetime.fromisoformat(cuerpo["starts_at"])
    assert datetime.fromisoformat(cuerpo["ends_at"]) - inicio == DURACION
    turno = await _turno(test_session, cuerpo["public_id"])
    assert turno.duration_minutes == 50
    assert turno.price_amount == TOTAL
    assert turno.extra_services_amount == BARBA_PRECIO
    snapshot = turno.extra_services_snapshot
    assert isinstance(snapshot, list) and len(snapshot) == 1
    assert snapshot[0]["public_id"] == t.barba
    assert (snapshot[0]["name"], snapshot[0]["duration_minutes"]) == ("Barba", 20)
    assert snapshot[0]["price"] == "5000.00"
    cobro = await _cobro(test_session, turno.id)
    assert cobro.amount == SENA
    regla = cobro.deposit_rule or {}
    assert regla["price"] == "15000.00"
    assert regla["extra_services_amount"] == "5000.00"
    assert regla["rule_service_id"] == t.corte
    lineas = cast(list[dict[str, Any]], regla["lines"])
    assert [linea["public_id"] for linea in lineas] == [t.corte, t.barba]
    # El aviso al dueno nombra los dos servicios.
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
    assert [a.payload["service_name"] for a in avisos] == ["Corte + Barba"]


@pytest.mark.asyncio
async def test_la_regla_de_un_extra_cobra_aunque_el_principal_no_tenga_sena(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-extra-con-sena")

    res = await _reservar(client, t, [t.corte], principal=t.barba)

    assert res.status_code == 201, res.text
    assert res.json()["services_label"] == "Barba + Corte"
    assert res.json()["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert Decimal(str(res.json()["payment_amount"])) == SENA
    turno = await _turno(test_session, res.json()["public_id"])
    assert (await _cobro(test_session, turno.id)).amount == SENA


@pytest.mark.asyncio
async def test_los_previews_dicen_lo_mismo_que_cobra_el_alta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """15.000 + Diseno 1.000 + Aceite x2 1.000 = 17.000; 10 % de promo =
    15.300; la sena del 50 % (Corte) sobre el total con descuento = 7.650."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-previews")
    promo = await client.post(
        "/promotions/",
        headers=auth_headers(t.token),
        json={
            "title": "Promo",
            "code": "VERANO10",
            "promotion_type": "percent",
            "value": 10,
        },
    )
    assert promo.status_code == 201, promo.text
    addons = [
        {"addon_id": t.diseno, "quantity": 1},
        {"addon_id": t.aceite, "quantity": 2},
    ]
    comunes: list[tuple[str, Any]] = [
        ("store_public_id", t.store),
        ("service_id", t.corte),
        ("extra_service_id", t.barba),
        ("addon", f"{t.diseno}:1"),
        ("addon", f"{t.aceite}:2"),
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
    res = await _reservar(
        client, t, [t.barba], addons=addons, promotion_code="VERANO10"
    )

    assert vista_promo.status_code == 200, vista_promo.text
    assert Decimal(str(vista_promo.json()["base_amount"])) == Decimal("17000")
    assert Decimal(str(vista_promo.json()["final_amount"])) == Decimal("15300")
    assert vista_sena.status_code == 200, vista_sena.text
    assert Decimal(str(vista_sena.json()["price"])) == Decimal("15300")
    assert Decimal(str(vista_sena.json()["extra_services_amount"])) == BARBA_PRECIO
    assert Decimal(str(vista_sena.json()["addons_amount"])) == Decimal("2000")
    assert Decimal(str(vista_sena.json()["amount"])) == Decimal("7650")
    assert res.status_code == 201, res.text
    assert res.json()["final_price"] == vista_promo.json()["final_amount"]
    assert res.json()["final_price"] == vista_sena.json()["price"]
    assert res.json()["payment_amount"] == vista_sena.json()["amount"]
    turno = await _turno(test_session, res.json()["public_id"])
    assert turno.price_amount == Decimal("15300.00")
    assert turno.addons_amount == Decimal("2000.00")
    # Cada adicional dice de que servicio es.
    servicios_de = {
        linea["addon_id"]: linea["service_id"] for linea in turno.addons_snapshot or []
    }
    assert set(servicios_de) == {t.diseno, t.aceite}
    assert servicios_de[t.diseno] != servicios_de[t.aceite]
    cobro = await _cobro(test_session, turno.id)
    assert cobro.amount == Decimal("7650.00")
    # Antes de la promo: 50 % de 17.000.
    assert cobro.original_amount == Decimal("8500.00")


@pytest.mark.asyncio
async def test_mas_de_tres_servicios_es_422_y_la_entrada_tiene_tope_duro(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-tope")
    cuarto, _ = await _servicio(client, t.token, "Lavado", 10, Decimal("1000"))
    extras = [t.barba, t.color, cuarto]

    alta = await _reservar(client, t, extras)
    grilla = await client.get(
        "/public/availability",
        params=[
            ("store_public_id", t.store),
            ("service_id", t.corte),
            ("date", _dia_local(t).isoformat()),
            *(("extra_service_id", e) for e in extras),
        ],
    )

    for res in (alta, grilla):
        assert res.status_code == 422, res.text
        assert res.json()["error_code"] == "TOO_MANY_SERVICES"
    # Mas alla del tope duro de la entrada ni se mira la tienda.
    absurdo = await _reservar(client, t, [f"id-{i}" for i in range(10)])
    assert absurdo.status_code == 422, absurdo.text
    assert absurdo.json()["error_code"] == "VALIDATION_ERROR"
    assert await _turnos(test_session) == []


@pytest.mark.asyncio
async def test_mas_de_480_minutos_es_422(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-largo")
    largo, _ = await _servicio(client, t.token, "Alisado", 460, Decimal("1000"))

    alta = await _reservar(client, t, [largo])
    grilla = await client.get(
        "/public/availability",
        params=[
            ("store_public_id", t.store),
            ("service_id", t.corte),
            ("date", _dia_local(t).isoformat()),
            ("extra_service_id", largo),
        ],
    )

    for res in (alta, grilla):
        assert res.status_code == 422, res.text
        assert res.json()["error_code"] == "SERVICES_TOO_LONG"
    assert await _turnos(test_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caso", ["repetido", "el-principal", "inactivo", "otra-tienda"]
)
async def test_un_extra_invalido_es_el_404_neutro_sin_escribir_nada(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, f"varios-404-{caso}")
    if caso == "repetido":
        extras = [t.barba, t.barba]
    elif caso == "el-principal":
        extras = [t.corte]
    elif caso == "inactivo":
        baja = await client.delete(
            f"/services/{t.barba}", headers=auth_headers(t.token)
        )
        assert baja.status_code in (200, 204), baja.text
        extras = [t.barba]
    else:
        otra = await _tienda(client, "varios-404-ajena")
        extras = [otra.barba]

    res = await _reservar(client, t, extras)

    assert res.status_code == 404, res.text
    assert res.json()["error_code"] == "SERVICE_NOT_FOUND"
    assert await _turnos(test_session) == []


@pytest.mark.asyncio
async def test_un_adicional_de_un_servicio_no_elegido_es_422(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-addon-ajeno")

    res = await _reservar(
        client, t, [t.barba], addons=[{"addon_id": t.brillo, "quantity": 1}]
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "ADDON_UNAVAILABLE"
    assert await _turnos(test_session) == []


@pytest.mark.asyncio
async def test_la_misma_reserva_dos_veces_es_un_solo_turno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-idempotente")

    primera = await _reservar(client, t, [t.barba], clave="varios-idem-000001")
    segunda = await _reservar(client, t, [t.barba], clave="varios-idem-000001")

    assert primera.status_code == 201, primera.text
    assert segunda.status_code == 201, segunda.text
    assert segunda.json()["public_id"] == primera.json()["public_id"]
    assert len(await _turnos(test_session)) == 1


# ---------------------------------------------------------------------------
# Disponibilidad y profesionales
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_grilla_dura_la_suma_y_solo_ofrece_a_quien_hace_todos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-grilla")
    base: list[tuple[str, Any]] = [
        ("store_public_id", t.store),
        ("service_id", t.corte),
        ("date", _dia_local(t).isoformat()),
    ]

    solo = await client.get("/public/availability", params=base)
    varios = await client.get(
        "/public/availability", params=[*base, ("extra_service_id", t.barba)]
    )
    otra_vez = await client.get(
        "/public/availability", params=[*base, ("extra_service_id", t.barba)]
    )
    panel = await client.get(
        "/appointments/availability",
        params=[*base[1:], ("extra_service_id", t.barba)],
        headers=auth_headers(t.token),
    )

    assert solo.status_code == varios.status_code == panel.status_code == 200
    assert {s["staff_id"] for s in solo.json()} == {t.ana, t.beto}
    assert {s["staff_id"] for s in varios.json()} == {t.ana}
    assert varios.json()
    for slot in varios.json():
        inicio = datetime.fromisoformat(slot["starts_at"])
        assert datetime.fromisoformat(slot["ends_at"]) - inicio == DURACION
    # Cache con su propia clave: la segunda lectura es la misma grilla.
    assert otra_vez.json() == varios.json()
    assert [s["starts_at"] for s in panel.json()] == [
        s["starts_at"] for s in varios.json()
    ]
    # Beto no hace Barba: elegirlo es 409; "cualquiera" toma a Ana.
    con_beto = await _reservar(client, t, [t.barba], staff="beto")
    assert con_beto.status_code == 409, con_beto.text
    cualquiera = await _reservar(client, t, [t.barba], staff=None)
    assert cualquiera.status_code == 201, cualquiera.text
    assert cualquiera.json()["staff_id"] == t.ana


@pytest.mark.asyncio
async def test_el_turno_largo_ocupa_todo_su_rango(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un turno de 13:00 a 13:50: un Corte de Ana a las 13:30 choca."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-rango")
    largo = await _reservar(client, t, [t.barba])
    assert largo.status_code == 201, largo.text

    choca = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.corte,
            "staff_id": t.ana,
            "starts_at": (_slot(t, 13) + timedelta(minutes=30)).isoformat(),
            "client_name": "Otro",
            "client_phone": "+5491155577999",
            "client_email": "otro@example.com",
            "accepts_terms": True,
            "idempotency_key": "varios-rango-choca-01",
        },
    )

    assert choca.status_code == 409, choca.text


# ---------------------------------------------------------------------------
# Reprogramar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_cliente_reprograma_y_conserva_duracion_y_lineas(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-reprograma-cliente")
    reserva = await _reservar(
        client, t, [t.barba], addons=[{"addon_id": t.aceite, "quantity": 1}]
    )
    assert reserva.status_code == 201, reserva.text
    original = await _turno(test_session, reserva.json()["public_id"])
    lineas = original.extra_services_snapshot
    adicionales = original.addons_snapshot
    await _verificar_cliente(client, monkeypatch, t)  # type: ignore[arg-type]

    res = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": _slot(t, 16).isoformat(),
            "idempotency_key": "varios-reprograma-cliente-01",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["extra_services"] == _barba(t)
    assert res.json()["services_label"] == "Corte + Barba"
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.ends_at - nuevo.starts_at == DURACION
    assert nuevo.duration_minutes == 50
    assert nuevo.extra_services_snapshot == lineas
    assert nuevo.extra_services_amount == BARBA_PRECIO
    assert nuevo.addons_snapshot == adicionales
    assert nuevo.price_amount == Decimal("15500.00")
    # "Mis turnos" muestra los dos servicios.
    mis = await client.get(f"/public/client/{t.store}/{TELEFONO}/appointments")
    assert mis.status_code == 200, mis.text
    (item,) = [a for a in mis.json()["appointments"] if a["public_id"] == nuevo.id]
    assert item["extra_services"] == _barba(t)
    assert item["services_label"] == "Corte + Barba"


@pytest.mark.asyncio
async def test_el_panel_reprograma_y_conserva_duracion_y_lineas(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-reprograma-panel", corte_modo="none")
    reserva = await _reservar(client, t, [t.barba])
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["payment_required"] is False
    original = await _turno(test_session, reserva.json()["public_id"])
    lineas = original.extra_services_snapshot

    res = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": _slot(t, 16).isoformat(),
            "idempotency_key": "varios-reprograma-panel-01",
        },
    )

    assert res.status_code == 200, res.text
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.ends_at - nuevo.starts_at == DURACION
    assert nuevo.duration_minutes == 50
    assert nuevo.extra_services_snapshot == lineas
    assert (nuevo.price_amount, nuevo.extra_services_amount) == (TOTAL, BARBA_PRECIO)


# ---------------------------------------------------------------------------
# Link del panel
# ---------------------------------------------------------------------------


def _mercadopago(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    preferencias: list[dict[str, Any]] = []

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            preferencias.append(json_body or {})
            return {
                "id": "pref-varios",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=v",
            }
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)
    return preferencias


@pytest.mark.asyncio
async def test_el_link_del_panel_cobra_la_lista_de_hoy_de_cada_linea(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corte con sena OPCIONAL de 50 %: el alta no cobra; el link del panel
    cobra la regla mas alta sobre la lista de hoy de cada linea (y el titulo de
    MP dice "Corte + Barba")."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    preferencias = _mercadopago(monkeypatch)
    t = await _tienda(client, "varios-link", corte_modo="optional", mercadopago=True)
    reserva = await _reservar(client, t, [t.barba])
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["payment_required"] is False
    turno = reserva.json()["public_id"]

    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.token)
    )

    assert link.status_code == 200, link.text
    assert (await _cobro(test_session, turno)).amount == SENA
    assert preferencias[-1]["items"][0]["title"] == "Corte + Barba"
    # La Barba sube a 7.000: el link re-tarifa la lista de hoy (50 % de 17.000).
    subio = await client.patch(
        f"/services/{t.barba}", headers=auth_headers(t.token), json={"price": 7000}
    )
    assert subio.status_code == 200, subio.text
    otra = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.token)
    )
    assert otra.status_code == 200, otra.text
    assert (await _cobro(test_session, turno)).amount == Decimal("8500.00")


# ---------------------------------------------------------------------------
# Agenda, busqueda, reportes y mails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agenda_busqueda_y_reportes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "varios-agenda", corte_modo="none")
    reserva = await _reservar(client, t, [t.barba])
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]
    dia = _dia_local(t).isoformat()

    agenda = await client.get(
        f"/appointments/?date={dia}", headers=auth_headers(t.token)
    )
    busqueda = await client.get("/appointments/search", headers=auth_headers(t.token))
    reportes = await client.get(
        "/reports/summary",
        params={"from_date": dia, "to_date": dia},
        headers=auth_headers(t.token),
    )

    assert agenda.status_code == 200, agenda.text
    (item,) = [a for a in agenda.json() if a["public_id"] == turno]
    assert item["extra_services"] == _barba(t)
    assert item["services_label"] == "Corte + Barba"
    assert busqueda.status_code == 200, busqueda.text
    (fila,) = [r for r in busqueda.json()["results"] if r["public_id"] == turno]
    assert fila["extra_services"] == _barba(t)
    assert fila["services_label"] == "Corte + Barba"
    # El top de servicios cuenta el principal (decision de Mateo, 2026-10-16).
    assert reportes.status_code == 200, reportes.text
    top = {s["service_id"]: s["appointments"] for s in reportes.json()["top_services"]}
    assert top == {t.corte: 1}


@pytest.mark.asyncio
async def test_el_mail_de_reserva_dice_corte_mas_barba(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda(client, "varios-mail")

    res = await _reservar(client, t, [t.barba])
    assert res.status_code == 201, res.text
    await cola.entregar()

    assert len(buzon.enviados) == 1
    (_para, _asunto, cuerpo) = buzon.enviados[0]
    assert "Corte + Barba" in cuerpo
