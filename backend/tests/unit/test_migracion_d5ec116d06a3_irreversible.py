"""C-03 (2026-09-18): el downgrade de `d5ec116d06a3` es irreversible y lo dice.

Sintoma: `downgrade()` era `pass`. `alembic downgrade 82f93e683770` salia con
0 sin revertir nada: dejaba el esquema inconsistente y el upgrade siguiente
volvia a correr los ALTER TYPE. La migracion convierte a VARCHAR los ids
bigint de seis tablas (hoy son ULID: el cast de vuelta a BIGINT falla con
cualquier fila) y borra columnas con datos que no se pueden reconstruir
(users.hashed_password, users.is_global_admin, staff_blocks...). No hay
inverso real con datos: el downgrade levanta un error explicito que remite
al runbook de backup, antes de emitir una sola operacion.

Test sin base: se reemplaza `op` por un mock que registra cada llamada.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRACION = (
    BACKEND_ROOT / "alembic" / "versions" / "d5ec116d06a3_refactor_backend_v2.py"
)


def _cargar_migracion() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migracion_d5ec116d06a3", MIGRACION)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_el_downgrade_levanta_un_error_explicito_sin_tocar_el_esquema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migracion = _cargar_migracion()
    op_simulado = MagicMock()
    monkeypatch.setattr(migracion, "op", op_simulado)

    with pytest.raises(NotImplementedError) as error:
        migracion.downgrade()

    mensaje = str(error.value)
    assert "d5ec116d06a3" in mensaje
    assert "ULID" in mensaje
    assert "users.hashed_password" in mensaje
    assert "staff_blocks" in mensaje
    assert "docs/BACKUP_RESTORE_RUNBOOK.md" in mensaje
    # Ninguna operacion antes del error: un downgrade a medias es peor que uno
    # que no arranca.
    assert op_simulado.mock_calls == []


def test_el_upgrade_y_la_identidad_de_la_revision_no_cambian() -> None:
    migracion = _cargar_migracion()
    assert migracion.revision == "d5ec116d06a3"
    assert migracion.down_revision == "82f93e683770"
