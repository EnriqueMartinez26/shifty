"""Una sola base declarativa en todo el backend (X-14, 2026-09-18).

Sintoma: `core/database.py` declaraba una segunda `class Base(DeclarativeBase)`
que ningun modelo usaba. Con dos `Base` importables desde `core/`, heredar de
la equivocada crea una tabla que Alembic (`alembic/env.py` usa
`core.models.Base.metadata`) y los `create_all` de los tests no ven.

La base real es `core.models.Base`; este test fija que sea la unica y que
todo modelo registrado cuelgue de ella.
"""

from __future__ import annotations

import core.database
from core.model_registry import load_all_models
from core.models import Base


def test_core_database_no_expone_otra_base() -> None:
    assert not hasattr(core.database, "Base")


def test_todos_los_modelos_cuelgan_de_la_base_de_core_models() -> None:
    load_all_models()

    tablas = list(Base.metadata.tables.values())
    assert tablas, "el registro no cargo ningun modelo"
    for mapper in Base.registry.mappers:
        # Por identidad: `==` entre tablas arma una expresion SQL, no un bool.
        assert any(mapper.local_table is tabla for tabla in tablas), (
            mapper.class_.__name__
        )
