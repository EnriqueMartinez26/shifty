"""El cliente recibe mail al reservar y al ser confirmado (2026-09-10).

Antes el mail del flujo publico estaba detras de ``status == CONFIRMED`` y el
turno nace pendiente: nunca salia nada. ``confirm()`` tampoco mandaba. Solo
llegaba el recordatorio de 24 horas. Ademas la hora salia en ISO UTC.

F2-01 (plan de rendimiento, R1-04, 2026-09-24): el 201 de ``POST
/public/appointments`` esperaba al SMTP (conexion + STARTTLS + LOGIN, hasta
10 s por operacion). Ahora el request solo ENCOLA la tarea
``send_booking_email`` (cola ``interactive``) con el tipo de mail, la tienda y
el id del turno; el worker relee el turno y manda. En el broker no viaja el
email ni el nombre del cliente (PV-19).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.utils import ARGENTINA_TZ
from modules.appointments.model import Appointment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


class Buzon:
    def __init__(self, *, falla: bool = False) -> None:
        self.enviados: list[tuple[str, str, str]] = []
        self.falla = falla

    async def __call__(
        self, to: str, subject: str, body: str, smtp: Any = None
    ) -> bool:
        if self.falla:
            return False
        self.enviados.append((to, subject, body))
        return True


class ColaDeReservas:
    """Reemplaza la tarea ``send_booking_email``: guarda lo encolado.

    ``entregar`` corre el cuerpo de la tarea (lo que hace el worker) sobre lo
    encolado, con la sesion del test. Se prueba la corrutina y no el wrapper de
    Celery porque ``run_in_worker_loop`` se niega a anidarse en un loop activo.
    """

    def __init__(self) -> None:
        self.encolados: list[tuple[Any, ...]] = []

    def delay(self, *args: Any) -> None:
        self.encolados.append(args)

    async def entregar(self) -> list[dict[str, str]]:
        resultados = [await tasks.deliver_booking_email(*a) for a in self.encolados]
        self.encolados.clear()
        return resultados


def usar_cola_de_reservas(
    monkeypatch: pytest.MonkeyPatch, test_session: AsyncSession
) -> ColaDeReservas:
    """Cola falsa + el worker leyendo con la sesion del test."""
    cola = ColaDeReservas()
    monkeypatch.setattr(tasks, "send_booking_email", cola)

    @asynccontextmanager
    async def sesion_de_prueba() -> AsyncIterator[AsyncSession]:
        yield test_session

    monkeypatch.setattr(tasks, "AsyncSessionFactory", sesion_de_prueba)
    return cola


async def _tienda_reservable(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    return store, token, service, staff, slot


def _reserva(
    store: str, service: str, staff: str, slot: datetime, **extra: str
) -> dict[str, Any]:
    cuerpo = {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Carla Ruiz",
        "client_phone": "+5491155550031",
        "accepts_terms": True,
        "idempotency_key": "mail-cliente-000001",
    }
    cuerpo.update(extra)
    return cuerpo


@pytest.mark.asyncio
async def test_reservar_y_confirmar_mandan_mail_en_hora_argentina(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, token, service, staff, slot = await _tienda_reservable(client, "mail-ok")

    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text

    # El request encola y no manda: el SMTP no corre en el proceso de la API.
    assert buzon.enviados == []
    public_id = reserva.json()["public_id"]
    [encolado] = cola.encolados
    assert encolado[0] == "registration"
    assert encolado[2] == public_id
    # PV-19: por el broker viajan ids, no datos personales.
    assert "carla" not in repr(encolado).lower()

    assert await cola.entregar() == [{"status": "sent"}]
    assert len(buzon.enviados) == 1
    destino, asunto, cuerpo = buzon.enviados[0]
    assert destino == "carla@example.com"
    assert asunto.startswith("Reserva registrada")
    assert "Hola Carla Ruiz" in cuerpo
    local = slot.astimezone(ARGENTINA_TZ)
    assert local.strftime("%d/%m/%Y") in cuerpo and "10:00 hs" in cuerpo
    assert "T13:00" not in cuerpo, "la hora no puede salir en ISO UTC"
    assert "desde la app" not in cuerpo
    assert "/b/mail-ok" in cuerpo

    confirmar = await client.patch(
        f"/appointments/{public_id}/confirm",
        headers=auth_headers(token),
    )
    assert confirmar.status_code == 200, confirmar.text
    assert len(buzon.enviados) == 2
    _, asunto2, cuerpo2 = buzon.enviados[1]
    assert asunto2.startswith("Turno confirmado")
    assert "10:00 hs" in cuerpo2


@pytest.mark.asyncio
async def test_sin_email_real_no_se_encola_ni_se_manda_nada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, token, service, staff, slot = await _tienda_reservable(client, "mail-sin")

    # Sin email: el alta inventa uno tecnico .noreply que no debe recibir nada.
    reserva = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )
    assert reserva.status_code == 201, reserva.text
    assert cola.encolados == [], "is_deliverable_email filtra antes de encolar"
    await client.patch(
        f"/appointments/{reserva.json()['public_id']}/confirm",
        headers=auth_headers(token),
    )
    assert buzon.enviados == []


@pytest.mark.asyncio
async def test_un_smtp_caido_no_impide_reservar_ni_confirmar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon(falla=True))
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, token, service, staff, slot = await _tienda_reservable(client, "mail-caido")

    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text
    # El worker lo intenta y registra el fallo; no se reintenta (max_retries=0).
    [resultado] = await cola.entregar()
    assert resultado["status"] == "failed"
    confirmar = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/confirm",
        headers=auth_headers(token),
    )
    assert confirmar.status_code == 200, confirmar.text
    assert confirmar.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_un_broker_caido_no_impide_reservar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallo de encolado = mail no enviado: se loguea, la reserva sigue."""

    class ColaCaida:
        def delay(self, *_args: object) -> None:
            raise RuntimeError("broker caido")

    monkeypatch.setattr(tasks, "send_booking_email", ColaCaida())
    store, _token, service, staff, slot = await _tienda_reservable(
        client, "mail-broker-caido"
    )

    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )

    assert reserva.status_code == 201, reserva.text


