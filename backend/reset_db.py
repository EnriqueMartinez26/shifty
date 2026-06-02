#!/usr/bin/env python3
import sqlalchemy as sa
from sqlalchemy import text
import time

# Conectar a PostgreSQL (sin especificar BD para poder dropar la BD)
engine = sa.create_engine("postgresql://postgres:postgres@localhost/postgres", echo=False, isolation_level="AUTOCOMMIT")

with engine.connect() as conn:
    # Cerrar todas las conexiones a la BD shifty
    conn.execute(text("SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = 'shifty' AND pid <> pg_backend_pid();"))
    time.sleep(1)
    
    # Dropar BD (sin CASCADE, PostgreSQL no soporta)
    try:
        conn.execute(text("DROP DATABASE IF EXISTS shifty;"))
        print("✅ BD shifty eliminada")
    except Exception as e:
        print(f"⚠️ Error al dropar: {e}")
    
    time.sleep(1)
    
    # Crear BD nueva
    conn.execute(text("CREATE DATABASE shifty;"))
    print("✅ BD shifty creada (vacía)")

engine.dispose()
print("✅ Limpieza completada - BD lista para migraciones")
