"""La API no hace DDL al arrancar: el esquema es de las migraciones (B7-07/X-18).

2026-09-19. Sintoma: `core/runtime_contracts.py` (`ensure_runtime_contracts`)
agregaba columnas con `ALTER TABLE` y corria `Base.metadata.create_all` desde
el lifespan de la API, con una segunda lista de modelos escrita a mano e
incompleta. Estaba detras de `RUN_RUNTIME_CONTRACTS_ON_STARTUP`, en `false` en
todos los entornos versionados: codigo que no corria en ningun lado pero que,
prendido, emitia DDL contra produccion con el rol de la app. Un `create_all`
tampoco crea la exclusion GiST `ex_appointments_no_active_overlap`, que solo
existe en la migracion.

El esquema lo definen `alembic/versions/**` (regla 13) y lo verifican el job
`contract-and-migrations` y `tests/postgres/`.
"""

from __future__ import annotations

import importlib.util

import main
from core.config import Settings


def test_no_existe_el_modulo_de_ddl_de_arranque() -> None:
    assert importlib.util.find_spec("core.runtime_contracts") is None


def test_el_lifespan_no_tiene_camino_de_ddl() -> None:
    assert not hasattr(main, "ensure_runtime_contracts")


def test_no_queda_el_flag_que_lo_prendia() -> None:
    assert "RUN_RUNTIME_CONTRACTS_ON_STARTUP" not in Settings.model_fields
