"""La vigencia de una promocion nunca queda como datetime sin zona.

2026-09-18, F11b-02 (parte backend): ``valid_from``/``valid_until`` de
``promotions/schemas.py`` aceptaban datetimes naive (el form manda el valor
crudo de un ``<input type="datetime-local">``, "2026-03-01T23:59"). Dos
sintomas:

- La columna es ``timestamptz`` y el service compara contra
  ``datetime.now(timezone.utc)``: el naive se guardaba como UTC por accidente.
- Un naive y un aware en la misma validacion (``valid_from >= valid_until``
  en el schema, o el payload del PATCH contra la fecha guardada, que Postgres
  devuelve con zona) levantaban ``TypeError`` -- no ``ValueError`` --, que
  pydantic no convierte en 422: salia un 500.

Tratamiento (2026-09-20, unificado con el fix del panel): un valor SIN offset
se rechaza con 422 en vez de suponerlo UTC -suponer una zona aca solo mueve la
adivinanza de lugar-, y con offset se lleva a UTC. La conversion desde hora
argentina es del front (``argentinaLocalToUtcIso``), que ahora manda siempre
el instante con zona.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from modules.promotions.schemas import PromotionCreate, PromotionUpdate

BASE: dict[str, object] = {"code": "VIGENCIA", "title": "Vigencia", "value": 10}
ART = timezone(timedelta(hours=-3))


@pytest.mark.parametrize("schema", [PromotionCreate, PromotionUpdate])
def test_una_vigencia_sin_offset_se_rechaza(
    schema: type[PromotionCreate] | type[PromotionUpdate],
) -> None:
    """Antes: se tomaba como UTC y la promo vencia tres horas antes."""
    datos = {
        **(BASE if schema is PromotionCreate else {}),
        "valid_until": "2026-03-01T23:59",
    }
    with pytest.raises(ValidationError, match="zona horaria"):
        schema.model_validate(datos)


def test_una_vigencia_con_offset_se_lleva_a_utc() -> None:
    promo = PromotionCreate.model_validate(
        {**BASE, "valid_until": "2026-03-01T23:59:00-03:00"}
    )
    assert promo.valid_until == datetime(2026, 3, 2, 2, 59, tzinfo=timezone.utc)
    assert promo.valid_until is not None
    assert promo.valid_until.utcoffset() == timedelta(0)


@pytest.mark.parametrize("schema", [PromotionCreate, PromotionUpdate])
def test_mezclar_naive_y_aware_no_revienta(
    schema: type[PromotionCreate] | type[PromotionUpdate],
) -> None:
    """Antes: TypeError (500) al comparar un naive con un aware. Ahora el
    naive se rechaza como ValueError (422) antes de llegar a la comparacion."""
    datos = {
        **(BASE if schema is PromotionCreate else {}),
        "valid_from": "2026-03-01T10:00",
        "valid_until": datetime(2026, 3, 1, 12, 0, tzinfo=ART).isoformat(),
    }
    with pytest.raises(ValidationError, match="zona horaria"):
        schema.model_validate(datos)


def test_el_patch_normaliza_igual_que_el_alta() -> None:
    cambio = PromotionUpdate.model_validate({"valid_until": "2026-03-01T23:59-03:00"})
    assert cambio.valid_until == datetime(2026, 3, 2, 2, 59, tzinfo=timezone.utc)
