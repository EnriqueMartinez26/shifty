"""La guarda del ultimo SuperAdmin pide el lock ANTES de contar (regla 4).

AUD2-B3-12, 2026-09-20. Sintoma: las dos guardas de "ultimo SuperAdmin activo"
contaban con un ``SELECT count(*)`` y actuaban despues, sin ``FOR UPDATE`` ni
ninguna restriccion en la base que lo sostuviera. Con dos SuperAdmin activos y
dos requests concurrentes (A revoca a B, B revoca a A) los dos leian 2, los dos
pasaban la guarda y quedaban CERO: la plataforma se recupera solo con acceso al
servidor (``scripts/bootstrap_superadmin.py``). Es el "verificar y luego actuar"
que la regla 4 prohibe, aplicado a la ultima llave de la plataforma.

Por que este test y no uno de rafaga: toda la suite de integracion corre en
SQLite, donde ``FOR UPDATE`` se ignora en silencio y dos escrituras nunca son
concurrentes de verdad (§4 de CLAUDE.md). Una rafaga en SQLite estaria verde
con el lock y sin el, o sea que no probaria nada. La rafaga real vive en
``tests/postgres/test_pg_ultimo_superadmin_concurrente.py``; lo que se puede
afirmar de forma determinista y barata en cualquier motor es que la consulta
que emite la guarda LLEVA el ``FOR UPDATE``, y eso es lo que se afirma aca
compilando el statement contra el dialecto de PostgreSQL.
"""

from typing import Any, cast

from sqlalchemy.dialects import postgresql

from modules.users.guards import active_global_admins_locked


def test_la_consulta_de_la_guarda_pide_for_update() -> None:
    # Se compila contra el dialecto de PostgreSQL a proposito: el de SQLite es
    # justamente el que descarta el FOR UPDATE, asi que compilar con el motor
    # de la suite no probaria nada. `dialect` no lleva anotacion en SQLAlchemy.
    dialecto = cast(Any, postgresql.dialect)()
    sql = str(active_global_admins_locked().compile(dialect=dialecto)).upper()

    assert "FOR UPDATE" in sql, (
        "la guarda del ultimo SuperAdmin volvio a contar sin tomar el lock: "
        "dos revocaciones simultaneas pasan las dos y dejan cero SuperAdmin"
    )
    # Y bloquea solo a los candidatos, no a la tabla entera de usuarios: la
    # baja de un cliente de cualquier tienda no se serializa contra esto.
    assert "IS_GLOBAL_ADMIN" in sql and "IS_ACTIVE" in sql
