"""Varios servicios del mismo profesional en un turno: reglas puras.

Decision de Mateo (2026-10-16): hasta 3 servicios por turno y 480 minutos en
total; el turno dura la suma y cuesta la suma; la sena es la regla MAS ALTA
entre los servicios con sena, aplicada al TOTAL del turno (todos los servicios
y adicionales, despues de la promo), con los recargos de esa regla. Ejemplo del
dueno de la decision: Corte $10.000 con 50 % + Barba $5.000 sin sena -> $7.500.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from modules.appointments.availability import SLOT_STEP, leaves_unsellable_gap
from modules.payments.deposit_rules import (
    REASON_BASE,
    REASON_FAR_NOTICE,
    REASON_NEW_CLIENT,
    UNKNOWN_HISTORY,
    ClientHistory,
    DepositRules,
    decide_deposit,
    decide_selection_deposit,
    selection_deposit_mode,
)
from modules.services.addons import (
    AddonChoice,
    AddonSelectionError,
    price_selection,
    price_selection_for_services,
)
from modules.services.selection import (
    MAX_EXTRA_SERVICES,
    MAX_SERVICES_PER_APPOINTMENT,
    MAX_TOTAL_DURATION_MINUTES,
    cache_segment,
    has_duplicates,
    price_extra_services,
    services_label,
    snapshot_duration,
    snapshot_items,
    too_long,
    too_many_services,
)

SIN_RECARGOS = DepositRules()
NOTICE = timedelta(days=1)


@dataclass
class _Servicio:
    id: str
    public_id: str
    name: str
    duration_minutes: int
    price: Decimal
    deposit_mode: str = "none"
    deposit_type: str = "percent"
    deposit_amount: Decimal | None = None


CORTE = _Servicio(
    "s-corte", "p-corte", "Corte", 30, Decimal("10000"), "required", "percent",
    Decimal("50"),
)  # fmt: skip
BARBA = _Servicio("s-barba", "p-barba", "Barba", 20, Decimal("5000"))
COLOR = _Servicio(
    "s-color", "p-color", "Color", 60, Decimal("8000"), "optional", "fixed",
    Decimal("3000"),
)  # fmt: skip


def _sena(
    servicios: list[_Servicio],
    precio: Decimal,
    *,
    rules: DepositRules = SIN_RECARGOS,
    history: ClientHistory = UNKNOWN_HISTORY,
    notice: timedelta = NOTICE,
) -> tuple[Decimal, str | None]:
    resultado = decide_selection_deposit(
        servicios, price=precio, notice=notice, rules=rules, history=history
    )
    regla = resultado.rule_service
    return resultado.decision.amount, (regla.public_id if regla else None)


# ---------------------------------------------------------------------------
# Sena: la regla mas alta sobre el total
# ---------------------------------------------------------------------------


def test_el_ejemplo_de_la_decision_corte_con_50_y_barba_sin_sena() -> None:
    assert _sena([CORTE, BARBA], Decimal("15000")) == (Decimal("7500.00"), "p-corte")


def test_la_regla_de_un_extra_cobra_aunque_el_principal_no_tenga_sena() -> None:
    assert _sena([BARBA, CORTE], Decimal("15000")) == (Decimal("7500.00"), "p-corte")


def test_gana_la_regla_mas_alta_fija_contra_porcentual() -> None:
    """Corte 10 % de 18.000 = 1.800; Color fijo 3.000: cobra 3.000 (Color)."""
    corte_10 = _Servicio(
        "s-c", "p-c", "Corte", 30, Decimal("10000"), "required", "percent",
        Decimal("10"),
    )  # fmt: skip
    assert _sena([corte_10, COLOR], Decimal("18000")) == (Decimal("3000.00"), "p-color")
    # Con 50 % el porcentual gana: 9.000.
    assert _sena([CORTE, COLOR], Decimal("18000")) == (Decimal("9000.00"), "p-corte")


def test_ningun_servicio_con_sena_no_cobra_nada() -> None:
    sin = _Servicio("s-x", "p-x", "Lavado", 10, Decimal("2000"))
    assert _sena([BARBA, sin], Decimal("7000")) == (Decimal("0.00"), None)


def test_full_cobra_el_total_del_turno() -> None:
    entero = _Servicio(
        "s-f", "p-f", "Tintura", 60, Decimal("9000"), "required", "full", None
    )
    assert _sena([BARBA, entero], Decimal("14000")) == (Decimal("14000.00"), "p-f")


def test_el_fijo_se_acota_al_total() -> None:
    caro = _Servicio(
        "s-k", "p-k", "Caro", 30, Decimal("100"), "required", "fixed",
        Decimal("50000"),
    )  # fmt: skip
    assert _sena([caro, BARBA], Decimal("5100")) == (Decimal("5100.00"), "p-k")


def test_la_promo_se_aplica_al_total_antes_de_la_sena() -> None:
    """15.000 con 10 % de descuento = 13.500; la sena de 50 % es 6.750."""
    assert _sena([CORTE, BARBA], Decimal("13500")) == (Decimal("6750.00"), "p-corte")


def test_los_recargos_son_los_de_la_regla_elegida() -> None:
    reglas = DepositRules(
        far_notice_days=7,
        far_notice_extra_percent=10,
        new_client_extra_percent=5,
    )
    nuevo = ClientHistory()
    resultado = decide_selection_deposit(
        [BARBA, CORTE],
        price=Decimal("15000"),
        notice=timedelta(days=10),
        rules=reglas,
        history=nuevo,
    )
    # 50 % + 15 puntos sobre el total: 7.500 + 2.250.
    assert resultado.decision.amount == Decimal("9750.00")
    assert resultado.decision.extra_percent == 15
    assert resultado.decision.reasons == [
        REASON_BASE,
        REASON_FAR_NOTICE,
        REASON_NEW_CLIENT,
    ]
    assert resultado.rule_service is CORTE


def test_un_empate_lo_gana_el_elegido_primero() -> None:
    otro_corte = _Servicio(
        "s-o", "p-o", "Otro", 30, Decimal("1"), "required", "percent", Decimal("50")
    )
    assert _sena([CORTE, otro_corte], Decimal("100"))[1] == "p-corte"
    assert _sena([otro_corte, CORTE], Decimal("100"))[1] == "p-o"


@pytest.mark.parametrize("servicio", [CORTE, BARBA, COLOR])
def test_con_un_servicio_es_exactamente_decide_deposit(servicio: _Servicio) -> None:
    reglas = DepositRules(far_notice_days=1, far_notice_extra_percent=20)
    for precio in (Decimal("0"), Decimal("999.99"), Decimal("10000")):
        esperado = decide_deposit(
            servicio, price=precio, notice=NOTICE, rules=reglas, history=UNKNOWN_HISTORY
        )
        obtenido = decide_selection_deposit(
            [servicio],
            price=precio,
            notice=NOTICE,
            rules=reglas,
            history=UNKNOWN_HISTORY,
        ).decision
        assert obtenido == esperado


def test_un_turno_sin_servicios_no_existe() -> None:
    with pytest.raises(ValueError):
        decide_selection_deposit(
            [], price=Decimal("1"), notice=NOTICE, rules=SIN_RECARGOS,
            history=UNKNOWN_HISTORY,
        )  # fmt: skip


@pytest.mark.parametrize(
    ("servicios", "modo"),
    [
        ([BARBA], "none"),
        ([BARBA, COLOR], "optional"),
        ([COLOR, CORTE], "required"),
        ([BARBA, COLOR, CORTE], "required"),
        ([CORTE], "required"),
    ],
)
def test_el_modo_es_required_sobre_optional_sobre_none(
    servicios: list[_Servicio], modo: str
) -> None:
    assert selection_deposit_mode(servicios) == modo


# ---------------------------------------------------------------------------
# Topes, duracion y etiqueta
# ---------------------------------------------------------------------------


def test_los_topes_de_la_decision() -> None:
    assert MAX_SERVICES_PER_APPOINTMENT == 3
    assert MAX_EXTRA_SERVICES == 2
    assert MAX_TOTAL_DURATION_MINUTES == 480
    assert not too_many_services(["a", "b"])
    assert too_many_services(["a", "b", "c"])
    assert not too_long(480)
    assert too_long(481)


def test_repetidos_y_el_principal_como_extra() -> None:
    assert not has_duplicates("a", ["b", "c"])
    assert has_duplicates("a", ["a"])
    assert has_duplicates("a", ["b", "b"])


def test_los_extras_congelan_precio_y_duracion_de_hoy() -> None:
    extras = price_extra_services([BARBA, COLOR])
    assert extras.amount == Decimal("13000.00")
    assert extras.duration_minutes == 80
    assert extras.snapshot() == [
        {
            "service_id": "s-barba",
            "public_id": "p-barba",
            "name": "Barba",
            "duration_minutes": 20,
            "price": "5000.00",
        },
        {
            "service_id": "s-color",
            "public_id": "p-color",
            "name": "Color",
            "duration_minutes": 60,
            "price": "8000.00",
        },
    ]
    assert price_extra_services([]).snapshot() is None


def test_la_duracion_y_los_items_salen_del_snapshot_tolerando_basura() -> None:
    snapshot = price_extra_services([BARBA, COLOR]).snapshot()
    assert snapshot_duration(snapshot) == 80
    assert snapshot_items(snapshot) == [
        ("p-barba", "Barba", 20),
        ("p-color", "Color", 60),
    ]
    for raro in (None, "texto", {"a": 1}, [1, "x"], [{"duration_minutes": "x"}]):
        assert snapshot_duration(raro) == 0


def test_la_etiqueta_corte_mas_barba() -> None:
    snapshot = price_extra_services([BARBA]).snapshot()
    assert services_label("Corte", snapshot) == "Corte + Barba"
    assert services_label("Corte", None) == "Corte"
    assert services_label("Corte", [{"name": "Barba"}, "basura"]) == "Corte + Barba"


def test_la_clave_de_cache_de_un_servicio_no_cambia() -> None:
    assert cache_segment("p-corte", []) == "p-corte"
    # Con extras, el conjunto ordenado: el orden elegido no parte el cache.
    assert cache_segment("p-corte", ["p-barba"]) == "p-barba+p-corte"
    assert cache_segment("p-barba", ["p-corte"]) == "p-barba+p-corte"


# ---------------------------------------------------------------------------
# Adicionales repartidos por servicio
# ---------------------------------------------------------------------------


@dataclass
class _Adicional:
    id: str
    service_id: str
    name: str
    unit_price: Decimal
    max_quantity: int


DISENO = _Adicional("a-diseno", "s-corte", "Diseno", Decimal("1000"), 1)
ACEITE = _Adicional("a-aceite", "s-barba", "Aceite", Decimal("500"), 3)
BRILLO = _Adicional("a-brillo", "s-color", "Brillo", Decimal("700"), 1)


def test_cada_adicional_dice_de_que_servicio_es() -> None:
    cotizado = price_selection_for_services(
        [DISENO, ACEITE, BRILLO],
        [AddonChoice("a-aceite", 2), AddonChoice("a-diseno", 1)],
        service_ids=["s-corte", "s-barba"],
    )
    assert cotizado.total == Decimal("2000.00")
    assert [linea["service_id"] for linea in cotizado.snapshot() or []] == [
        "s-barba",
        "s-corte",
    ]


def test_un_adicional_de_un_servicio_no_elegido_se_rechaza() -> None:
    with pytest.raises(AddonSelectionError):
        price_selection_for_services(
            [DISENO, ACEITE, BRILLO],
            [AddonChoice("a-brillo", 1)],
            service_ids=["s-corte", "s-barba"],
        )


def test_con_un_servicio_la_linea_no_cambia_de_forma() -> None:
    cotizado = price_selection(
        [DISENO], [AddonChoice("a-diseno", 1)], service_id="s-corte"
    )
    assert cotizado.snapshot() == [
        {
            "addon_id": "a-diseno",
            "name": "Diseno",
            "unit_price": "1000.00",
            "quantity": 1,
            "amount": "1000.00",
        }
    ]


# ---------------------------------------------------------------------------
# Filtro de huecos con el servicio mas corto
# ---------------------------------------------------------------------------


def test_el_filtro_de_huecos_mide_con_el_servicio_mas_corto() -> None:
    """Hueco libre de 09:00 a 12:00 y un turno de 50 min (30 + 20) a las 09:45.

    Con la suma (50) antes de las 09:45 no entra otro turno de 50 alineado a
    la grilla y el slot se escondia; con el mas corto (20) entra a cada lado,
    asi que se ofrece. Sin ``gap_duration`` es lo de siempre.
    """
    origen = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    inicio = origen + timedelta(minutes=45)
    duracion = timedelta(minutes=50)

    def deja_hueco(gap: timedelta | None = None) -> bool:
        return leaves_unsellable_gap(
            inicio,
            duracion,
            free_from=origen,
            free_until=origen + timedelta(hours=3),
            grid_origin=origen,
            gap_duration=gap,
        )

    assert deja_hueco() is True
    assert deja_hueco(timedelta(minutes=20)) is False
    assert deja_hueco(duracion) == deja_hueco()
    assert SLOT_STEP == timedelta(minutes=15)
