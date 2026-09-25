"""audit_logs: quitar el texto de las notas del profesional (L3-02, PV-10)

2026-09-25, auditoria de datos de terceros (L3-02). ``update_staff_notes``
copiaba el texto completo de ``notes_staff`` (notas del tipo "nota
clinica", hasta 1000 caracteres) a ``payload_before``/``payload_after`` de
``audit_logs``, una tabla que no se purga y que leen ``/reports/audit-logs`` y
el superadmin. El codigo ya audita solo el hecho
(``{"notes_staff_changed": true, "notes_staff_length": n}``); esta migracion
deja las filas viejas con esa misma forma. Recortar la tabla, que por lo
demas es inmutable, es decision de Mateo (auditoria legal, 2026-09-25): la IA
no decide destruccion de datos (CLAUDE.md §1). Todavia no hay datos de
produccion.

Solo migracion de datos, sin cambio de esquema. Toca unicamente filas de
``Appointment`` con accion ``update`` cuyo payload tiene la clave
``notes_staff`` (el unico lugar que la escribia); ninguna fila se borra.
Por lotes con clave por id (``LOTE`` filas por lectura), filtrados por
``resource_type`` (indexado). En Postgres corre en ``autocommit_block``: cada
UPDATE se confirma solo. ``audit_logs`` esta fuera de RLS
(``c3d4e5f6a7b8``), asi que no hace falta el bypass. Idempotente e informa
la cantidad de filas recortadas en el log de alembic.

El downgrade no hace nada: el esquema no cambio y el texto no se puede
restaurar (el codigo anterior lee estas filas igual; solo las muestra).

Revision ID: c7e9a1b3d5f7
Revises: b5d7f9a1c3e6
Create Date: 2026-09-25
"""

import json
import logging
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e9a1b3d5f7"
down_revision: Union[str, Sequence[str], None] = "b5d7f9a1c3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

LOTE = 500
CLAVE = "notes_staff"

audit_logs = sa.table(
    "audit_logs",
    sa.column("id", sa.Integer()),
    sa.column("resource_type", sa.String()),
    sa.column("action", sa.String()),
    sa.column("payload_before", sa.JSON(none_as_null=True)),
    sa.column("payload_after", sa.JSON(none_as_null=True)),
)


def _como_dict(valor: Any) -> Any:
    # Postgres devuelve el JSON ya decodificado; SQLite (tests) el texto.
    return json.loads(valor) if isinstance(valor, str) else valor


def _sin_texto(payload: Any) -> Any:
    """La marca y el largo en lugar del texto; lo demas, igual."""
    if not isinstance(payload, dict) or CLAVE not in payload:
        return payload
    texto = payload[CLAVE]
    largo = len(texto) if isinstance(texto, str) else 0
    return {"notes_staff_changed": True, "notes_staff_length": largo}


def recortar_notas(bind: sa.Connection, *, lote: int = LOTE) -> int:
    """Recorta las filas por lotes; devuelve cuantas cambio."""
    cambiadas = 0
    ultimo = 0
    while True:
        filas = bind.execute(
            sa.select(
                audit_logs.c.id,
                audit_logs.c.payload_before,
                audit_logs.c.payload_after,
            )
            .where(
                audit_logs.c.resource_type == "Appointment",
                audit_logs.c.action == "update",
                audit_logs.c.id > ultimo,
            )
            .order_by(audit_logs.c.id)
            .limit(lote)
        ).all()
        if not filas:
            return cambiadas
        for id_, crudo_antes, crudo_despues in filas:
            antes, despues = _como_dict(crudo_antes), _como_dict(crudo_despues)
            nuevo_antes, nuevo_despues = _sin_texto(antes), _sin_texto(despues)
            if (nuevo_antes, nuevo_despues) != (antes, despues):
                bind.execute(
                    sa.update(audit_logs)
                    .where(audit_logs.c.id == id_)
                    .values(payload_before=nuevo_antes, payload_after=nuevo_despues)
                )
                cambiadas += 1
        ultimo = int(filas[-1][0])


def upgrade() -> None:
    # Offline (``--sql``) no hay filas que leer: el recorte es solo online.
    if op.get_context().as_sql:
        return
    if op.get_bind().dialect.name != "postgresql":
        cambiadas = recortar_notas(op.get_bind())
    else:
        with op.get_context().autocommit_block():
            cambiadas = recortar_notas(op.get_bind())
    logger.info("audit_logs: texto de notas quitado en %s fila(s)", cambiadas)


def downgrade() -> None:
    # Sin cambio de esquema y sin texto que restaurar (ver docstring).
    pass
