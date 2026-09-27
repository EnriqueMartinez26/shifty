"""Caracterizacion de ``POST /public/appointments`` antes de partirlo (B1-12).

Audit B1-12 (2026-09-19), regla 29 de CLAUDE.md: ``create_public_booking``
tenia 371 lineas y commiteaba en el router. Antes de moverlo a un service
propio (patron de ``appointments``) estos tests fijan el camino completo tal
como es HOY: codigos y cuerpos, filas creadas, eventos del outbox,
invalidaciones del cache, mails, idempotencia (reserva, liberacion y replay)
y el orden commit -> llamada externa -> compensacion. Tienen que pasar sobre
la base y seguir pasando despues del refactor sin cambiar una asercion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.circuit_breaker import CircuitBreakerOpenError
from core.redis import get_redis
from core.utils import ensure_utc_aware
from main import app
from modules.appointments.model import Appointment
from modules.payments.model import OutboxMessage, Payment
from modules.public_api.router import _booking_cache_key
from modules.public_api.schemas import PublicBookingCreate
from modules.users.model import User
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon, usar_cola_de_reservas


class _Tienda:
    def __init__(
        self, store: str, token: str, service: str, staff: str, slot: datetime
    ) -> None:
        self.store = store
        self.token = token
        self.service = service
        self.staff = staff
        self.slot = slot


async def _tienda(client: AsyncClient, slug: str, *, pagos: bool = False) -> _Tienda:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    if pagos:
        flags = await client.put(
            "/stores/me/feature-flags",
            headers=auth_headers(token),
            json={"payments": True},
        )
        assert flags.status_code == 200, flags.text
        gateway = await client.put(
            "/payments/gateway-config",
            headers=auth_headers(token),
            json={"access_token": "TEST-CARACTERIZACION-TOKEN"},
        )
        assert gateway.status_code == 200, gateway.text
        service = await create_service(
            client,
            token,
            deposit_mode="required",
            deposit_type="fixed",
            deposit_amount=2500,
        )
    else:
        service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    return _Tienda(store, token, service, staff, slot)


def _reserva(t: _Tienda, clave: str, **extra: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "store_public_id": t.store,
        "service_id": t.service,
        "staff_id": t.staff,
        "starts_at": t.slot.isoformat(),
        "client_name": "Cliente Caracterizado",
        "client_phone": "+5491155558001",
        "accepts_terms": True,
        "client_email": "caracterizado@example.com",
        "notes": "Primera vez",
        "idempotency_key": clave,
    }
    cuerpo.update(extra)
    return cuerpo


async def _redis() -> Any:
    return await app.dependency_overrides[get_redis]()


def _clave_redis(cuerpo: dict[str, Any]) -> str:
    """La clave real que el alta usa en Redis, namespaceada (AUD2-B1-06).

    Antes era la cadena cruda del cliente; afirmar sobre
    ``idempotency:{clave}`` ahora daria siempre ``None`` y la asercion de
    liberacion no probaria nada.
    """
    data = PublicBookingCreate(**cuerpo)
    return "idempotency:" + _booking_cache_key(data, cuerpo["idempotency_key"])


async def _contar(session: AsyncSession, modelo: Any) -> int:
    session.expire_all()
    return int(await session.scalar(select(func.count()).select_from(modelo)) or 0)


async def _eventos(session: AsyncSession) -> list[tuple[str, dict[str, Any]]]:
    session.expire_all()
    filas = await session.execute(
        select(OutboxMessage).order_by(OutboxMessage.created_at.asc())
    )
    return [(m.event_type, dict(m.payload or {})) for m in filas.scalars()]


def _espiar_orden(
    session: AsyncSession, redis: Any, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Registra commits, invalidaciones de cache y llamadas a MP, en orden."""
    orden: list[str] = []
    commit_original = session.commit
    incr_original = redis.incr

    async def commit() -> None:
        orden.append("commit")
        await commit_original()

    async def incr(key: str) -> int:
        if key.startswith("availability:v:") and (not orden or orden[-1] != "cache"):
            orden.append("cache")
        return int(await incr_original(key))

    monkeypatch.setattr(session, "commit", commit)
    monkeypatch.setattr(redis, "incr", incr)
    return orden


