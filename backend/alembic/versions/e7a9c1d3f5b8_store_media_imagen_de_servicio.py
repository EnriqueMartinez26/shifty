"""store_media: imagen de servicio y bytea sin comprimir (F1-28, F1-30)

R10-01: la CSP del front solo permite imagenes de ``'self'`` y
``services.image_url`` exigia una URL externa, asi que toda imagen de
servicio salia rota. La imagen de servicio pasa a subirse a ``store_media``
como el logo y la portada:

- ``kind`` gana el valor ``'service'`` y un ``CHECK`` con los tres valores
  (hasta ahora el tipo lo sostenia solo el router).
- ``service_id`` (nullable, FK a ``services`` con ``ON DELETE CASCADE``) y un
  ``CHECK`` que lo exige si y solo si ``kind = 'service'``.
- ``uq_store_media_service_id``: una imagen por servicio (dos subidas a la
  vez no dejan dos filas) y el indice de la FK. ``CONCURRENTLY`` dentro de
  ``autocommit_block``, con ``DROP ... IF EXISTS`` antes por si un intento
  cortado dejo un indice INVALID.

F1-30 (R10-07): ``data SET STORAGE EXTERNAL``. Con el default (EXTENDED)
TOAST intentaba comprimir cada imagen con pglz: PNG, JPEG y WebP ya vienen
comprimidos, asi que era CPU al escribir y al leer sin ahorro. EXTERNAL la
guarda fuera de linea sin comprimir. Solo cambia el catalogo (lock breve, sin
reescribir la tabla) y aplica a las filas nuevas; las existentes quedan como
estan hasta que se reemplazan.

Si hay filas con un ``kind`` fuera de ``logo``/``cover``, la migracion no las
corrige: se detiene con el conteo (mismo criterio que ``c3d5e7f9a1b4``).

El downgrade vuelve ``data`` a EXTENDED y quita el indice, los ``CHECK``, la
FK y la columna. NO borra las imagenes de servicio ya subidas: el codigo
anterior las sigue sirviendo por id y ``services.image_url`` las sigue
apuntando; solo se pierde el vinculo fila -> servicio.

Revision ID: e7a9c1d3f5b8
Revises: d4e6f8a0b2c5
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "e7a9c1d3f5b8"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a0b2c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICE = "uq_store_media_service_id"


def _kinds_desconocidos() -> int:
    if context.is_offline_mode():
        return 0
    consulta = "SELECT count(*) FROM store_media WHERE kind NOT IN ('logo', 'cover')"
    return int(op.get_bind().execute(sa.text(consulta)).scalar() or 0)


def upgrade() -> None:
    desconocidos = _kinds_desconocidos()
    if desconocidos:
        raise RuntimeError(
            f"{desconocidos} fila(s) de store_media con un kind distinto de "
            "logo/cover. Esta migracion no las corrige: revisarlas a mano y "
            "volver a correr `alembic upgrade head`."
        )
    op.add_column("store_media", sa.Column("service_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_store_media_service_id",
        "store_media",
        "services",
        ["service_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_store_media_kind", "store_media", "kind IN ('logo', 'cover', 'service')"
    )
    op.create_check_constraint(
        "ck_store_media_service_id",
        "store_media",
        "(kind = 'service') = (service_id IS NOT NULL)",
    )
    op.execute("ALTER TABLE store_media ALTER COLUMN data SET STORAGE EXTERNAL")
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY {INDICE} ON store_media (service_id) "
            "WHERE service_id IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
    op.execute("ALTER TABLE store_media ALTER COLUMN data SET STORAGE EXTENDED")
    op.drop_constraint("ck_store_media_service_id", "store_media", type_="check")
    op.drop_constraint("ck_store_media_kind", "store_media", type_="check")
    op.drop_constraint("fk_store_media_service_id", "store_media", type_="foreignkey")
    op.drop_column("store_media", "service_id")
