"""Aislamiento entre tiendas: la invariante mas importante de un SaaS.

El rol de base que usa la aplicacion resulto ser superuser con BYPASSRLS, asi
que las politicas de Row-Level Security no filtran nada: el aislamiento depende
por completo de los filtros ``store_id`` del codigo. Estos tests atacan cada
endpoint administrativo con ids de OTRA tienda para que esa dependencia quede
verificada y no se erosione.
"""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    register_and_login,
)


class Tienda:
    """Una tienda lista para operar: servicio, profesional, agenda y token."""

    def __init__(self, token: str, store: str, servicio: str, staff: str) -> None:
        self.token = token
        self.store = store
        self.servicio = servicio
        self.staff = staff


async def _montar(client: AsyncClient, *, slug: str, email: str) -> Tienda:
    store, token = await register_and_login(client, slug=slug, email=email)
    servicio = await create_service(client, token)
    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro",
            "first_name": "Pro",
            "last_name": "Fesional",
            "email": f"pro-{slug}@aislamiento.com",
            "service_ids": [servicio],
        },
    )
    assert alta.status_code == 201, alta.text
    staff = cast(str, alta.json()["public_id"])

    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return Tienda(token, store, servicio, staff)


def _slot(hora: int) -> str:
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    return dia.replace(hour=hora, minute=0, second=0, microsecond=0).isoformat()