class _MercadoPago:
    def __init__(self, orden: list[str] | None = None) -> None:
        self.orden = orden
        self.falla: Exception | None = None

    async def __call__(
        self,
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        if self.orden is not None:
            self.orden.append(f"mp:{method}")
        if self.falla is not None:
            raise self.falla
        return {
            "id": "pref-caracterizacion",
            "sandbox_init_point": "https://sandbox.mercadopago.com/x?pref=carac",
        }


def _sin_ids(cuerpo: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in cuerpo.items()
        if k not in {"public_id", "starts_at", "ends_at", "payment_public_id"}
    }


@pytest.mark.asyncio
async def test_reserva_manual_cuerpo_filas_outbox_cache_mail_y_replay(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda(client, "carac-manual")
    redis = await _redis()
    orden = _espiar_orden(test_session, redis, monkeypatch)

    res = await client.post(
        "/public/appointments",
        json=_reserva(t, "carac-manual-0001", accepts_terms=True),
    )

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert _sin_ids(cuerpo) == {
        "service_id": t.service,
        "service_name": "Consulta",
        "staff_id": t.staff,
        "staff_name": "Pro Demo",
        "status": "pending",
        "client_name": "Cliente Caracterizado",
        "client_phone": "5491155558001",
        "notes": "Primera vez",
        "custom_fields": {},
        "payment_required": False,
        "payment_status": None,
        "payment_link": None,
        "payment_amount": 0.0,
        "promotion_code": None,
        "service_price": 10000.0,
        "discount_amount": 0.0,
        "final_price": 10000.0,
    }
    assert ensure_utc_aware(datetime.fromisoformat(cuerpo["starts_at"])) == t.slot
    assert ensure_utc_aware(
        datetime.fromisoformat(cuerpo["ends_at"])
    ) == t.slot + timedelta(minutes=30)
    # Un commit (el del alta) y despues la invalidacion; nada de MP.
    assert orden == ["commit", "cache"], orden

    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == cuerpo["public_id"])
        )
    ).scalar_one()
    tienda_del_turno = turno.store_id
    assert turno.status == "pending"
    assert ensure_utc_aware(turno.expires_at) == t.slot  # type: ignore[arg-type]
    assert turno.price_amount == Decimal("10000.00")
    assert turno.idempotency_key == "carac-manual-0001"
    assert turno.client_email == "caracterizado@example.com"
    assert turno.terms_accepted_at is not None
    assert await _eventos(test_session) == [
        (
            "appointment.pending_confirmation",
            {
                "appointment_id": cuerpo["public_id"],
                "client_name": "Cliente Caracterizado",
                "service_name": "Consulta",
            },
        )
    ]
    # F2-01: el request encola (ids, sin datos personales) y manda el worker.
    assert buzon.enviados == []
    assert cola.encolados == [("registration", tienda_del_turno, cuerpo["public_id"])]
    await cola.entregar()
    assert [m[0] for m in buzon.enviados] == ["caracterizado@example.com"]

    # Replay con la misma clave: mismo cuerpo, ninguna fila ni mail nuevo.
    replay = await client.post(
        "/public/appointments",
        json=_reserva(t, "carac-manual-0001", accepts_terms=True),
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == cuerpo
    assert await _contar(test_session, Appointment) == 1
    assert cola.encolados == []
    assert len(buzon.enviados) == 1


@pytest.mark.asyncio
async def test_reserva_con_mp_commit_antes_del_link(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "carac-mp", pagos=True)
    redis = await _redis()
    orden = _espiar_orden(test_session, redis, monkeypatch)
    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", _MercadoPago(orden)
    )

    res = await client.post(
        "/public/appointments",
        json=_reserva(t, "carac-mp-0001", payment_method="mercadopago"),
    )

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert _sin_ids(cuerpo) == {
        "service_id": t.service,
        "service_name": "Consulta",
        "staff_id": t.staff,
        "staff_name": "Pro Demo",
        "status": "pending_payment",
        "client_name": "Cliente Caracterizado",
        "client_phone": "5491155558001",
        "notes": "Primera vez",
        "custom_fields": {},
        "payment_required": True,
        "payment_status": "pending",
        "payment_link": "https://sandbox.mercadopago.com/x?pref=carac",
        "payment_amount": 2500.0,
        "promotion_code": None,
        "service_price": 10000.0,
        "discount_amount": 0.0,
        "final_price": 10000.0,
    }
    # Regla 5: el alta commitea e invalida; recien despues MP y su commit.
    assert orden == ["commit", "cache", "mp:POST", "commit"], orden
    pago = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == cuerpo["public_id"])
        )
    ).scalar_one()
    assert pago.id == cuerpo["payment_public_id"]
    assert pago.amount == Decimal("2500.00")
    assert pago.preference_id == "pref-caracterizacion"
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == cuerpo["public_id"])
        )
    ).scalar_one()
    hold = ensure_utc_aware(turno.expires_at)  # type: ignore[arg-type]
    assert datetime.now(timezone.utc) < hold < t.slot
    # B2-17 (2026-09-19): payment.preference.created dejo de publicarse (no
    # tenia consumidor); el alta con cobro no deja eventos en el outbox.
    assert [e[0] for e in await _eventos(test_session)] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("falla", "codigo", "error_code"),
    [
        (RuntimeError("timeout upstream"), 502, "PAYMENT_LINK_CREATION_FAILED"),
        (
            CircuitBreakerOpenError("abierto", retry_after_seconds=30),
            503,
            "PAYMENT_PROVIDER_UNAVAILABLE",
        ),
    ],
)
async def test_mp_falla_despues_del_commit_y_se_compensa(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    falla: Exception,
    codigo: int,
    error_code: str,
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    t = await _tienda(client, f"carac-falla-{codigo}", pagos=True)
    redis = await _redis()
    orden = _espiar_orden(test_session, redis, monkeypatch)
    mp = _MercadoPago(orden)
    mp.falla = falla
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)

    cuerpo = _reserva(t, f"carac-falla-{codigo}-0001", payment_method="mercadopago")
    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == codigo, res.text
    assert res.json()["error_code"] == error_code
    # Commit del alta -> cache -> MP -> commit de la compensacion -> cache.
    assert orden == ["commit", "cache", "mp:POST", "commit", "cache"], orden
    assert await _contar(test_session, Appointment) == 0
    assert await _contar(test_session, Payment) == 0
    # B2-17 (2026-09-19): payment.preference.created dejo de publicarse, asi
    # que la compensacion no deja ningun evento huerfano en el outbox.
    assert [e[0] for e in await _eventos(test_session)] == []
    assert await redis.get(_clave_redis(cuerpo)) is None
    assert buzon.enviados == []


