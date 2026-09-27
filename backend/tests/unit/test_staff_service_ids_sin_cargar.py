"""``Staff.service_ids`` no esconde una coleccion sin cargar (F3-01).

Con ``Staff.services`` en ``lazy="raise"``, la propiedad leia
``self.__dict__.get("services")`` y devolvia ``[]`` si nadie habia cargado la
coleccion: un profesional con servicios aparecia sin ninguno, sin error. Un
``Staff`` que ya existe en la base (tiene identidad) y no trae ni la coleccion
ni la lista explicita tiene que fallar fuerte.
"""

from typing import cast

import pytest
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

from modules.services.model import Service
from modules.staff.model import Staff
from modules.staff.repository import StaffRepository


def _staff_de_la_base() -> Staff:
    """Un Staff con identidad (como leido de la base) sin cargar ``services``."""
    staff = Staff(id="st-1", store_id="store-1", display_name="Ana")
    make_transient_to_detached(staff)
    return staff


def test_un_staff_de_la_base_sin_servicios_cargados_falla_fuerte() -> None:
    staff = _staff_de_la_base()

    with pytest.raises(InvalidRequestError, match="selectinload"):
        _ = staff.service_ids


def test_la_lista_explicita_sigue_valiendo_sin_la_coleccion() -> None:
    staff = _staff_de_la_base()
    staff.service_ids = ["svc-a", "svc-b"]

    assert staff.service_ids == ["svc-a", "svc-b"]


def test_la_coleccion_cargada_manda() -> None:
    staff = Staff(id="st-2", store_id="store-1", display_name="Bea")
    staff.services = [Service(public_id="svc-c", store_id="store-1", name="Corte")]

    assert staff.service_ids == ["svc-c"]


def test_un_staff_nuevo_sin_servicios_no_tiene_ninguno() -> None:
    staff = Staff(id="st-3", store_id="store-1", display_name="Cris")

    assert staff.service_ids == []


@pytest.mark.asyncio
async def test_reasignar_servicios_exige_la_coleccion_cargada() -> None:
    """``_set_services`` corta antes de tocar la base si ``services`` no vino."""
    repo = StaffRepository(cast(AsyncSession, None))

    with pytest.raises(RuntimeError, match="get_by_id"):
        await repo._set_services(_staff_de_la_base(), [])
