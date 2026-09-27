"""2026-09-17 · C-05: el bloque `[CREDENTIALS]` del seed no dice la verdad.

Sintoma original: `_seed_password` genera (o toma de `SEED_PASSWORD_*`) la
contrasena real de cada rol y la guarda en `PASSWORDS`; al final el script
imprimia `global123` / `admin123` / `staff123` / `client123`, literales que no
coinciden con nada. El operador probaba `admin123` y fallaba, o peor, las
tomaba como contrasenas vigentes de staging.

Sintoma del primer arreglo (revision 2026-09-18): imprimir `PASSWORDS` tal cual
filtraba a los logs las contrasenas de `SEED_PASSWORD_*`, que antes nunca
salian -- la misma fuga que cerro C-04 --, y repetia las generadas contra el
"se imprimen una unica vez" de `_seed_password`. Decision: el bloque dice de
DONDE sale cada contrasena y nunca el valor; la generada se imprime una sola
vez, al generarse.

No se toca ninguna base: se reemplaza el trabajo por tienda por registradores
(mismo esquema que el test de C-04) y solo se lee la salida.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core import database as core_database
from scripts import seed_simulation as seed

URL = "postgresql+asyncpg://shifty_app:pw@db:5432/shifty_db"
CREDENCIALES_INVENTADAS = ("global123", "admin123", "staff123", "client123")

# Dos roles con contrasena del entorno y dos generadas.
PASSWORDS_DE_PRUEBA = {
    "global_admin": "generada-global-Xq7",
    "admin": "valor-del-entorno-admin-Zk9",
    "staff": "generada-staff-Wm2",
    "client": "valor-del-entorno-client-Jp4",
}
ROLES_DEL_ENTORNO = {"admin", "client"}


async def _correr_seed_sin_base(monkeypatch: pytest.MonkeyPatch) -> None:
    async def nada(session: AsyncSession, *args: Any) -> Any:
        return None

    async def seed_store_falso(
        session: AsyncSession, scenario: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "store": SimpleNamespace(id="01SEEDSTORE", name=scenario["name"]),
            "admin": None,
            "services": 0,
            "staff": 0,
            "clients": 0,
        }

    async def resumen_vacio(session: AsyncSession) -> dict[str, int]:
        return {}

    monkeypatch.setattr(seed, "DATABASE_URL", URL)
    monkeypatch.setattr(seed, "cleanup_seed", nada)
    monkeypatch.setattr(seed, "seed_store", seed_store_falso)
    monkeypatch.setattr(seed, "seed_global_admin", nada)
    monkeypatch.setattr(seed, "summarize_counts", resumen_vacio)
    monkeypatch.setattr(core_database, "_apply_tenant_context", nada)
    monkeypatch.setattr(seed, "_apply_tenant_context", nada, raising=False)
    monkeypatch.setattr(seed, "PASSWORDS", dict(PASSWORDS_DE_PRUEBA))
    monkeypatch.setattr(seed, "PASSWORDS_DEL_ENTORNO", set(ROLES_DEL_ENTORNO))

    try:
        await seed.seed_simulation()
    finally:
        core_database.set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_el_bloque_credentials_nombra_el_origen_sin_imprimir_valores(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    await _correr_seed_sin_base(monkeypatch)

    salida = capsys.readouterr().out
    bloque = salida.split("[CREDENTIALS]", 1)[1]

    for inventada in CREDENCIALES_INVENTADAS:
        assert inventada not in bloque, f"credencial inexistente impresa: {inventada}"

    # Ningun valor sale en este tramo: las del entorno nunca, y las generadas
    # ya se imprimieron una vez al generarse.
    for rol, valor in PASSWORDS_DE_PRUEBA.items():
        assert valor not in salida, f"contrasena de {rol} impresa en el resumen"

    assert "admin@barberia-sentinel.com / (SEED_PASSWORD_ADMIN)" in bloque
    assert "admin@salon-sentinel.com / (SEED_PASSWORD_ADMIN)" in bloque
    assert "(SEED_PASSWORD_CLIENT)" in bloque
    assert (
        "global-admin@shifty.com / (generada: ver '[seed] password global_admin' arriba)"
        in bloque
    )
    assert "(generada: ver '[seed] password staff' arriba)" in bloque


def test_la_contrasena_del_entorno_nunca_se_imprime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SEED_PASSWORD_ADMIN", "valor-del-entorno-que-no-se-ve")
    monkeypatch.setattr(seed, "PASSWORDS_DEL_ENTORNO", set())

    valor = seed._seed_password("admin")

    assert valor == "valor-del-entorno-que-no-se-ve"
    assert "valor-del-entorno-que-no-se-ve" not in capsys.readouterr().out
    assert "admin" in seed.PASSWORDS_DEL_ENTORNO


def test_la_contrasena_generada_se_imprime_una_unica_vez(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SEED_PASSWORD_STAFF", raising=False)
    monkeypatch.setattr(seed, "PASSWORDS_DEL_ENTORNO", set())

    valor = seed._seed_password("staff")

    assert capsys.readouterr().out.count(valor) == 1
    assert "staff" not in seed.PASSWORDS_DEL_ENTORNO