@pytest.mark.asyncio
async def test_slot_ocupado_409_libera_la_clave_y_no_escribe(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda(client, "carac-choque")
    primera = await client.post("/public/appointments", json=_reserva(t, "carac-ch-1"))
    assert primera.status_code == 201, primera.text
    redis = await _redis()

    cuerpo = _reserva(
        t,
        "carac-ch-2",
        client_phone="+5491155558002",
        client_email="otro-carac@example.com",
    )
    segunda = await client.post("/public/appointments", json=cuerpo)

    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["error_code"] == "APPOINTMENT_CONFLICT"
    assert segunda.json()["message"] == (
        "El horario ya esta ocupado. Por favor elegi otro."
    )
    assert await redis.get(_clave_redis(cuerpo)) is None
    assert await _contar(test_session, Appointment) == 1
    # El cliente nuevo tampoco quedo: el savepoint se deshizo entero.
    telefonos = (
        (await test_session.execute(select(User.phone).where(User.role == "client")))
        .scalars()
        .all()
    )
    assert "5491155558002" not in telefonos
    # Solo la primera reserva encolo su mail.
    assert len(cola.encolados) == 1


async def _suspender(session: AsyncSession, store_public_id: str) -> None:
    from tests.integration.test_suspension_por_endpoint import _suspender as s

    await s(session, store_public_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caso",
    ["suspendida", "otp", "antelacion", "promo", "campo", "servicio", "tienda"],
)
async def test_rechazos_previos_a_toda_escritura(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, f"carac-rechazo-{caso}")
    extra: dict[str, Any] = {}
    esperado: tuple[int, str]
    if caso == "suspendida":
        await _suspender(test_session, t.store)
        esperado = (404, "STORE_NOT_FOUND")
    elif caso == "otp":
        flags = await client.put(
            "/stores/me/feature-flags",
            headers=auth_headers(t.token),
            json={"otp_booking": True},
        )
        assert flags.status_code == 200, flags.text
        esperado = (403, "OTP_VERIFICATION_REQUIRED")
    elif caso == "antelacion":
        extra["starts_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat()
        esperado = (400, "BOOKING_NOTICE_REQUIRED")
    elif caso == "promo":
        extra["promotion_code"] = "NOEXISTE"
        esperado = (422, "VALIDATION_ERROR")
    elif caso == "campo":
        extra["custom_fields"] = {"inventado": "x"}
        esperado = (422, "VALIDATION_ERROR")
    elif caso == "servicio":
        extra["service_id"] = "01J00000000000000000000000"
        esperado = (404, "SERVICE_NOT_FOUND")
    else:
        extra["store_public_id"] = "01J00000000000000000000000"
        esperado = (404, "STORE_NOT_FOUND")
    clientes_antes = await _contar(test_session, User)
    redis = await _redis()

    cuerpo = _reserva(t, f"carac-rz-{caso}", **extra)
    res = await client.post("/public/appointments", json=cuerpo)

    assert (res.status_code, res.json()["error_code"]) == esperado, res.text
    assert await _contar(test_session, Appointment) == 0
    assert await _contar(test_session, User) == clientes_antes
    assert await _eventos(test_session) == []
    assert await redis.get(_clave_redis(cuerpo)) is None


@pytest.mark.asyncio
async def test_la_reserva_cierra_la_entrada_de_la_lista_de_espera(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "carac-espera")
    alta = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "window_starts_at": (t.slot - timedelta(hours=2)).isoformat(),
            "window_ends_at": (t.slot + timedelta(hours=2)).isoformat(),
            "client_name": "Cliente Caracterizado",
            "client_phone": "+5491155558001",
        },
    )
    assert alta.status_code == 201, alta.text

    res = await client.post("/public/appointments", json=_reserva(t, "carac-esp-1"))

    assert res.status_code == 201, res.text
    test_session.expire_all()
    entrada = (
        await test_session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == alta.json()["public_id"])
        )
    ).scalar_one()
    assert entrada.status == "booked"


