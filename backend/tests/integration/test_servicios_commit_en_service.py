"""B6-05 (2026-09-30, D-20260930-14): el commit del catalogo es del service.

``ServiceRepository`` commiteaba en ``create``/``update``/``soft_delete``. El
PATCH que desvincula la imagen subida borra la fila de ``store_media`` ANTES
de guardar el servicio: con el commit en el repositorio dependia de que nadie
metiera nada en el medio. Ahora el repositorio solo hace ``flush`` y
``ServiceCatalogService`` cierra UNA transaccion: si el commit falla, el
servicio conserva su ``image_url`` y la imagen conserva su fila. Lo que sale
de la base (invalidar el cache de disponibilidad) va despues del commit.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.services.service import ServiceCatalogService
from tests.conftest import MockRedis
from tests.integration.test_imagen_de_servicio import (
    _filas_del_servicio,
    _subir,
    _tienda_con_servicio,
)


class _CommitFalla(RuntimeError):
    pass


async def _servicio(db: AsyncSession, public_id: str) -> Service:
    res = await db.execute(select(Service).where(Service.public_id == public_id))
    return res.scalar_one()


@pytest.mark.asyncio
async def test_si_el_commit_falla_el_patch_no_borra_la_imagen_ni_invalida(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, token, publico = await _tienda_con_servicio(client, "b6-05-atomico")
    _, subida = await _subir(client, token, publico)
    url_subida = subida["image_url"]
    servicio = await _servicio(test_session, publico)
    store_id, nombre = str(servicio.store_id), servicio.name
    llamadas: list[str] = []

    async def _registrar(_cache: object, store: str) -> None:
        llamadas.append(store)

    async def _commit_roto() -> None:
        raise _CommitFalla("commit roto")

    monkeypatch.setattr(
        "modules.services.service.invalidate_store_availability", _registrar
    )
    monkeypatch.setattr(test_session, "commit", _commit_roto)

    with pytest.raises(_CommitFalla):
        await ServiceCatalogService(test_session, cache=MockRedis()).update(
            publico, store_id, {"image_url": None, "name": "Otro nombre"}
        )
    await test_session.rollback()

    assert llamadas == [], "la invalidacion va despues del commit"
    recargado = await _servicio(test_session, publico)
    assert recargado.name == nombre
    assert recargado.image_url == url_subida
    assert await _filas_del_servicio(test_session, publico) == 1


@pytest.mark.asyncio
async def test_el_patch_commitea_una_vez_y_despues_invalida(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, token, publico = await _tienda_con_servicio(client, "b6-05-orden")
    await _subir(client, token, publico)
    servicio = await _servicio(test_session, publico)
    store_id = str(servicio.store_id)
    eventos: list[str] = []
    commit_real = test_session.commit

    async def _commit() -> None:
        eventos.append("commit")
        await commit_real()

    async def _invalidar(_cache: object, store: str) -> None:
        eventos.append(f"invalidar:{store}")

    monkeypatch.setattr(test_session, "commit", _commit)
    monkeypatch.setattr(
        "modules.services.service.invalidate_store_availability", _invalidar
    )

    actualizado = await ServiceCatalogService(test_session, cache=MockRedis()).update(
        publico, store_id, {"image_url": None}
    )

    assert eventos == ["commit", f"invalidar:{store_id}"]
    assert actualizado.image_url is None
    assert await _filas_del_servicio(test_session, publico) == 0


@pytest.mark.asyncio
async def test_la_baja_commitea_y_despues_invalida(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, publico = await _tienda_con_servicio(client, "b6-05-baja")
    servicio = await _servicio(test_session, publico)
    store_id = str(servicio.store_id)
    eventos: list[str] = []
    commit_real = test_session.commit

    async def _commit() -> None:
        eventos.append("commit")
        await commit_real()

    async def _invalidar(_cache: object, store: str) -> None:
        eventos.append(f"invalidar:{store}")

    monkeypatch.setattr(test_session, "commit", _commit)
    monkeypatch.setattr(
        "modules.services.service.invalidate_store_availability", _invalidar
    )

    await ServiceCatalogService(test_session, cache=MockRedis()).soft_delete(
        publico, store_id
    )

    assert eventos == ["commit", f"invalidar:{store_id}"]
    assert (await _servicio(test_session, publico)).is_active is False
