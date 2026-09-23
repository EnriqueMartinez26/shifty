"""Rafaga sobre la ultima llave de la plataforma: no puede quedar en cero.

AUD2-B3-12, 2026-09-20. Sintoma: las guardas de la regla 14 ("nunca se
desactiva al ultimo SuperAdmin activo") contaban con un ``SELECT count(*)`` y
escribian a continuacion, sin ``FOR UPDATE`` ni restriccion en la base. Con dos
SuperAdmin activos y dos requests simultaneos -- A baja a B, B baja a A -- los
dos leian 2, los dos pasaban la guarda y quedaban CERO SuperAdmin activos:
``/superadmin/*`` exige ``is_global_admin`` sobre un usuario activo, asi que la
plataforma se recuperaba solo con acceso al servidor
(``scripts/bootstrap_superadmin.py``). Es el "verificar y luego actuar" que la
regla 4 prohibe.

Solo Postgres lo prueba: en SQLite ``FOR UPDATE`` se ignora y las escrituras no
son concurrentes de verdad (§4 de CLAUDE.md). Cada operacion corre en su propia
sesion y las dos cargan las filas ANTES de que cualquiera tome el lock (una
barrera las alinea), que es el orden real del router.

Nota de ejecucion: este archivo se escribio junto al arreglo pero NO se corrio
(el lote no levanta contenedores). Lo corre el job ``backend-postgres`` de CI.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from core.exceptions import AppException
from modules.superadmin.repository import SuperAdminRepository
from modules.users.model import User
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

SLUGS = ("b312-pg-a", "b312-pg-b")
EMAILS = tuple(f"{slug}@demo.com" for slug in SLUGS)


@asynccontextmanager
async def _como_superadmin(session: AsyncSession) -> AsyncIterator[None]:
    """Contexto de superadmin, como el endpoint (get_current_global_admin)."""
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(session)
        yield
    finally:
        set_tenant_context(None, False)


async def _sembrar_dos_superadmin(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    for slug, email in zip(SLUGS, EMAILS):
        await seed_store_and_admin(sessions, slug=slug, email=email)
    async with sessions() as session:
        async with _como_superadmin(session):
            usuarios = (
                (await session.execute(select(User).where(User.email.in_(EMAILS))))
                .scalars()
                .all()
            )
            assert len(usuarios) == 2
            for usuario in usuarios:
                usuario.is_global_admin = True
            await session.commit()


async def _cargar(session: AsyncSession, email: str) -> User:
    return (await session.execute(select(User).where(User.email == email))).scalar_one()


async def _desactivar(
    sessions: async_sessionmaker[AsyncSession],
    actor_email: str,
    objetivo_email: str,
    barrera: asyncio.Barrier,
) -> str:
    """``PATCH /superadmin/users/{id}`` con ``is_active: false``, en paralelo."""
    async with sessions() as session:
        async with _como_superadmin(session):
            repo = SuperAdminRepository(session)
            actor = await _cargar(session, actor_email)
            objetivo = await _cargar(session, objetivo_email)
            # Como el router: las dos filas ya estan leidas antes del lock.
            await barrera.wait()
            try:
                await repo.users.update_user(objetivo, {"is_active": False}, actor)
            except AppException as exc:
                await session.rollback()
                return str(exc.error_code)
            return "ok"


async def _revocar(
    sessions: async_sessionmaker[AsyncSession],
    actor_email: str,
    objetivo_email: str,
    barrera: asyncio.Barrier,
) -> str:
    """``PATCH /superadmin/users/{id}/global-admin`` con ``false``."""
    async with sessions() as session:
        async with _como_superadmin(session):
            repo = SuperAdminRepository(session)
            actor = await _cargar(session, actor_email)
            objetivo = await _cargar(session, objetivo_email)
            await barrera.wait()
            try:
                await repo.users.set_global_admin(objetivo, False, actor)
            except AppException as exc:
                await session.rollback()
                return str(exc.error_code)
            return "ok"


async def _superadmin_activos(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        async with _como_superadmin(session):
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(User)
                        .where(
                            User.is_active.is_(True),
                            User.is_global_admin.is_(True),
                        )
                    )
                ).scalar_one()
            )


@pytest.mark.asyncio
async def test_dos_bajas_cruzadas_simultaneas_dejan_un_superadmin(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _sembrar_dos_superadmin(app_sessions)
    barrera = asyncio.Barrier(2)

    resultados = await asyncio.gather(
        _desactivar(app_sessions, EMAILS[0], EMAILS[1], barrera),
        _desactivar(app_sessions, EMAILS[1], EMAILS[0], barrera),
    )

    assert sorted(resultados) == ["LAST_SUPERADMIN_DEACTIVATION_DENIED", "ok"], (
        f"las dos bajas cruzadas pasaron: {resultados}"
    )
    assert await _superadmin_activos(app_sessions) == 1, (
        "la plataforma quedo sin ningun SuperAdmin activo"
    )


@pytest.mark.asyncio
async def test_dos_revocaciones_cruzadas_simultaneas_dejan_un_superadmin(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _sembrar_dos_superadmin(app_sessions)
    barrera = asyncio.Barrier(2)

    resultados = await asyncio.gather(
        _revocar(app_sessions, EMAILS[0], EMAILS[1], barrera),
        _revocar(app_sessions, EMAILS[1], EMAILS[0], barrera),
    )

    assert sorted(resultados) == ["LAST_SUPERADMIN_REVOCATION_DENIED", "ok"], (
        f"las dos revocaciones cruzadas pasaron: {resultados}"
    )
    assert await _superadmin_activos(app_sessions) == 1, (
        "la plataforma quedo sin ningun SuperAdmin activo"
    )
