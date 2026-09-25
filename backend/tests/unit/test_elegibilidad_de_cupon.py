"""La elegibilidad y la tarifacion de un canje se prueban sin base.

Auditoria B3-08, 2026-09-17. Sintoma: ``CouponAdminRepository.redeem_coupon``
tenia 95 lineas y metia en una sola funcion el lock, ocho validaciones, el
calculo del dinero, la escritura de dos agregados, el alta del canje, la
auditoria y el commit (regla 29 de CLAUDE.md). Las ocho validaciones son una
maquina de elegibilidad pura sobre ``(cupon, suscripcion, ahora)`` que no se
podia ejercer sin levantar Postgres y tomar dos ``SELECT ... FOR UPDATE``.

El orden importa: lo extraido corre DESPUES del lock. Mover una validacion
antes reabriria la carrera de ``current_uses`` contra el tope ``max_uses``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ast
import inspect
import pytest

from modules.billing.model import CouponRedemption, SaaSCoupon, StoreSubscription
from modules.superadmin.repository import (
    CouponAdminRepository,
    _assert_coupon_redeemable,
    _compute_discount,
)

AHORA = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
MAX_LINEAS = 80


def _cupon(**overrides: object) -> SaaSCoupon:
    # Los defaults de columna se aplican en el INSERT, no al instanciar: aca
    # todo va explicito para que el objeto suelto sea representativo.
    campos: dict[str, object] = {
        "code": "PROMO10",
        "coupon_type": "percent",
        "value": Decimal("10"),
        "currency": None,
        "max_uses": None,
        "current_uses": 0,
        "valid_from": None,
        "valid_until": None,
        "one_time_per_store": False,
        "is_active": True,
    }
    campos.update(overrides)
    return SaaSCoupon(**campos)


def _suscripcion(**overrides: object) -> StoreSubscription:
    campos: dict[str, object] = {
        "store_id": "store-1",
        "plan_id": "plan-1",
        "status": "active",
        "base_amount": Decimal("10000"),
        "discount_amount": Decimal("0"),
        "total_amount": Decimal("10000"),
        "currency": "ARS",
        "current_period_end": AHORA + timedelta(days=15),
        "is_active": True,
    }
    campos.update(overrides)
    return StoreSubscription(**campos)


def test_redeem_coupon_entra_en_el_tope_de_lineas_de_la_regla_29() -> None:
    source = inspect.getsource(CouponAdminRepository.redeem_coupon)
    cuerpo = ast.parse(source.lstrip()).body[0]
    assert isinstance(cuerpo, ast.AsyncFunctionDef)
    lineas = (cuerpo.end_lineno or 0) - cuerpo.lineno + 1
    assert lineas <= MAX_LINEAS, (
        f"redeem_coupon tiene {lineas} lineas (tope {MAX_LINEAS}, regla 29)."
    )


def test_un_canje_valido_no_levanta() -> None:
    _assert_coupon_redeemable(_cupon(), _suscripcion(), AHORA, None)


@pytest.mark.parametrize(
    ("cupon_kwargs", "suscripcion_kwargs", "previo", "mensaje"),
    [
        ({}, {"status": "suspended"}, False, "no está activa"),
        (
            {},
            {"current_period_end": AHORA - timedelta(days=1)},
            False,
            "está vencida",
        ),
        ({"is_active": False}, {}, False, "El cupón no está activo"),
        (
            {"valid_from": AHORA + timedelta(days=1)},
            {},
            False,
            "todavía no está vigente",
        ),
        (
            {"valid_until": AHORA - timedelta(days=1)},
            {},
            False,
            "El cupón está vencido",
        ),
        ({"max_uses": 3, "current_uses": 3}, {}, False, "límite de usos"),
        ({"currency": "USD"}, {}, False, "moneda del cupón no coincide"),
        ({"one_time_per_store": True}, {}, True, "ya canjeó ese cupón"),
    ],
)
def test_cada_causal_de_rechazo_tiene_su_mensaje(
    cupon_kwargs: dict[str, object],
    suscripcion_kwargs: dict[str, object],
    previo: bool,
    mensaje: str,
) -> None:
    anterior = CouponRedemption() if previo else None
    with pytest.raises(ValueError, match=mensaje):
        _assert_coupon_redeemable(
            _cupon(**cupon_kwargs),
            _suscripcion(**suscripcion_kwargs),
            AHORA,
            anterior,
        )


def test_una_suscripcion_sin_fin_de_periodo_no_se_considera_vencida() -> None:
    _assert_coupon_redeemable(
        _cupon(), _suscripcion(current_period_end=None), AHORA, None
    )


def test_un_canje_previo_no_bloquea_si_el_cupon_es_reutilizable() -> None:
    _assert_coupon_redeemable(
        _cupon(one_time_per_store=False), _suscripcion(), AHORA, CouponRedemption()
    )


def test_el_descuento_porcentual_se_redondea_a_dos_decimales() -> None:
    descuento, final = _compute_discount(
        _cupon(coupon_type="percent", value=Decimal("33.33")), Decimal("10000")
    )
    assert descuento == Decimal("3333.00")
    assert final == Decimal("6667.00")


def test_el_descuento_fijo_nunca_supera_la_base() -> None:
    descuento, final = _compute_discount(
        _cupon(coupon_type="fixed", value=Decimal("99999")), Decimal("10000")
    )
    assert descuento == Decimal("10000.00")
    assert final == Decimal("0.00")


def test_un_tipo_de_cupon_desconocido_es_un_error_de_dominio() -> None:
    with pytest.raises(ValueError, match="Tipo de cupón inválido"):
        _compute_discount(_cupon(coupon_type="regalo"), Decimal("10000"))
