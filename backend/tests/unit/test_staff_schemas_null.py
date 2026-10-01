"""M2 (2026-09-30): PATCH .../schedules/{sid} con start_time null respondia 500, None >= time.

``ScheduleUpdate`` rechaza un null explicito en sus tres columnas NOT NULL;
un campo ausente sigue siendo "no cambiar".
"""

from datetime import time

import pytest
from pydantic import ValidationError

from modules.staff.schemas import ScheduleUpdate


@pytest.mark.parametrize("campo", ["day_of_week", "start_time", "end_time"])
def test_null_explicito_se_rechaza(campo: str) -> None:
    with pytest.raises(ValidationError, match=f"{campo} no puede ser null"):
        ScheduleUpdate.model_validate({campo: None})


def test_cuerpo_vacio_no_marca_ningun_campo() -> None:
    datos = ScheduleUpdate.model_validate({})
    assert datos.model_dump(exclude_unset=True) == {}


def test_valores_validos_pasan() -> None:
    datos = ScheduleUpdate.model_validate(
        {"day_of_week": 2, "start_time": "09:00:00", "end_time": "18:00:00"}
    )
    assert datos.model_dump(exclude_unset=True) == {
        "day_of_week": 2,
        "start_time": time(9, 0),
        "end_time": time(18, 0),
    }


def test_campo_ausente_no_se_confunde_con_null() -> None:
    datos = ScheduleUpdate.model_validate({"end_time": "12:00:00"})
    assert datos.model_dump(exclude_unset=True) == {"end_time": time(12, 0)}
