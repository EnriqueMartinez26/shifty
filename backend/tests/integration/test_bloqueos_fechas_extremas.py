"""Bloqueos con fechas extremas: 422 y nada escrito, nunca 500.

2026-09-24, revision de perf/f4-back. Sintoma: crear un bloqueo, cerrar la
tienda o mover un bloqueo a 9999-12-31 o a 0001-01-01 respondia 500. Peor:
en el alta el ``INSERT`` ya estaba commiteado cuando la invalidacion del cache
(``invalidate_availability_range``, dia local siguiente o anterior al rango)
levantaba ``ValueError``/``OverflowError``, asi que el bloqueo imposible
quedaba en la agenda.

Decision: cada instante que manda el request (inicio y fin) cae entre hace 2
anios y dentro de 2 anios mas la duracion maxima de un bloqueo (366 dias).
En el PATCH solo se miran los extremos que cambian: editar el motivo de un
bloqueo viejo sigue funcionando.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.staff.model import StaffBlock
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

LEJANOS = ("9999-12-31T23:30:00+00:00", "9999-12-31T23:59:00+00:00")
ANTIGUOS = ("0001-01-01T00:00:00+00:00", "0001-01-01T01:00:00+00:00")


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str, str]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    return store, token, staff


async def _bloqueos(session: AsyncSession) -> list[StaffBlock]:
    session.expire_all()
    return list((await session.execute(select(StaffBlock))).scalars().all())


@pytest.mark.asyncio
async def test_alta_cierre_y_lote_con_fechas_extremas_422_sin_escribir(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token, staff = await _tienda(client, "bloq-extremos")
    headers = auth_headers(token)

    for inicio, fin in (LEJANOS, ANTIGUOS):
        rango = {"starts_at": inicio, "ends_at": fin, "reason": "Imposible"}
        for url, cuerpo in (
            ("/appointment-blocks/", {**rango, "staff_id": staff}),
            ("/appointment-blocks/store-wide", rango),
            ("/appointment-blocks/batch", {**rango, "staff_id": staff}),
            ("/appointment-blocks/preview", {**rango, "staff_id": staff}),
        ):
            res = await client.post(url, headers=headers, json=cuerpo)
            assert res.status_code == 422, (url, inicio, res.text)

    assert await _bloqueos(test_session) == []


@pytest.mark.asyncio
async def test_mover_un_bloqueo_a_fechas_extremas_422(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token, staff = await _tienda(client, "bloq-mover")
    headers = auth_headers(token)
    inicio = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    creado = await client.post(
        "/appointment-blocks/",
        headers=headers,
        json={
            "staff_id": staff,
            "starts_at": inicio.isoformat(),
            "ends_at": (inicio + timedelta(hours=1)).isoformat(),
            "reason": "Tramite",
        },
    )
    assert creado.status_code == 201, creado.text

    for inicio_x, fin_x in (LEJANOS, ANTIGUOS):
        res = await client.patch(
            f"/appointment-blocks/{creado.json()['public_id']}",
            headers=headers,
            json={"starts_at": inicio_x, "ends_at": fin_x},
        )
        assert res.status_code == 422, (inicio_x, res.text)


def _iso_del_front(instante: datetime) -> str:
    """Como ``argentinaLocalToUtcIso`` del front: UTC con milisegundos y Z."""
    return instante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _bloqueo_guardado(
    session: AsyncSession, store: str, staff: str, inicio: datetime, motivo: str
) -> str:
    store_id = (
        await session.execute(select(Store.id).where(Store.public_id == store))
    ).scalar_one()
    bloqueo = StaffBlock(
        store_id=store_id,
        staff_id=staff,
        start_time=inicio,
        end_time=inicio + timedelta(minutes=30),
        reason=motivo,
        is_active=True,
    )
    session.add(bloqueo)
    await session.commit()
    return str(bloqueo.id)


@pytest.mark.asyncio
async def test_editar_el_motivo_de_un_bloqueo_viejo_con_el_payload_del_front(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El formulario de la agenda (``CalendarContainer``) manda SIEMPRE
    ``staff_id``, ``starts_at``, ``ends_at`` y ``reason``: editar solo el
    motivo de un bloqueo de hace 3 anios reenvia los mismos extremos. Solo se
    mira la ventana de fechas en el extremo cuyo VALOR cambia."""
    store, token, staff = await _tienda(client, "bloq-viejo")
    inicio = (datetime.now(timezone.utc) - timedelta(days=3 * 365)).replace(
        second=0, microsecond=0
    )
    viejo = await _bloqueo_guardado(test_session, store, staff, inicio, "Hace 3 anios")

    res = await client.patch(
        f"/appointment-blocks/{viejo}",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": _iso_del_front(inicio),
            "ends_at": _iso_del_front(inicio + timedelta(minutes=30)),
            "reason": "Motivo corregido",
        },
    )
    movido = await client.patch(
        f"/appointment-blocks/{viejo}",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": _iso_del_front(inicio - timedelta(hours=1)),
            "ends_at": _iso_del_front(inicio + timedelta(minutes=30)),
            "reason": "Motivo corregido",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["reason"] == "Motivo corregido"
    # Mover el inicio a otra fecha fuera de la ventana si se rechaza.
    assert movido.status_code == 422, movido.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inicio", "otro"),
    [
        (
            datetime(9999, 12, 31, 23, 0, tzinfo=timezone.utc),
            datetime(9999, 12, 31, 21, 0, tzinfo=timezone.utc),
        ),
        # En 0001 la zona argentina es la hora media local (-3:53): llevar
        # 0001-01-01T00:00Z a hora local cae en el anio 0 (revision de
        # perf/f4-back, 2026-09-25: ``days_covered`` desbordaba sin guarda).
        (
            datetime(1, 1, 1, 0, 0, tzinfo=timezone.utc),
            datetime(1, 1, 1, 2, 0, tzinfo=timezone.utc),
        ),
    ],
)
async def test_borrar_o_editar_un_bloqueo_imposible_ya_guardado_no_da_500(
    client: AsyncClient, test_session: AsyncSession, inicio: datetime, otro: datetime
) -> None:
    """Un bloqueo en 9999-12-31 o en 0001-01-01 que ya esta en la base (de
    antes de la ventana) se tiene que poder editar y borrar: la invalidacion
    del cache desbordaba DESPUES del commit (500). Ahora cae a invalidar la
    tienda entera."""
    store, token, staff = await _tienda(client, f"bloq-imposible-{inicio.year}")
    headers = auth_headers(token)
    editar = await _bloqueo_guardado(test_session, store, staff, inicio, "Imposible")
    borrar = await _bloqueo_guardado(test_session, store, staff, otro, "Imposible 2")

    editado = await client.patch(
        f"/appointment-blocks/{editar}",
        headers=headers,
        json={
            "staff_id": staff,
            "starts_at": _iso_del_front(inicio),
            "ends_at": _iso_del_front(inicio + timedelta(minutes=30)),
            "reason": "Imposible corregido",
        },
    )
    borrado = await client.delete(f"/appointment-blocks/{borrar}", headers=headers)

    assert editado.status_code == 200, editado.text
    assert borrado.status_code == 204, borrado.text
