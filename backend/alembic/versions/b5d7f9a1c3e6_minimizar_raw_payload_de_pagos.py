"""payments.raw_payload: recortar lo historico a la lista blanca de MP (L3-01)

2026-09-25, auditoria de datos de terceros (L3-01) y PV-14. La conciliacion
guardaba el recurso completo del pago de Mercado Pago (email, nombre,
identificacion y telefono del pagador, titular y digitos de la tarjeta, IP) y
la creacion del link guardaba la preferencia con ``payer`` e ``items``. El
codigo ya guarda solo la lista blanca (``modules/payments/minimization.py``);
esta migracion recorta las filas escritas antes.

Solo migracion de datos, sin cambio de esquema. Que se recorta:

- payload con ``data`` (webhook o conciliacion): claves de primer nivel de la
  notificacion y, dentro de ``data``, las que lee el webhook;
- respuesta de la preferencia (``init_point``, ``payer``, ``items``, sin
  ``data``): el id y los links.

Lo demas no viene de MP y no se toca: el motivo del vencimiento
(``reason``/``released_by``), la nota de la confirmacion manual y los datos
del reembolso. Las listas estan COPIADAS del modulo a proposito: una
migracion no puede cambiar de comportamiento cuando cambia el codigo.

Por lotes con clave por id (``LOTE`` filas por lectura) y, en Postgres, en
``autocommit_block``: cada UPDATE se confirma solo, asi que no hay un lock
largo sobre ``payments`` mientras el codigo viejo sigue sirviendo. RLS esta
forzada en ``payments``: el bypass se fija a nivel de sesion (en autocommit
un ``set_config(..., true)`` duraria una sola sentencia) y se apaga al final.
Idempotente: una segunda corrida no encuentra nada que recortar. Informa la
cantidad de filas recortadas en el log de alembic.

El downgrade no hace nada: el esquema no cambio y lo borrado no se puede
restaurar (el codigo anterior funciona igual con el payload recortado:
ningun lector usaba esos datos). Si hace falta el original, esta en el
recurso de MP (``GET /v1/payments/{id}``) o en un backup.

Revision ID: b5d7f9a1c3e6
Revises: a3c5e7f9b1d2
Create Date: 2026-09-25
"""

import json
import logging
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5d7f9a1c3e6"
down_revision: Union[str, Sequence[str], None] = "a3c5e7f9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

LOTE = 500

NOTIFICATION_FIELDS = (
    "id",
    "type",
    "action",
    "topic",
    "resource",
    "api_version",
    "live_mode",
    "date_created",
    "user_id",
    "status",
    "external_reference",
    "payment_id",
    "appointment_id",
)
PAYMENT_DATA_FIELDS = (
    "id",
    "status",
    "external_reference",
    "metadata",
    "date_approved",
    "transaction_amount",
    "currency_id",
    "collector_id",
    "live_mode",
    "preference_id",
)
METADATA_FIELDS = ("appointment_id", "store_id", "store_public_id", "payment_id")
PREFERENCE_FIELDS = ("id", "init_point", "sandbox_init_point", "external_reference")
# Una respuesta de preferencia se reconoce por cualquiera de estas claves.
PREFERENCE_MARKERS = ("init_point", "sandbox_init_point", "payer", "items")

_ESCALARES = (str, int, float, bool, type(None))

payments = sa.table(
    "payments", sa.column("id", sa.String()), sa.column("raw_payload", sa.JSON())
)


def _escalares(origen: dict[str, Any], claves: tuple[str, ...]) -> dict[str, Any]:
    return {
        k: origen[k]
        for k in claves
        if k in origen and isinstance(origen[k], _ESCALARES)
    }


def recortar(payload: Any) -> Any:
    """El payload recortado, o el mismo si no vino de MP."""
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if isinstance(data, dict):
        resultado = _escalares(payload, NOTIFICATION_FIELDS)
        minimo = _escalares(data, PAYMENT_DATA_FIELDS)
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            minimo["metadata"] = _escalares(metadata, METADATA_FIELDS)
        resultado["data"] = minimo
        return resultado
    if any(marca in payload for marca in PREFERENCE_MARKERS):
        return _escalares(payload, PREFERENCE_FIELDS)
    return payload


def _como_dict(valor: Any) -> Any:
    # Postgres devuelve el JSON ya decodificado; SQLite (tests) puede devolver
    # el texto.
    return json.loads(valor) if isinstance(valor, str) else valor


def minimizar(bind: sa.Connection, *, lote: int = LOTE) -> int:
    """Recorta todas las filas por lotes; devuelve cuantas cambio."""
    cambiadas = 0
    ultimo = ""
    while True:
        filas = bind.execute(
            sa.select(payments.c.id, payments.c.raw_payload)
            .where(payments.c.raw_payload.is_not(None), payments.c.id > ultimo)
            .order_by(payments.c.id)
            .limit(lote)
        ).all()
        if not filas:
            return cambiadas
        for id_, crudo in filas:
            actual = _como_dict(crudo)
            nuevo = recortar(actual)
            if nuevo != actual:
                bind.execute(
                    sa.update(payments)
                    .where(payments.c.id == id_)
                    .values(raw_payload=nuevo)
                )
                cambiadas += 1
        ultimo = filas[-1][0]


def upgrade() -> None:
    # Offline (``--sql``) no hay filas que leer: el recorte es solo online.
    if op.get_context().as_sql:
        return
    if op.get_bind().dialect.name != "postgresql":
        cambiadas = minimizar(op.get_bind())
    else:
        with op.get_context().autocommit_block():
            bind = op.get_bind()
            bind.execute(
                sa.text("SELECT set_config('app.is_global_admin', 'true', false)")
            )
            try:
                cambiadas = minimizar(bind)
            finally:
                bind.execute(
                    sa.text("SELECT set_config('app.is_global_admin', 'false', false)")
                )
    logger.info("payments.raw_payload recortado en %s fila(s)", cambiadas)


def downgrade() -> None:
    # Sin cambio de esquema y sin datos que restaurar (ver docstring).
    pass
