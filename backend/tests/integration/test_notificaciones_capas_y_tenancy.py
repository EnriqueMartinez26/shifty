"""Campanita del panel: capas router -> service -> repository y aislamiento.

B4-05 (2026-09-18): ``modules/notifications/router.py`` armaba sus propias
consultas y commiteaba (``await db.commit()`` en marcar leida y en read-all);
el modulo no tenia ``service.py`` ni ``repository.py``. CLAUDE.md §2: el
router solo hace HTTP, el service es dueno de la transaccion y el repositorio
hace consultas puras. Al mover las consultas, los filtros ``store_id`` pasan
al repositorio: el segundo test demuestra que siguen vivos por HTTP.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.model import Notification, NotificationType
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

_MODULO = Path(__file__).resolve().parents[2] / "modules" / "notifications"


def _llamadas_a_atributo(path: Path, nombres: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    encontradas: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in nombres
        ):
            encontradas.append(f"{path.name}:{node.lineno} .{node.func.attr}(")
    return encontradas


def test_router_de_notificaciones_no_commitea_ni_consulta() -> None:
    """El router delega; el commit vive en el service y no en el repositorio."""
    assert (_MODULO / "service.py").is_file(), "falta modules/notifications/service.py"
    assert (_MODULO / "repository.py").is_file(), (
        "falta modules/notifications/repository.py"
    )

    en_router = _llamadas_a_atributo(
        _MODULO / "router.py", {"commit", "execute", "scalar", "scalars"}
    )
    assert en_router == [], f"el router toca la sesion: {en_router}"

    en_repo = _llamadas_a_atributo(_MODULO / "repository.py", {"commit"})
    assert en_repo == [], f"el repositorio commitea: {en_repo}"

    en_service = _llamadas_a_atributo(_MODULO / "service.py", {"commit"})
    assert en_service, "el service tiene que ser el dueno del commit"


async def _sembrar(
    session: AsyncSession, store_id: str, titulo: str, *, leida: bool = False
) -> str:
    notificacion = Notification(
        store_id=store_id,
        type=NotificationType.PAYMENT_APPROVED.value,
        title=titulo,
        body=None,
    )
    if leida:
        notificacion.mark_read()
    session.add(notificacion)
    await session.flush()
    notificacion_id = notificacion.id
    await session.commit()
    return notificacion_id


async def _store_id(session: AsyncSession, store_public_id: str) -> str:
    store_id = await session.scalar(
        select(Store.id).where(Store.public_id == store_public_id)
    )
    assert store_id is not None
    return str(store_id)


async def _read_at(session: AsyncSession, notificacion_id: str) -> object:
    session.expire_all()
    return await session.scalar(
        select(Notification.read_at).where(Notification.id == notificacion_id)
    )


@pytest.mark.asyncio
async def test_notificaciones_de_otra_tienda_no_se_leen_ni_se_marcan(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Guarda de tenancy: listar, contar, marcar una y read-all por tienda."""
    publica_a, token_a = await register_and_login(
        client, slug="notif-capas-a", email="notif-capas-a@test.com"
    )
    publica_b, token_b = await register_and_login(
        client, slug="notif-capas-b", email="notif-capas-b@test.com"
    )
    tienda_a = await _store_id(test_session, publica_a)
    tienda_b = await _store_id(test_session, publica_b)
    ajena_1 = await _sembrar(test_session, tienda_a, "de A 1")
    ajena_2 = await _sembrar(test_session, tienda_a, "de A 2")
    propia = await _sembrar(test_session, tienda_b, "de B")
    await _sembrar(test_session, tienda_b, "de B leida", leida=True)

    listado = await client.get("/notifications", headers=auth_headers(token_b))
    assert listado.status_code == 200, listado.text
    titulos = {item["title"] for item in listado.json()["items"]}
    assert titulos == {"de B", "de B leida"}
    assert listado.json()["unread_count"] == 1

    # Marcar por id una notificacion de otra tienda: 404 y no se toca.
    cruzada = await client.post(
        f"/notifications/{ajena_1}/read", headers=auth_headers(token_b)
    )
    assert cruzada.status_code == 404, cruzada.text
    assert await _read_at(test_session, ajena_1) is None

    # La propia se marca una vez; la segunda no cuenta como actualizada.
    primera = await client.post(
        f"/notifications/{propia}/read", headers=auth_headers(token_b)
    )
    assert primera.status_code == 200, primera.text
    assert primera.json() == {"updated": 1, "unread_count": 0}
    segunda = await client.post(
        f"/notifications/{propia}/read", headers=auth_headers(token_b)
    )
    assert segunda.json() == {"updated": 0, "unread_count": 0}

    # read-all de B no marca las de A.
    todas_b = await client.post(
        "/notifications/read-all", headers=auth_headers(token_b)
    )
    assert todas_b.status_code == 200, todas_b.text
    assert todas_b.json() == {"updated": 0, "unread_count": 0}
    assert await _read_at(test_session, ajena_1) is None
    assert await _read_at(test_session, ajena_2) is None

    listado_a = await client.get("/notifications", headers=auth_headers(token_a))
    assert listado_a.json()["unread_count"] == 2
    todas_a = await client.post(
        "/notifications/read-all", headers=auth_headers(token_a)
    )
    assert todas_a.json() == {"updated": 2, "unread_count": 0}
    assert await _read_at(test_session, ajena_1) is not None
