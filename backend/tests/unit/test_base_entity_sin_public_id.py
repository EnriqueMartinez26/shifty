"""`BaseEntity` no declara `public_id`, y su archivo no lo discute.

2026-09-18 (audit B7-12). Sintoma: `core/models.py` tenia un comentario con
trabajo pendiente ("might need to keep it", "it's better to remove it from
BaseEntity") sobre una columna que ya NO esta en `BaseEntity`. El texto no
describia el codigo: invitaba a volver a agregarla o a buscar una migracion
que no hace falta.

La verdad vive en los modelos concretos y es la que fija este test:
`stores` y `services` tienen una columna `public_id` real; `appointments`,
`schedules`, `staff` y `users` exponen `public_id` como propiedad que
devuelve el `id`.
"""

from __future__ import annotations

from pathlib import Path

import core.models
from core.models import BaseEntity
from infrastructure.persistence.models.appointment import AppointmentModel
from infrastructure.persistence.models.user import UserModel
from modules.services.model import Service
from modules.stores.model import Store


def test_base_entity_no_declara_public_id() -> None:
    assert "public_id" not in BaseEntity.__annotations__


def test_core_models_no_arrastra_una_duda_de_esquema() -> None:
    """Un comentario que discute una columna que ya no esta es ruido."""
    fuente = Path(core.models.__file__).read_text(encoding="utf-8")

    assert "public_id" not in fuente


def test_stores_y_services_tienen_columna_public_id() -> None:
    for modelo in (Store, Service):
        assert "public_id" in modelo.__table__.columns.keys(), modelo.__name__


def test_el_resto_expone_public_id_como_alias_del_id() -> None:
    for modelo in (AppointmentModel, UserModel):
        assert "public_id" not in modelo.__table__.columns.keys(), modelo.__name__
        assert isinstance(modelo.__dict__["public_id"], property), modelo.__name__