@pytest.mark.asyncio
async def test_la_reserva_publica_no_espera_al_smtp(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2-01: un SMTP que tarda 3 s por mail no demora el 201.

    Con la tarea real (broker ``memory://`` en los tests): si el request
    volviera a mandar en linea, la respuesta tardaria los 3 s del stub.
    """

    async def smtp_lento(to: str, subject: str, body: str, smtp: Any = None) -> bool:
        await asyncio.sleep(3)
        return True

    monkeypatch.setattr(tasks, "_send_email", smtp_lento)
    store, _token, service, staff, slot = await _tienda_reservable(client, "mail-lento")

    inicio = time.perf_counter()
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    demora = time.perf_counter() - inicio

    assert reserva.status_code == 201, reserva.text
    assert demora < 1.0, f"la reserva espero al SMTP: {demora:.2f} s"


@pytest.mark.asyncio
async def test_el_worker_no_manda_la_confirmacion_de_un_turno_que_ya_no_esta_confirmado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El worker relee el turno: entre el encolado y el envio pudo cambiar."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    usar_cola_de_reservas(monkeypatch, test_session)
    store, _token, service, staff, slot = await _tienda_reservable(
        client, "mail-releido"
    )
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text
    public_id = reserva.json()["public_id"]
    turno = await test_session.get(Appointment, public_id)
    assert turno is not None and turno.status == "pending"
    store_id = turno.store_id

    resultado = await tasks.deliver_booking_email("confirmation", store_id, public_id)
    assert resultado == {"status": "skipped", "reason": "status"}
    ajeno = await tasks.deliver_booking_email("registration", "otra-tienda", public_id)
    assert ajeno == {"status": "skipped", "reason": "not-found"}
    assert buzon.enviados == []
