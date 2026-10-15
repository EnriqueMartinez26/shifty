"""Adicionales: cotizacion pura y sena sobre el total (2026-10-14).

Decision de Mateo (2026-10-14): un adicional suma PRECIO, nunca tiempo, y la
sena porcentual se calcula sobre el total (servicio + adicionales). Decisiones
del coordinador a confirmar en la PR: (a) la promo baja solo el servicio y los
adicionales suman encima; (b) ``full`` cobra tambien los adicionales.

``services.addons.price_selection`` es la unica cotizacion: la usan el preview
de la sena y el alta publica. ``deposit_rules.decide_deposit`` no cambia: se le
pasa el total.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest

from modules.payments.deposit_rules import (
    UNKNOWN_HISTORY,
    DepositRules,
    decide_deposit,
)
from modules.services.addons import (
    NO_ADDONS,
    AddonChoice,
    AddonSelectionError,
    price_selection,
    snapshot_label,
)

SERVICIO = "svc-unas"


@dataclass
class _Adicional:
    id: str
    service_id: str
    name: str
    unit_price: Decimal
    max_quantity: int


@dataclass
class _Servicio:
    deposit_mode: str = "required"
    deposit_type: str = "percent"
    deposit_amount: Decimal | None = Decimal("30")


STRASS = _Adicional("add-strass", SERVICIO, "Strass", Decimal("500"), 10)
DISENO = _Adicional("add-diseno", SERVICIO, "Diseno", Decimal("1500.50"), 1)
DE_OTRO = _Adicional("add-otro", "svc-otro", "Brillo", Decimal("100"), 5)
CATALOGO = [STRASS, DISENO, DE_OTRO]


def _cotizar(*elegidos: tuple[str, int]) -> Decimal:
    return price_selection(
        CATALOGO, [AddonChoice(i, q) for i, q in elegidos], service_id=SERVICIO
    ).total


def _sena(servicio: _Servicio, total: Decimal, **reglas: int) -> Decimal:
    return decide_deposit(
        servicio,
        price=total,
        notice=timedelta(days=1),
        rules=DepositRules(**reglas),
        history=UNKNOWN_HISTORY,
    ).amount


# ---------------------------------------------------------------------------
# Cotizacion
# ---------------------------------------------------------------------------


def test_cotiza_cada_linea_y_suma_el_total() -> None:
    cotizacion = price_selection(
        CATALOGO,
        [AddonChoice("add-strass", 6), AddonChoice("add-diseno", 1)],
        service_id=SERVICIO,
    )

    assert [(x.addon_id, x.quantity, x.amount) for x in cotizacion.lines] == [
        ("add-strass", 6, Decimal("3000.00")),
        ("add-diseno", 1, Decimal("1500.50")),
    ]
    assert cotizacion.total == Decimal("4500.50")
    assert cotizacion.label() == "Strass x6, Diseno x1"
    # El snapshot lleva importes como texto y suma lo mismo que el total.
    snapshot = cotizacion.snapshot()
    assert snapshot is not None
    assert sum(Decimal(str(x["amount"])) for x in snapshot) == cotizacion.total
    assert snapshot[0] == {
        "addon_id": "add-strass",
        "name": "Strass",
        "unit_price": "500.00",
        "quantity": 6,
        "amount": "3000.00",
    }
    assert snapshot_label(snapshot) == "Strass x6, Diseno x1"


def test_sin_adicionales_el_total_es_cero_y_no_hay_snapshot() -> None:
    vacia = price_selection(CATALOGO, [], service_id=SERVICIO)

    assert vacia.total == Decimal("0.00") == NO_ADDONS.total
    assert vacia.snapshot() is None
    assert snapshot_label(None) == ""


@pytest.mark.parametrize(
    "elegidos",
    [
        pytest.param([("add-inexistente", 1)], id="desconocido"),
        pytest.param([("add-otro", 1)], id="de-otro-servicio"),
        pytest.param([("add-strass", 1), ("add-strass", 2)], id="repetido"),
        pytest.param([("add-strass", 11)], id="mas-que-el-maximo"),
        pytest.param([("add-diseno", 2)], id="maximo-uno"),
        pytest.param([("add-strass", 0)], id="cero"),
    ],
)
def test_rechaza_lo_que_no_es_del_catalogo_vigente(
    elegidos: list[tuple[str, int]],
) -> None:
    with pytest.raises(AddonSelectionError):
        _cotizar(*elegidos)


# ---------------------------------------------------------------------------
# Sena sobre el total
# ---------------------------------------------------------------------------


def test_la_sena_porcentual_sale_sobre_servicio_mas_adicionales() -> None:
    """El caso del diseno: 30 % de 27.000 + 3.000 = 9.000 (no 8.100)."""
    total = Decimal("27000") + _cotizar(("add-strass", 6))

    assert total == Decimal("30000.00")
    assert _sena(_Servicio(), total) == Decimal("9000.00")


def test_la_sena_fija_no_cambia_con_los_adicionales() -> None:
    fija = _Servicio(deposit_type="fixed", deposit_amount=Decimal("5000"))

    assert _sena(fija, Decimal("27000") + _cotizar(("add-strass", 6))) == Decimal(
        "5000.00"
    )


def test_full_cobra_tambien_los_adicionales() -> None:
    """Decision (b) del coordinador: el total entero."""
    total = _sena(_Servicio(deposit_type="full", deposit_amount=None), Decimal("30000"))

    assert total == Decimal("30000.00")


def test_los_recargos_tambien_salen_sobre_el_total() -> None:
    # Base 30 % de 30.000 = 9.000, mas 10 puntos del total = 3.000.
    sena = _sena(
        _Servicio(),
        Decimal("30000"),
        far_notice_days=1,
        far_notice_extra_percent=10,
    )

    assert sena == Decimal("12000.00")


def test_la_promo_baja_solo_el_servicio() -> None:
    """Decision (a) del coordinador: 10 % de promo sobre 27.000 = 24.300, mas
    3.000 de adicionales = 27.300; la sena del 30 % es 8.190."""
    servicio_con_promo = Decimal("27000") * Decimal("0.9")
    total = servicio_con_promo + _cotizar(("add-strass", 6))

    assert total == Decimal("27300.00")
    assert _sena(_Servicio(), total) == Decimal("8190.00")