# ---------------------------------------------------------------------------
# F3-03 (plan de rendimiento, R1-05, 2026-09-24): cuanto le cuesta a la base
# ---------------------------------------------------------------------------

TELEFONO_CONOCIDO = "+5491155558001"


async def _cliente_conocido_verificado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, t: _Tienda
) -> None:
    """Cliente con ficha y email, OTP verificado y la tienda exigiendo OTP.

    Es el camino mas caro del alta: el gate de OTP, el contacto verificado y
    el historial del cliente para la regla de sena.
    """
    from core.config import settings

    primera = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            "carac-sql-0001",
            payment_method="mercadopago",
            starts_at=(t.slot + timedelta(hours=2)).isoformat(),
        ),
    )
    assert primera.status_code == 201, primera.text
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(t.token),
        json={"payments": True, "otp_booking": True},
    )
    assert flags.status_code == 200, flags.text
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": t.store,
            "phone": TELEFONO_CONOCIDO,
            "channel": "whatsapp",
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": t.store,
            "phone": TELEFONO_CONOCIDO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text


@pytest.mark.asyncio
async def test_sentencias_del_alta_con_otp_historial_y_cobro(
    client: AsyncClient,
    test_engine: Any,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antes 33 sentencias con repetidas: el servicio dos veces, el predicado
    de OTP (ficha + verificacion) resuelto de nuevo en cada llamada (la ficha
    tres veces), los profesionales con sus horarios y servicios en cascada y
    los horarios releidos al elegirlo, y un UPDATE del turno recien insertado
    para la retencion y el consentimiento."""
    from sqlalchemy import event

    monkeypatch.setattr(tasks, "_send_email", Buzon())
    usar_cola_de_reservas(monkeypatch, test_session)
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", _MercadoPago())
    t = await _tienda(client, "carac-sql", pagos=True)
    await _cliente_conocido_verificado(client, monkeypatch, t)
    test_session.expunge_all()

    sentencias: list[str] = []

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.split()).lower())

    event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
    try:
        res = await client.post(
            "/public/appointments",
            json=_reserva(t, "carac-sql-0002", payment_method="mercadopago"),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)

    assert res.status_code == 201, res.text
    assert res.json()["payment_link"] == (
        "https://sandbox.mercadopago.com/x?pref=carac"
    )
    ficha_otp = [s for s in sentencias if s.startswith("select users.email from users")]
    assert len(ficha_otp) == 1, "la ficha del telefono se busca una sola vez"
    servicios = [s for s in sentencias if s.startswith("select services.")]
    assert len(servicios) == 1, "el servicio se resuelve una sola vez"
    horarios = [s for s in sentencias if "from schedules" in s]
    assert len(horarios) <= 1, "los horarios del profesional se leen una vez"
    assert not [s for s in sentencias if "staff_1" in s], "profesionales sin cascada"
    assert not [s for s in sentencias if s.startswith("update appointments")], (
        "retencion y consentimiento van en el INSERT del turno"
    )
    # 33 -> 26 en SQLite (sin los set_config de Postgres). Quedan fuera de
    # este carril: las dos cargas en cascada de store_schedules (F3-01 las
    # saca con lazy="raise": 24) y las lecturas de payments/service (el
    # Payment releido tras el commit, la tienda y la configuracion de MP).
    assert len(sentencias) <= 26, "\n".join(sentencias)