async def _turno(client: AsyncClient, tienda: Tienda, *, hora: int, clave: str) -> str:
    res = await client.post(
        "/appointments/",
        headers=auth_headers(tienda.token),
        json={
            "service_id": tienda.servicio,
            "staff_id": tienda.staff,
            "starts_at": _slot(hora),
            "idempotency_key": clave,
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


@pytest_asyncio.fixture
async def dos_tiendas(client: AsyncClient) -> tuple[Tienda, Tienda]:
    a = await _montar(client, slug="aisl-a", email="aisl-a@test.com")
    b = await _montar(client, slug="aisl-b", email="aisl-b@test.com")
    return a, b


# ---------------------------------------------------------------------------
# Carga de turnos con ids cruzados
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_se_puede_reservar_con_recursos_de_otra_tienda(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    """El caso mas grave: crear turnos en la agenda ajena.

    El alta resolvia servicio y profesional por id sin acotar a la tienda del
    turno, asi que mandar los ids de otra tienda creaba el turno igual.
    """
    a, b = dos_tiendas

    combinaciones = [
        (a.servicio, a.staff, "servicio y profesional ajenos"),
        (b.servicio, a.staff, "profesional ajeno"),
        (a.servicio, b.staff, "servicio ajeno"),
    ]
    for i, (servicio, staff, caso) in enumerate(combinaciones):
        res = await client.post(
            "/appointments/",
            headers=auth_headers(b.token),
            json={
                "service_id": servicio,
                "staff_id": staff,
                "starts_at": _slot(11 + i),
                "idempotency_key": f"cruce-aislamiento-{i}",
            },
        )
        assert res.status_code >= 400, f"{caso} fue aceptado ({res.status_code})"


# ---------------------------------------------------------------------------
# Transiciones sobre turnos ajenos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ninguna_transicion_alcanza_un_turno_ajeno(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    """Cada accion se prueba sobre un turno nuevo.

    Reutilizar el mismo turno enmascara el problema: tras confirmarlo y
    completarlo, el resto rebota por el grafo de estados y parece protegido
    cuando en realidad no se estaba validando la tienda.
    """
    a, b = dos_tiendas

    for i, accion in enumerate(["confirm", "complete", "cancel", "absent", "release"]):
        turno = await _turno(client, a, hora=9 + i, clave=f"transicion-ajena-{i}")
        res = await client.patch(
            f"/appointments/{turno}/{accion}", headers=auth_headers(b.token)
        )
        assert res.status_code == 404, (
            f"{accion} sobre turno ajeno respondio {res.status_code}"
        )


@pytest.mark.asyncio
async def test_no_se_pueden_leer_ni_escribir_notas_de_un_turno_ajeno(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    a, b = dos_tiendas
    turno = await _turno(client, a, hora=15, clave="notas-ajenas-001")

    res = await client.patch(
        f"/appointments/{turno}/notes-staff",
        headers=auth_headers(b.token),
        json={"notes_staff": "informacion privada"},
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_no_se_puede_reprogramar_un_turno_ajeno(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    a, b = dos_tiendas
    turno = await _turno(client, a, hora=16, clave="reprogramar-ajeno-001")

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(b.token),
        json={
            "new_starts_at": _slot(17),
            "idempotency_key": "reprogramar-ajeno-nuevo-001",
        },
    )
    assert res.status_code >= 400, res.text


# ---------------------------------------------------------------------------
# Listados
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_busqueda_de_turnos_no_cruza_tiendas(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    """search_appointments no tenia ningun filtro de tienda."""
    a, b = dos_tiendas
    turno_a = await _turno(client, a, hora=10, clave="busqueda-aislada-001")

    res = await client.get(
        "/appointments/search",
        headers=auth_headers(b.token),
        params={"page": 1, "page_size": 100},
    )
    assert res.status_code == 200, res.text
    ajenos = [t for t in res.json()["results"] if t["public_id"] == turno_a]
    assert not ajenos, "la busqueda devolvio turnos de otra tienda"


@pytest.mark.asyncio
async def test_los_listados_solo_muestran_lo_propio(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    a, b = dos_tiendas

    staff = await client.get("/staff/", headers=auth_headers(b.token))
    assert all(s["public_id"] != a.staff for s in staff.json())

    servicios = await client.get("/services/", headers=auth_headers(b.token))
    assert all(s["public_id"] != a.servicio for s in servicios.json())


# ---------------------------------------------------------------------------
# Recursos de configuracion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_se_puede_operar_sobre_el_catalogo_ajeno(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    a, b = dos_tiendas
    H = auth_headers(b.token)

    assert (await client.get(f"/services/{a.servicio}", headers=H)).status_code == 404
    assert (
        await client.patch(f"/services/{a.servicio}", headers=H, json={"price": 1})
    ).status_code == 404
    assert (
        await client.delete(f"/services/{a.servicio}", headers=H)
    ).status_code == 404
    assert (await client.get(f"/staff/{a.staff}", headers=H)).status_code == 404
    assert (
        # Nombre valido a proposito: con uno de 1 caracter el schema rebota
        # antes de llegar al chequeo de tienda y el test no probaria nada.
        await client.patch(
            f"/staff/{a.staff}", headers=H, json={"display_name": "Intruso"}
        )
    ).status_code == 404
    assert (await client.delete(f"/staff/{a.staff}", headers=H)).status_code == 404


@pytest.mark.asyncio
async def test_no_se_puede_agendar_ni_bloquear_al_personal_ajeno(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    a, b = dos_tiendas
    H = auth_headers(b.token)

    horario = await client.post(
        f"/staff/{a.staff}/schedules",
        headers=H,
        json={"day_of_week": 0, "start_time": "08:00:00", "end_time": "09:00:00"},
    )
    assert horario.status_code >= 400, horario.text

    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=H,
        json={
            "staff_id": a.staff,
            "starts_at": _slot(12),
            "ends_at": _slot(13),
            "reason": "intruso",
        },
    )
    assert bloqueo.status_code >= 400, bloqueo.text


@pytest.mark.asyncio
async def test_la_disponibilidad_publica_no_mezcla_catalogos(
    client: AsyncClient, dos_tiendas: tuple[Tienda, Tienda]
) -> None:
    """Pedir la agenda de B con un servicio de A no puede devolver horarios."""
    a, b = dos_tiendas
    dia = datetime.now(timezone.utc) + timedelta(days=4)

    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": b.store,
            "service_id": a.servicio,
            "date": dia.strftime("%Y-%m-%d"),
        },
    )
    assert res.status_code == 200, res.text
    assert res.json() == [], "devolvio slots para un servicio de otra tienda"
