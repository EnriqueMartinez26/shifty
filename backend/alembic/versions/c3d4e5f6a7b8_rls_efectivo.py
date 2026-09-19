"""hacer efectivo el Row-Level Security

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-27

El aislamiento entre tiendas dependia por completo de los filtros ``store_id``
del codigo: las politicas de RLS existian pero no filtraban nada, porque el rol
con el que se conecta la aplicacion es superusuario con BYPASSRLS.

Esta migracion cierra las dos mitades del problema:

1. Crea ``shifty_app``, un rol sin superusuario y sin BYPASSRLS, con permisos
   solo de datos. La aplicacion se conecta con este; las migraciones siguen
   corriendo con el dueno porque necesitan DDL y CREATE EXTENSION.
2. Agrega las politicas que faltaban en appointment_blocks, store_schedules y
   notifications, y habilita RLS donde no estaba.

``audit_logs`` queda deliberadamente fuera: es global por diseno y la consulta
el panel de superadministracion, que necesita ver todas las tiendas.
"""

import os
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "shifty_app"

# Tablas con store_id a las que les faltaba la politica.
TABLAS_SIN_POLITICA = ("appointment_blocks", "store_schedules", "notifications")

# Misma forma que las politicas ya existentes: el admin global ve todo, el
# resto solo su tienda.
_POLITICA = """
CREATE POLICY {tabla}_rls_policy ON {tabla}
USING (
    current_setting('app.is_global_admin', true) = 'true'
    OR store_id::text = current_setting('app.current_store_id', true)
)
"""


def _literal_sql(valor: str) -> str:
    """Literal SQL con la semantica de quote_literal de Postgres.

    El DDL no acepta parametros ligados, asi que la contrasena va como literal:
    la comilla simple se duplica y, si hay barras invertidas, se usa E'' con la
    barra duplicada. Asi el resultado no depende de standard_conforming_strings.
    """
    escapado = valor.replace("'", "''")
    if "\\" in valor:
        literal = "E'" + escapado.replace("\\", "\\\\") + "'"
    else:
        literal = "'" + escapado + "'"
    # op.execute(str) pasa por sqlalchemy.text(), que toma `:palabra` como
    # parametro ligado y desescapa `\:`. Escapar cada `:` hace que Postgres
    # reciba exactamente el literal de arriba. (`%` ya lo maneja text().)
    return literal.replace(":", "\\:")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Sin default (C-02, 2026-09-19): antes caia en una contrasena publicada en
    # el repo y un despliegue sin la variable creaba el rol con ella. Falla
    # cerrada, antes de emitir DDL (reglas 17 y 21).
    password = os.environ.get("APP_DB_PASSWORD", "").strip()
    if not password:
        raise RuntimeError(
            "Falta APP_DB_PASSWORD: es la contrasena con la que se crea el rol "
            f"{APP_ROLE}. Definila en el entorno de la migracion (en desarrollo, "
            "en el .env de la raiz; generala con `openssl rand -hex 32`)."
        )
    # NUL y caracteres de control no tienen representacion segura en el
    # literal; "$$" cerraria el bloque DO de abajo antes de tiempo.
    if any(ord(c) < 32 or ord(c) == 127 for c in password) or "$$" in password:
        raise RuntimeError(
            'APP_DB_PASSWORD contiene caracteres de control o "$$": no se puede '
            f"usar como contrasena del rol {APP_ROLE}. Genera otra con "
            "`openssl rand -hex 32`."
        )

    # El rol se crea solo si no existe, para que la migracion sea reejecutable.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD {_literal_sql(password)}
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    # Aunque exista de antes, nos aseguramos de que no pueda saltear RLS.
    op.execute(f"ALTER ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        f"TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # Las tablas que se creen mas adelante heredan estos permisos.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    for tabla in TABLAS_SIN_POLITICA:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {tabla}_rls_policy ON {tabla}")
        op.execute(_POLITICA.format(tabla=tabla))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for tabla in TABLAS_SIN_POLITICA:
        op.execute(f"DROP POLICY IF EXISTS {tabla}_rls_policy ON {tabla}")
        op.execute(f"ALTER TABLE {tabla} NO FORCE ROW LEVEL SECURITY")

    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    # El rol no se elimina: puede tener sesiones abiertas o ser reutilizado.
