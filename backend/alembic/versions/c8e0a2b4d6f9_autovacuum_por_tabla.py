"""autovacuum afinado por tabla (F1-16, R7-07)

Con los valores por defecto (VACUUM al 20 % de filas muertas) una tabla de un
millon de turnos esperaba 200.000 UPDATE para limpiarse, y el outbox y el inbox
-que se insertan y se marcan procesados todo el tiempo- acumulaban bloat entre
corridas, justo donde el lote de cada minuto busca pendientes.

- ``appointments``: VACUUM al 5 %, ANALYZE al 2 % (los planes de solapamiento y
  agenda dependen de estadisticas frescas de ``starts_at``).
- ``outbox_messages`` y ``webhook_inbox``: VACUUM al 1 % con umbral de 500, y
  por inserciones al 5 % (marca las paginas como visibles para los index-only
  scan de los pendientes).
- ``notifications`` y ``audit_logs``: casi solo inserciones, VACUUM por
  inserciones al 5 %.

``ALTER TABLE ... SET`` de parametros de autovacuum toma ``SHARE UPDATE
EXCLUSIVE``: no frena lecturas ni escrituras. El downgrade los resetea al valor
global.

Revision ID: c8e0a2b4d6f9
Revises: b7d9f1a3c5e8
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c8e0a2b4d6f9"
down_revision: Union[str, Sequence[str], None] = "b7d9f1a3c5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLAS = {
    "autovacuum_vacuum_scale_factor": "0.01",
    "autovacuum_vacuum_threshold": "500",
    "autovacuum_vacuum_insert_scale_factor": "0.05",
}
_SOLO_INSERCIONES = {"autovacuum_vacuum_insert_scale_factor": "0.05"}

PARAMETROS: dict[str, dict[str, str]] = {
    "appointments": {
        "autovacuum_vacuum_scale_factor": "0.05",
        "autovacuum_analyze_scale_factor": "0.02",
    },
    "outbox_messages": _COLAS,
    "webhook_inbox": _COLAS,
    "notifications": _SOLO_INSERCIONES,
    "audit_logs": _SOLO_INSERCIONES,
}


def upgrade() -> None:
    for tabla, parametros in PARAMETROS.items():
        valores = ", ".join(f"{clave} = {valor}" for clave, valor in parametros.items())
        op.execute(f"ALTER TABLE {tabla} SET ({valores})")


def downgrade() -> None:
    for tabla, parametros in PARAMETROS.items():
        op.execute(f"ALTER TABLE {tabla} RESET ({', '.join(parametros)})")
