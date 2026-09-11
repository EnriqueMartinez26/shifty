"""Tests de _resolve_payment_requirement (backend/modules/public_api/router.py).

create_public_booking pedia la misma pregunta tres veces -- "con el metodo de
pago pedido y estos datos de tienda/servicio, hace falta pagar la sena" -- con
tres combinaciones booleanas distintas de las mismas 5 variables. Se extrajo
a una funcion pura para poder testearla sin DB ni FastAPI.
"""

from decimal import Decimal

import pytest

from core.exceptions import ValidationException
from modules.public_api.router import _resolve_payment_requirement


class TestMercadopago:
    def test_sin_sena_configurada_lanza(self) -> None:
        with pytest.raises(ValidationException) as exc:
            _resolve_payment_requirement(
                payment_method="mercadopago",
                payments_enabled=True,
                deposit_amount=Decimal("0"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
        assert "no tiene una seña configurada" in exc.value.message

    def test_pagos_deshabilitados_lanza(self) -> None:
        with pytest.raises(ValidationException) as exc:
            _resolve_payment_requirement(
                payment_method="mercadopago",
                payments_enabled=False,
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
        assert "no tiene habilitados los cobros" in exc.value.message

    def test_sin_sena_y_sin_pagos_prioriza_error_de_sena(self) -> None:
        """El orden importa: si faltan ambas cosas, gana el mensaje de la seña."""
        with pytest.raises(ValidationException) as exc:
            _resolve_payment_requirement(
                payment_method="mercadopago",
                payments_enabled=False,
                deposit_amount=Decimal("0"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
        assert "no tiene una seña configurada" in exc.value.message

    def test_viable_devuelve_true(self) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="mercadopago",
                payments_enabled=True,
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is True
        )


class TestManual:
    def test_sena_obligatoria_sin_coordinacion_manual_lanza(self) -> None:
        with pytest.raises(ValidationException) as exc:
            _resolve_payment_requirement(
                payment_method="manual",
                payments_enabled=True,
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=False,
            )
        assert "requiere pagar la seña" in exc.value.message

    def test_sena_obligatoria_con_coordinacion_manual_habilitada_no_lanza(
        self,
    ) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="manual",
                payments_enabled=True,
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
            is False
        )

    def test_sena_opcional_no_lanza(self) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="manual",
                payments_enabled=True,
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is False
        )

    def test_sena_none_no_lanza(self) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="manual",
                payments_enabled=True,
                deposit_amount=Decimal("100"),
                deposit_mode="none",
                allow_manual_coordination=False,
            )
            is False
        )


class TestAuto:
    def test_pagos_habilitados_y_sena_positiva_requiere_pago(self) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="auto",
                payments_enabled=True,
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is True
        )

    def test_pagos_deshabilitados_no_requiere_pago(self) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="auto",
                payments_enabled=False,
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is False
        )

    def test_sena_cero_no_requiere_pago(self) -> None:
        assert (
            _resolve_payment_requirement(
                payment_method="auto",
                payments_enabled=True,
                deposit_amount=Decimal("0"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is False
        )
