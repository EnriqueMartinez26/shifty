"""
Script alternativo de migración para Windows + Python 3.13.

USO:
    ..\\.venv\\Scripts\\python.exe run_migrations.py

Bypassa completamente Alembic CLI para evitar el UnicodeDecodeError de
psycopg2 en Windows con codificación regional española.
"""
import sys
import os

# Asegurar que el backend está en el path
sys.path.insert(0, os.path.dirname(__file__))

# Leer el .env manualmente ANTES de importar settings
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import re

def parse_db_url(url: str) -> dict:
    clean = re.sub(r"postgresql\+\w+://", "", url)
    if "?" in clean:
        clean = clean.split("?")[0]
    match = re.match(
        r"(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<dbname>.+)",
        clean,
    )
    if not match:
        raise ValueError(f"No se pudo parsear DATABASE_URL: {url}")
    return {
        "user": match.group("user"),
        "password": match.group("password"),
        "host": match.group("host"),
        "port": int(match.group("port") or 5432),
        "dbname": match.group("dbname"),
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
            sslmode="disable",
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
        from alembic.config import Config
        from alembic import command as alembic_command

        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "alembic"))
        alembic_command.upgrade(alembic_cfg, "head")
        print("OK: Migraciones aplicadas correctamente.")
    except Exception as e:
        print(f"ERROR: Error en migraciones: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
