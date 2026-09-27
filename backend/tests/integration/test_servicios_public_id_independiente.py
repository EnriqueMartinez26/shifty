"""AUD2-B6-08 / B6-09 (2026-09-20): `new_service.public_id = new_service.id` no hacia nada.

Sintoma: la linea prometia que el `public_id` del servicio fuera igual a su
`id` interno, pero corria ANTES del flush, cuando `id` todavia es `None`.
SQLAlchemy resuelve entonces los dos `default` por separado en el INSERT y
salen dos ULID distintos. Quien leyera el repositorio iba a creer que puede
buscar un servicio por `id` con un `public_id` (o al reves) y fallar solo en
runtime. Es codigo muerto que documenta un invariante falso.

Este test fija lo que el codigo hace de verdad: las dos columnas son
independientes y cada camino usa la suya. No decide que `public_id` DEBA ser
distinto del `id` (eso es del dueno): deja escrito que hoy lo es, para que
borrar la linea no cambie nada y para que volver a ponerla no pase
inadvertido.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.services.repository import ServiceRepository
from modules.stores.model import Store


async def _tienda(session: AsyncSession, slug: str) -> str:
    # Sin `tienda.public_id = tienda.id`: es el mismo patron muerto que este
    # test denuncia (antes del flush, `id` todavia es None). El test solo usa
    # el `id` interno como `store_id` del servicio.
    tienda = Store(name=f"Tienda {slug}", slug=slug)
    session.add(tienda)
    await session.flush()
    return str(tienda.id)


@pytest.mark.asyncio
async def test_el_public_id_del_servicio_es_independiente_del_id(
    test_session: AsyncSession,
) -> None:
    store_id = await _tienda(test_session, "aud2-b6-08")
    repo = ServiceRepository(test_session)
    servicio = await repo.create(
        {"name": "Corte", "duration_minutes": 30, "price": 1000}, store_id
    )

    assert servicio.id
    assert servicio.public_id
    assert servicio.public_id != servicio.id

    # Cada columna la usa quien corresponde: el repositorio busca por
    # public_id y la relacion con staff guarda el id interno.
    por_public_id = await repo.get_by_id(servicio.public_id, store_id)
    assert por_public_id is not None and por_public_id.id == servicio.id

    por_id = await test_session.execute(
        select(Service.public_id).where(Service.id == servicio.id)
    )
    assert por_id.scalar_one() == servicio.public_id

    # El public_id nunca es una busqueda valida por id interno.
    assert (await repo.get_by_id(servicio.id, store_id)) is None, (
        "public_id e id no son intercambiables"
    )
