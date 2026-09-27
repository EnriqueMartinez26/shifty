"""2026-09-16 · C-04: `seed_simulation.py` imprimia la URL completa y saltaba RLS por rol.

Sintoma (a): la primera linea de salida era
`[CONN] Seeding database at: postgresql+asyncpg://shifty_user:S3cr3t@db:5432/db`,
usuario y contrasena incluidos.

Sintoma (b): el script no fijaba `set_tenant_context(None, True)` ni llamaba a
`_apply_tenant_context`, asi que solo escribia con un superusuario (BYPASSRLS).
Con la `DATABASE_URL` de compose (rol `shifty_app`, NOBYPASSRLS y FORCE ROW
LEVEL SECURITY) cada INSERT cae por el WITH CHECK y `cleanup_seed` no ve
filas. Los jobs de Celery y `bootstrap_superadmin.py` declaran ese bypass de
forma explicita; el seed tiene que hacer lo mismo.

No se toca ninguna base: el trabajo por tienda se reemplaza por registradores
y solo se observa el orden en que el script prepara la sesion.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core import database as core_database
from scripts import seed_simulation as seed

URL_CON_PASSWORD = "postgresql+asyncpg://shifty_user:S3cr3t@db:5432/shifty_db"


@pytest.mark.asyncio
async def test_seed_declara_bypass_de_rls_y_no_imprime_la_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    eventos: list[tuple[str, Any]] = []
    sesiones: list[AsyncSession] = []

    async def apply_registrado(session: AsyncSession) -> None:
        eventos.append(
            (
                "tenant_context",
                (
                    core_database._current_store_id.get(),
                    core_database._is_global_admin.get(),
                    isinstance(session, core_database.TenantSession),
                ),
            )
        )
        sesiones.append(session)

    async def cleanup_registrado(session: AsyncSession) -> None:
        eventos.append(("cleanup_seed", None))
        sesiones.append(session)

    async def seed_store_registrado(
        session: AsyncSession, scenario: dict[str, Any]
    ) -> dict[str, Any]:
        eventos.append(("seed_store", scenario["slug"]))
        sesiones.append(session)
        return {
            "store": SimpleNamespace(id="01SEEDSTORE", name=scenario["name"]),
            "admin": None,
            "services": 0,
            "staff": 0,
            "clients": 0,
        }

    async def global_admin_registrado(
        session: AsyncSession, default_store_id: str
    ) -> None:
        eventos.append(("seed_global_admin", default_store_id))
        sesiones.append(session)

    async def summarize_registrado(session: AsyncSession) -> dict[str, int]:
        eventos.append(("summarize_counts", None))
        sesiones.append(session)
        return {}

    monkeypatch.setattr(seed, "DATABASE_URL", URL_CON_PASSWORD)
    monkeypatch.setattr(seed, "cleanup_seed", cleanup_registrado)
    monkeypatch.setattr(seed, "seed_store", seed_store_registrado)
    monkeypatch.setattr(seed, "seed_global_admin", global_admin_registrado)
    monkeypatch.setattr(seed, "summarize_counts", summarize_registrado)
    # Se intercepta en core.database (lo usa TenantSession tras el commit) y en
    # el propio script, que antes del fix ni siquiera lo importaba.
    monkeypatch.setattr(core_database, "_apply_tenant_context", apply_registrado)
    monkeypatch.setattr(seed, "_apply_tenant_context", apply_registrado, raising=False)

    try:
        await seed.seed_simulation()
    finally:
        core_database.set_tenant_context(None, False)

    salida = capsys.readouterr().out
    assert "S3cr3t" not in salida
    assert "shifty_user" not in salida
    assert "db:5432/shifty_db" in salida

    nombres = [nombre for nombre, _ in eventos]
    assert nombres == [
        "tenant_context",  # bypass explicito ANTES de la primera escritura
        "cleanup_seed",
        "seed_store",
        "seed_store",
        "seed_global_admin",
        "tenant_context",  # set_config(..., true) muere con el commit: se reaplica
        "summarize_counts",
    ]
    contextos = [detalle for nombre, detalle in eventos if nombre == "tenant_context"]
    assert contextos == [(None, True, True)] * 2, (
        "el seed debe correr como superadmin global (store_id=None, is_admin=True) "
        "sobre una TenantSession, igual que los jobs de Celery"
    )
    assert len({id(sesion) for sesion in sesiones}) == 1, (
        "el contexto se aplica sobre la misma sesion que escribe"
    )
