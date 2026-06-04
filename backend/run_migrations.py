"""
Script alternativo de migración para Windows + Python 3.13.

USO:
    ..\\.venv\\Scripts\\python.exe run_migrations.py

Bypassa completamente Alembic CLI para evitar el UnicodeDecodeError de
psycopg2 en Windows con codificación regional española.
"""
import sys
import os
from urllib.parse import parse_qs, unquote, urlparse

backend_dir = os.path.dirname(__file__)
if sys.path and os.path.abspath(sys.path[0]) == os.path.abspath(backend_dir):
    sys.path.pop(0)
from alembic.config import Config
from alembic import command as alembic_command

# Asegurar que el backend está en el path
sys.path.insert(0, backend_dir)

# Leer el .env manualmente ANTES de importar settings
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

def parse_db_url(url: str) -> dict:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme != "postgresql" or not parsed.hostname or not parsed.path:
        raise ValueError(f"No se pudo parsear DATABASE_URL: {url}")
    query = parse_qs(parsed.query)
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "dbname": parsed.path.lstrip("/"),
        "sslmode": query.get("sslmode", ["require"])[0],
    }

def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL no está definida en el .env")
        sys.exit(1)

    params = parse_db_url(db_url)
    print(f"Conectando a PostgreSQL en {params['host']}:{params['port']}/{params['dbname']} ...")

    try:
        import psycopg2
        # Conectar usando parámetros de keyword (sin DSN string)
        conn = psycopg2.connect(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            dbname=params["dbname"],
            sslmode=params["sslmode"],
            options="-c client_encoding=UTF8",
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"OK: Conexión exitosa: {version[0]}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"ERROR: Error de conexión: {e}")
        sys.exit(1)

    # Ahora correr Alembic programáticamente
    print("\nEjecutando migraciones de Alembic...")
    try:
        alembic_cfg = Config(os.path.join(backend_dir, "alembic.ini"))
        alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
        alembic_command.upgrade(alembic_cfg, "head")
        print("OK: Migraciones aplicadas correctamente.")
    except Exception as e:
        print(f"ERROR: Error en migraciones: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
