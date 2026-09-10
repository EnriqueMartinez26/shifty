"""Regla de la sena (Fase 5): pura, con bordes."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from modules.payments.deposit_rules import (
    ClientHistory,
    DepositRules,
    base_deposit,
    decide_deposit,
)

SIN_RECARGOS = DepositRules()
CON_TODO = DepositRules(
    far_notice_days=7,
    far_notice_extra_percent=20,
    new_client_extra_percent=10,
    absent_client_extra_percent=30,
)
HABITUAL = ClientHistory(completed=5)
NUEVO = ClientHistory()
FALTADOR = ClientHistory(completed=2, absent=1)


def _servicio(
    mode: str = "required", tipo: str = "percent", monto: float | None = 30
) -> SimpleNamespace:
    return SimpleNamespace(deposit_mode=mode, deposit_type=tipo, deposit_amount=monto)


def test_sin_sena_base_no_hay_recargo_aunque_apliquen_todas_las_reglas() -> None:
    d = decide_deposit(
        _servicio(mode="none"),
        price=Decimal("10000"),
        notice=timedelta(days=30),
        rules=CON_TODO,
        history=ClientHistory(absent=3),
    )
    assert d.amount == Decimal("0.00")
    assert d.reasons == []


def test_cliente_habitual_con_poca_antelacion_paga_solo_la_base() -> None:
    d = decide_deposit(
        _servicio(),
        price=Decimal("10000"),
        notice=timedelta(days=2),
        rules=CON_TODO,
        history=HABITUAL,
    )
    assert d.amount == Decimal("3000.00")
    assert d.extra_percent == 0
    assert d.reasons == ["base"]


def test_los_recargos_se_suman_en_puntos_del_precio() -> None:
    d = decide_deposit(
        _servicio(),
        price=Decimal("10000"),
        notice=timedelta(days=10),
        rules=CON_TODO,
        history=NUEVO,
    )
    # base 30% + 20 (antelacion) + 10 (nuevo) = 60%
    assert d.amount == Decimal("6000.00")
    assert d.extra_percent == 30
    assert d.reasons == ["base", "far_notice", "new_client"]


def test_nunca_supera_el_precio() -> None:
    d = decide_deposit(
        _servicio(monto=80),
        price=Decimal("10000"),
        notice=timedelta(days=10),
        rules=CON_TODO,
        history=FALTADOR,
    )
    # 80% + 20 + 30 = 130% -> tope en el precio
    assert d.amount == Decimal("10000.00")
    assert d.reasons == ["base", "far_notice", "absences"]


def test_fijo_mayor_que_el_precio_se_recorta_al_precio() -> None:
    assert base_deposit(
        _servicio(tipo="fixed", monto=15000), Decimal("10000")
    ) == Decimal("10000.00")


def test_porcentaje_sobre_precio_con_promo_y_redondeo() -> None:
    # 30% de 8333.33 = 2499.999 -> 2500.00
    d = decide_deposit(
        _servicio(),
        price=Decimal("8333.33"),
        notice=timedelta(hours=3),
        rules=SIN_RECARGOS,
        history=HABITUAL,
    )
    assert d.amount == Decimal("2500.00")


def test_total_es_el_precio_y_los_recargos_no_lo_mueven() -> None:
    d = decide_deposit(
        _servicio(tipo="full", monto=None),
        price=Decimal("5000"),
        notice=timedelta(days=30),
        rules=CON_TODO,
        history=NUEVO,
    )
    assert d.amount == Decimal("5000.00")


def test_el_umbral_de_antelacion_es_inclusivo_y_cero_lo_apaga() -> None:
    reglas = DepositRules(far_notice_days=7, far_notice_extra_percent=20)
    justo = decide_deposit(
        _servicio(),
        price=Decimal("1000"),
        notice=timedelta(days=7),
        rules=reglas,
        history=HABITUAL,
    )
    assert justo.extra_percent == 20
    apagado = decide_deposit(
        _servicio(),
        price=Decimal("1000"),
        notice=timedelta(days=30),
        rules=DepositRules(far_notice_days=0, far_notice_extra_percent=20),
        history=HABITUAL,
    )
    assert apagado.extra_percent == 0


def test_el_snapshot_es_serializable_y_explica_el_monto() -> None:
    d = decide_deposit(
        _servicio(),
        price=Decimal("10000"),
        notice=timedelta(days=10),
        rules=CON_TODO,
        history=FALTADOR,
    )
    assert d.snapshot() == {
        "amount": "8000.00",
        "base_amount": "3000.00",
        "extra_percent": 50,
        "reasons": ["base", "far_notice", "absences"],
    }
