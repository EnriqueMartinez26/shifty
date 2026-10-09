"""Semana de trabajo del profesional, reemplazada de una vez (2026-10-08).

Sintoma: el manual le pide al admin "A cada persona cargale sus dias y horas
de trabajo", pero el panel no tenia editor y la API solo ofrecia una franja
por llamada (``POST``/``PATCH``/``DELETE /staff/{id}/schedules...``). Armar
la semana con N llamadas deja estados intermedios a la vista del portal (al
cargar la PRIMERA franja el profesional deja de atender todos los demas dias:
D-20260929-01) y una falla a mitad de camino guarda media semana.

``PUT /staff/{public_id}/schedules`` reemplaza la semana entera en UNA
transaccion: lista vacia = vuelve al horario del local (D-20260929-01), y
franjas superpuestas el mismo dia se rechazan sin tocar lo guardado.

La regla de la agenda la fija ``appointments/working_hours.py``: estos tests
prueban que la grilla (panel y portal publico) sigue a la semana guardada.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from core.utils import ARGENTINA_TZ
from tests.integration.test_alta_del_panel_para_cliente import Agenda, _agenda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
)

DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _dia_local(momento: datetime) -> int:
    return momento.astimezone(ARGENTINA_TZ).weekday()


async def _guardar_semana(
    client: AsyncClient, agenda: Agenda, staff: str, franjas: list[dict[str, Any]]
) -> Any:
    return await client.put(
        f"/staff/{staff}/schedules",
        headers=auth_headers(agenda.token),
        json={"schedules": franjas},
    )


async def _slots_panel(
    client: AsyncClient, agenda: Agenda, staff: str, dia: datetime
) -> list[str]:
    res = await client.get(
        "/appointments/availability",
        headers=auth_headers(agenda.token),
        params={
            "service_id": agenda.service,
            "date": dia.astimezone(ARGENTINA_TZ).date().isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    return [s["start_time"] for s in res.json() if s["staff_id"] == staff]


async def _slots_portal(
    client: AsyncClient, agenda: Agenda, staff: str, dia: datetime
) -> list[str]:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": agenda.store,
            "service_id": agenda.service,
            "date": dia.astimezone(ARGENTINA_TZ).date().isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    return [
        s["start_time"]
        for s in res.json()
        if s["staff_id"] == staff and s["status"] == "available"
    ]


async def _horario_del_local(
    client: AsyncClient, agenda: Agenda, dia: datetime, abre: str, cierra: str
) -> None:
    res = await client.patch(
        "/stores/me",
        headers=auth_headers(agenda.token),
        json={
            "business_hours": {DIAS[_dia_local(dia)]: [{"open": abre, "close": cierra}]}
        },
    )
    assert res.status_code == 200, res.text


def _franja(dia: int, inicio: str, fin: str) -> dict[str, Any]:
    return {"day_of_week": dia, "start_time": inicio, "end_time": fin}


@pytest.mark.asyncio
async def test_un_dia_sin_franjas_en_la_semana_no_tiene_turnos_en_el_portal(
    client: AsyncClient,
) -> None:
    """ "Lucas no trabaja los lunes": sin slots ese dia, ni en el panel ni en
    el portal, aunque el local abra y antes tuviera franja ese dia."""
    agenda = await _agenda(client, "semana-cerrado")
    dia = agenda.slot
    siguiente = dia + timedelta(days=1)
    # La agenda del dia queda en cache con el profesional atendiendo.
    assert await _slots_panel(client, agenda, agenda.staff, dia)
    await _horario_del_local(client, agenda, dia, "06:00", "18:00")

    semana = [
        _franja(d, "10:00:00", "14:00:00") for d in range(7) if d != _dia_local(dia)
    ]
    res = await _guardar_semana(client, agenda, agenda.staff, semana)

    assert res.status_code == 200, res.text
    assert len(res.json()) == 6
    assert _dia_local(dia) not in {f["day_of_week"] for f in res.json()}
    # El cache del dia se invalido: el dia cerrado ya no ofrece nada.
    assert await _slots_panel(client, agenda, agenda.staff, dia) == []
    assert await _slots_portal(client, agenda, agenda.staff, dia) == []
    # El dia siguiente sigue la franja nueva (10 a 14 local), no la vieja.
    horas = await _slots_portal(client, agenda, agenda.staff, siguiente)
    assert horas, "el dia con franja tiene que ofrecer turnos"
    assert min(horas) == "10:00:00"
    assert max(horas) < "14:00:00"


@pytest.mark.asyncio
async def test_dos_franjas_el_mismo_dia_dejan_el_corte_sin_turnos(
    client: AsyncClient,
) -> None:
    agenda = await _agenda(client, "semana-partido")
    dia = _dia_local(agenda.slot)

    res = await _guardar_semana(
        client,
        agenda,
        agenda.staff,
        [_franja(dia, "14:00:00", "18:00:00"), _franja(dia, "09:00:00", "12:00:00")],
    )

    assert res.status_code == 200, res.text
    # La respuesta sale ordenada por dia y hora de inicio.
    assert [f["start_time"] for f in res.json()] == ["09:00:00", "14:00:00"]
    horas = await _slots_panel(client, agenda, agenda.staff, agenda.slot)
    assert "09:00:00" in horas and "14:00:00" in horas
    assert not [h for h in horas if "12:00:00" <= h < "14:00:00"]


@pytest.mark.asyncio
async def test_semana_vacia_vuelve_al_horario_del_local(client: AsyncClient) -> None:
    agenda = await _agenda(client, "semana-vacia")
    await _horario_del_local(client, agenda, agenda.slot, "09:00", "12:00")
    # Con su franja propia (06 a 18 local) arranca a las 06.
    assert min(await _slots_panel(client, agenda, agenda.staff, agenda.slot)) == (
        "06:00:00"
    )

    res = await _guardar_semana(client, agenda, agenda.staff, [])

    assert res.status_code == 200, res.text
    assert res.json() == []
    horas = await _slots_panel(client, agenda, agenda.staff, agenda.slot)
    assert min(horas) == "09:00:00"
    assert max(horas) < "12:00:00"
    ficha = await client.get(
        f"/staff/{agenda.staff}", headers=auth_headers(agenda.token)
    )
    assert ficha.json()["schedules"] == []


@pytest.mark.asyncio
async def test_franjas_superpuestas_se_rechazan_sin_tocar_lo_guardado(
    client: AsyncClient,
) -> None:
    agenda = await _agenda(client, "semana-superpuesta")
    antes = (
        await client.get(f"/staff/{agenda.staff}", headers=auth_headers(agenda.token))
    ).json()["schedules"]

    res = await _guardar_semana(
        client,
        agenda,
        agenda.staff,
        [
            _franja(0, "08:00:00", "10:00:00"),
            _franja(2, "09:00:00", "13:00:00"),
            _franja(2, "12:30:00", "15:00:00"),
        ],
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "SCHEDULE_OVERLAP"
    assert res.json()["detail"] == {"day_of_week": 2}
    despues = (
        await client.get(f"/staff/{agenda.staff}", headers=auth_headers(agenda.token))
    ).json()["schedules"]
    assert despues == antes


@pytest.mark.asyncio
async def test_franjas_que_se_tocan_en_el_borde_son_validas(
    client: AsyncClient,
) -> None:
    agenda = await _agenda(client, "semana-borde")

    res = await _guardar_semana(
        client,
        agenda,
        agenda.staff,
        [_franja(4, "09:00:00", "13:00:00"), _franja(4, "13:00:00", "17:00:00")],
    )

    assert res.status_code == 200, res.text
    assert len(res.json()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"schedules": None},
        {"schedules": [_franja(1, "12:00:00", "09:00:00")]},
        {"schedules": [_franja(7, "09:00:00", "12:00:00")]},
        {"schedules": [_franja(-1, "09:00:00", "12:00:00")]},
        # Tope de franjas (MAX_SCHEDULES_PER_WEEK = 42): 43 franjas.
        {
            "schedules": [
                _franja(d, f"{h:02d}:00:00", f"{h:02d}:30:00")
                for d in range(7)
                for h in range(7)
            ][:43]
        },
    ],
    ids=["sin-clave", "null", "inicio-tras-fin", "dia-7", "dia-negativo", "43"],
)
async def test_cuerpos_invalidos_son_422_y_no_borran_la_semana(
    client: AsyncClient, cuerpo: dict[str, Any]
) -> None:
    agenda = await _agenda(client, "semana-invalida")

    res = await client.put(
        f"/staff/{agenda.staff}/schedules",
        headers=auth_headers(agenda.token),
        json=cuerpo,
    )

    assert res.status_code == 422, res.text
    ficha = await client.get(
        f"/staff/{agenda.staff}", headers=auth_headers(agenda.token)
    )
    assert len(ficha.json()["schedules"]) == 1


@pytest.mark.asyncio
async def test_no_se_toca_la_semana_de_un_profesional_de_otra_tienda(
    client: AsyncClient,
) -> None:
    alfa = await _agenda(client, "semana-alfa")
    beta = await _agenda(client, "semana-beta")

    res = await _guardar_semana(client, alfa, beta.staff, [])

    assert res.status_code == 404, res.text
    ficha = await client.get(f"/staff/{beta.staff}", headers=auth_headers(beta.token))
    assert len(ficha.json()["schedules"]) == 1


@pytest.mark.asyncio
async def test_un_profesional_nuevo_recibe_su_semana(client: AsyncClient) -> None:
    """El alta nace sin franjas (horario del local); la semana se carga aparte."""
    agenda = await _agenda(client, "semana-alta")
    nuevo = await create_staff(
        client, agenda.token, agenda.service, email="nuevo-semana-alta@t.com"
    )

    res = await _guardar_semana(
        client, agenda, nuevo, [_franja(d, "09:00:00", "17:00:00") for d in range(5)]
    )

    assert res.status_code == 200, res.text
    assert [f["day_of_week"] for f in res.json()] == [0, 1, 2, 3, 4]


# 2026-10-08 (revision de #130): Pydantic acepta una hora con offset
# ("09:00:00Z" da un ``time`` con tzinfo). Mezclar horas con y sin offset el
# mismo dia hacia que ``sorted`` (``first_overlapping_day``) o la comparacion
# de ``validate_time_order`` levantaran TypeError: un 500 alcanzable (regla
# 20). Las franjas son hora local de pared: una hora con offset es 422.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "franjas",
    [
        [_franja(2, "09:00:00Z", "12:00:00Z"), _franja(2, "13:00:00", "15:00:00")],
        [_franja(2, "09:00:00Z", "12:00:00")],
        [_franja(2, "09:00:00-03:00", "12:00:00-03:00")],
    ],
    ids=["mezcla-en-el-dia", "mezcla-en-la-franja", "todas-con-offset"],
)
async def test_put_con_hora_con_offset_es_422_y_no_500(
    client: AsyncClient, franjas: list[dict[str, Any]]
) -> None:
    agenda = await _agenda(client, "semana-offset")

    res = await _guardar_semana(client, agenda, agenda.staff, franjas)

    assert res.status_code == 422, res.text
    ficha = await client.get(
        f"/staff/{agenda.staff}", headers=auth_headers(agenda.token)
    )
    assert len(ficha.json()["schedules"]) == 1


@pytest.mark.asyncio
async def test_post_de_una_franja_con_offset_es_422(client: AsyncClient) -> None:
    agenda = await _agenda(client, "franja-offset-post")

    res = await client.post(
        f"/staff/{agenda.staff}/schedules",
        headers=auth_headers(agenda.token),
        json=_franja(3, "09:00:00Z", "12:00:00Z"),
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cambios",
    [{"start_time": "07:00:00Z"}, {"end_time": "20:00:00+00:00"}],
    ids=["inicio", "fin"],
)
async def test_patch_de_una_franja_con_offset_es_422(
    client: AsyncClient, cambios: dict[str, Any]
) -> None:
    agenda = await _agenda(client, "franja-offset-patch")
    franja = (
        await client.get(f"/staff/{agenda.staff}", headers=auth_headers(agenda.token))
    ).json()["schedules"][0]

    res = await client.patch(
        f"/staff/{agenda.staff}/schedules/{franja['public_id']}",
        headers=auth_headers(agenda.token),
        json=cambios,
    )

    assert res.status_code == 422, res.text
