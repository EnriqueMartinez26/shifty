"""La segunda consulta de ``expire_lapsed_offers`` tambien va acotada.

Auditoria 2, AUD2-B1-12 (2026-09-20). B1-16 le puso tope y orden al lote de
ofertas vencidas ("cada vencida cuesta varias consultas... sin tope, una cola
grande acercaba la corrida al time limit de Celery"), pero la SEGUNDA consulta
de la misma funcion -las entradas cuya ventana ya paso- quedo sin ``limit`` y
sin ``order_by``: barria todas las tiendas de la instalacion de una, con
``FOR UPDATE SKIP LOCKED`` sobre cada fila que trajera. En regimen la cantidad
es chica (cada entrada expira una sola vez), pero un backlog -el beat caido
unos dias, o la primera corrida despues de meses de uso- hace una sola
transaccion que lockea todas esas filas. Regla 8: los lotes van acotados.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import expire_lapsed_offers
from tests.integration.test_lista_de_espera import _alta, _tienda


async def _dos_ventanas_vencidas(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[list[str], datetime]:
    """Dos entradas en espera cuya ventana ya paso, en dias distintos.

    Vencen al reves del orden de alta para que el orden del lote no salga
    gratis del orden de insercion.
    """
    store, _token, service, _staff, slot = await _tienda(client, slug)
    ids: list[str] = []
    for i in range(2):
        alta = await client.post(
            "/public/waitlist",
            json=_alta(
                store,
                service,
                slot + timedelta(days=i),
                client_name=f"Vencida {i}",
                client_phone=f"+54911556{i:05d}",
                client_email=f"vencida{i}-{slug}@example.com",
            ),
        )
        assert alta.status_code == 201, alta.text
        ids.append(str(alta.json()["public_id"]))

    ahora = datetime.now(timezone.utc)
    filas = {
        e.id: e
        for e in (
            await session.execute(
                select(WaitlistEntry).where(WaitlistEntry.id.in_(ids))
            )
        ).scalars()
    }
    for i, entry_id in enumerate(ids):
        # ``ck_waitlist_window`` exige inicio < fin: se mueve la ventana
        # entera al pasado, no solo el extremo.
        filas[entry_id].window_starts_at = ahora - timedelta(hours=3, minutes=i)
        filas[entry_id].window_ends_at = ahora - timedelta(minutes=1 + i)
    await session.commit()
    return ids, ahora


async def _estados(session: AsyncSession, ids: list[str]) -> list[str]:
    session.expire_all()
    filas = {
        e.id: e.status
        for e in (
            await session.execute(
                select(WaitlistEntry).where(WaitlistEntry.id.in_(ids))
            )
        ).scalars()
    }
    return [filas[i] for i in ids]


@pytest.mark.asyncio
async def test_las_ventanas_vencidas_se_expiran_de_a_lote(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids, ahora = await _dos_ventanas_vencidas(client, test_session, "ventana-tope")

    consultas: list[Any] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        consultas.append(statement)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    primera = await expire_lapsed_offers(test_session, now=ahora, limit=1)
    await test_session.commit()
    monkeypatch.undo()

    # Una por corrida, la que vencio primero (la ultima anotada).
    assert primera.expired == 1
    assert await _estados(test_session, ids) == ["waiting", "expired"]

    # Sin ofertas vencidas la primera consulta no trae nada, asi que la de
    # ventanas es la segunda: tope, orden determinista y la guarda de la
    # regla 8 intacta.
    ventanas = consultas[1]
    assert ventanas._limit_clause is not None, "las ventanas vencidas no tienen tope"
    assert "window_ends_at" in str(ventanas._order_by_clause), "sin orden determinista"
    assert ventanas._for_update_arg is not None and ventanas._for_update_arg.skip_locked

    # El resto va en la corrida siguiente.
    segunda = await expire_lapsed_offers(test_session, now=ahora, limit=1)
    await test_session.commit()
    assert segunda.expired == 1
    assert await _estados(test_session, ids) == ["expired", "expired"]
