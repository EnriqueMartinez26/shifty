"""La reprogramacion del cliente decide la agenda con la misma funcion que el alta.

Audit B1-19 (2026-09-18). ``client_reschedule_appointment`` validaba horario,
bloqueo y choque con dos metodos privados del repositorio mas un lock y una
consulta de choque escritos a mano en el router: una segunda copia de "este
profesional puede tomar este rango" que ya habia divergido de la del alta
(B1-05 orden del lock, B1-07 buffer). Ahora las dos usan
``PublicRepository.staff_can_take_range``.

Guarda de la regla 4: el ``FOR UPDATE`` del profesional y la relectura de
bloqueo y choque ocurren DENTRO de esa funcion del repositorio (no en el
router), y en ese orden. Los codigos de error hacia afuera no cambian.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.public_api.repository import PublicRepository
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

TELEFONO = "+5491155550801"


async def _tienda_con_turno(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str, datetime]:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, token = await register_and_login(
        client, slug="agenda-unica", email="agenda-unica@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)  # 06-18 local
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local

    def reserva(inicio: datetime, telefono: str, clave: str) -> dict[str, str]:
        return {
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": inicio.isoformat(),
            "client_name": "Agenda",
            # La autogestion exige una ficha con email ENTREGABLE verificado por
            # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
            "client_email": f"agenda-{telefono.lstrip('+')}@example.com",
            "client_phone": telefono,
            "accepts_terms": True,
            "idempotency_key": clave,
        }

    propio = await client.post(
        "/public/appointments", json=reserva(base, TELEFONO, "agenda-unica-01")
    )
    assert propio.status_code == 201, propio.text
    # Un turno ajeno a las 15:00 UTC y un bloqueo a las 16:00 UTC.
    ajeno = await client.post(
        "/public/appointments",
        json=reserva(base + timedelta(hours=2), "+5491155550802", "agenda-unica-02"),
    )
    assert ajeno.status_code == 201, ajeno.text
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": (base + timedelta(hours=3)).isoformat(),
            "ends_at": (base + timedelta(hours=4)).isoformat(),
            "reason": "Pausa",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text

    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text
    return store, staff, str(propio.json()["public_id"]), base


def _espiar(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[str], list[dict[str, Any]]]:
    """Marca entrada/salida de ``staff_can_take_range`` y lo que se ejecuta."""
    registro: list[str] = []
    llamadas: list[dict[str, Any]] = []
    execute_original = session.execute
    funcion_original = PublicRepository.staff_can_take_range

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        sql = str(statement)
        if (
            "FROM staff" in sql
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            registro.append("lock_staff")
        elif "FROM appointment_blocks" in sql:
            registro.append("leer_bloqueos")
        elif "FROM appointments" in sql and "FOR UPDATE" not in sql:
            registro.append("leer_turnos")
        return await execute_original(statement, *args, **kwargs)

    async def funcion_espiada(self: PublicRepository, *args: Any, **kwargs: Any) -> Any:
        llamadas.append(kwargs)
        registro.append("entra")
        try:
            return await funcion_original(self, *args, **kwargs)
        finally:
            registro.append("sale")

    monkeypatch.setattr(session, "execute", execute_espiado)
    monkeypatch.setattr(PublicRepository, "staff_can_take_range", funcion_espiada)
    return registro, llamadas


async def _reprogramar(
    client: AsyncClient, turno: str, inicio: datetime, clave: str
) -> Any:
    return await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": inicio.isoformat(),
            "idempotency_key": clave,
        },
    )


@pytest.mark.asyncio
async def test_reprogramar_usa_la_funcion_del_repositorio_con_el_lock_adentro(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, _staff, turno, base = await _tienda_con_turno(client, monkeypatch)
    registro, llamadas = _espiar(test_session, monkeypatch)

    res = await _reprogramar(client, turno, base + timedelta(hours=1), "agenda-ok-01")

    assert res.status_code == 200, res.text
    assert len(llamadas) == 1, llamadas
    assert llamadas[0]["exclude_appointment_id"] == turno
    # Regla 4: lock y relectura dentro de la funcion del repo, en ese orden.
    dentro = registro[registro.index("entra") + 1 : registro.index("sale")]
    assert dentro.index("lock_staff") < dentro.index("leer_bloqueos"), dentro
    assert dentro.index("lock_staff") < dentro.index("leer_turnos"), dentro
    fuera = registro[: registro.index("entra")] + registro[registro.index("sale") :]
    assert "lock_staff" not in fuera, registro


@pytest.mark.asyncio
async def test_los_rechazos_de_agenda_conservan_sus_codigos(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, _staff, turno, base = await _tienda_con_turno(client, monkeypatch)

    # 22:00 UTC = 19:00 local: fuera del horario (06 a 18 local).
    fuera = await _reprogramar(client, turno, base + timedelta(hours=9), "agenda-e-01")
    assert fuera.status_code == 409, fuera.text
    assert fuera.json()["error_code"] == "OUT_OF_SCHEDULE", fuera.text

    bloqueado = await _reprogramar(
        client, turno, base + timedelta(hours=3), "agenda-e-02"
    )
    assert bloqueado.status_code == 409, bloqueado.text
    assert bloqueado.json()["error_code"] == "SCHEDULE_BLOCKED", bloqueado.text

    ocupado = await _reprogramar(
        client, turno, base + timedelta(hours=2), "agenda-e-03"
    )
    assert ocupado.status_code == 409, ocupado.text
    assert ocupado.json()["error_code"] == "APPOINTMENT_CONFLICT", ocupado.text

    # Moverlo sobre su propio horario no choca consigo mismo.
    mismo = await _reprogramar(
        client, turno, base + timedelta(minutes=15), "agenda-e-04"
    )
    assert mismo.status_code == 200, mismo.text
