"""Tests de ``resolve_deposit_channel`` (``modules/payments/deposit_channels.py``).

``create_public_booking`` pedia la misma pregunta tres veces -- "con el metodo
de pago pedido y estos datos de tienda/servicio, hace falta pagar la sena" --
con tres combinaciones booleanas distintas de las mismas 5 variables. Se
extrajo a una funcion pura para poder testearla sin DB ni FastAPI.

2026-10-03, decision de Mateo: una sena OBLIGATORIA se paga por Mercado Pago o
por WhatsApp (y la confirma a mano el personal). La funcion ya no dice "si o
no": dice POR DONDE se cobra la sena (``mercadopago``, ``whatsapp``) o que no
hay sena que cobrar (``None``). Una sena obligatoria sin ningun canal no se
reserva (409 ``DEPOSIT_CHANNEL_UNAVAILABLE``): el turno nunca se podria pagar.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from core.exceptions import AppException, ValidationException
from modules.payments.deposit_channels import (
    DepositChannels,
    online_payment_mandatory,
    resolve_deposit_channel,
)

# El flag de cobros viaja con los canales (``DepositChannels``); MP como canal
# lo implica. Cada caso lo fija explicito con ``replace`` cuando importa.
SIN_CANALES = DepositChannels(mercadopago=False, whatsapp=False, payments_enabled=False)
SOLO_MP = DepositChannels(mercadopago=True, whatsapp=False, payments_enabled=True)
SOLO_WHATSAPP = DepositChannels(
    mercadopago=False, whatsapp=True, payments_enabled=False
)
AMBOS = DepositChannels(mercadopago=True, whatsapp=True, payments_enabled=True)


class TestMercadopago:
    def test_sin_sena_configurada_lanza(self) -> None:
        with pytest.raises(ValidationException) as exc:
            resolve_deposit_channel(
                "mercadopago",
                channels=replace(SOLO_MP, payments_enabled=True),
                deposit_amount=Decimal("0"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
        assert "no tiene una seña configurada" in exc.value.message

    def test_pagos_deshabilitados_lanza(self) -> None:
        with pytest.raises(ValidationException) as exc:
            resolve_deposit_channel(
                "mercadopago",
                channels=replace(SOLO_WHATSAPP, payments_enabled=False),
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
        assert "no tiene habilitados los cobros" in exc.value.message

    def test_sin_sena_y_sin_pagos_prioriza_error_de_sena(self) -> None:
        """El orden importa: si faltan ambas cosas, gana el mensaje de la seña."""
        with pytest.raises(ValidationException) as exc:
            resolve_deposit_channel(
                "mercadopago",
                channels=replace(SIN_CANALES, payments_enabled=False),
                deposit_amount=Decimal("0"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
        assert "no tiene una seña configurada" in exc.value.message

    def test_viable_cobra_por_mercado_pago(self) -> None:
        assert (
            resolve_deposit_channel(
                "mercadopago",
                channels=replace(SOLO_MP, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            == "mercadopago"
        )

    def test_pedido_explicito_no_mira_la_conexion(self) -> None:
        """Camino de MP sin cambios: con el flag prendido y sin cuenta
        conectada sigue siendo el 409 PAYMENT_GATEWAY_NOT_CONNECTED de
        siempre, que se resuelve al pedir el link."""
        assert (
            resolve_deposit_channel(
                "mercadopago",
                channels=replace(SOLO_WHATSAPP, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
            == "mercadopago"
        )


class TestManual:
    def test_sena_obligatoria_sin_coordinacion_manual_lanza(self) -> None:
        with pytest.raises(ValidationException) as exc:
            resolve_deposit_channel(
                "manual",
                channels=replace(AMBOS, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=False,
            )
        assert "requiere pagar la seña con Mercado Pago" in exc.value.message

    def test_sena_obligatoria_con_coordinacion_manual_se_cobra_por_whatsapp(
        self,
    ) -> None:
        assert (
            resolve_deposit_channel(
                "manual",
                channels=replace(AMBOS, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
            == "whatsapp"
        )

    def test_sena_obligatoria_sin_mp_se_cobra_por_whatsapp(self) -> None:
        """La bandera de coordinacion manual solo obliga a pagar online
        cuando hay Mercado Pago: sin el, WhatsApp es el unico canal."""
        assert (
            resolve_deposit_channel(
                "manual",
                channels=replace(SOLO_WHATSAPP, payments_enabled=False),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=False,
            )
            == "whatsapp"
        )

    def test_sena_obligatoria_sin_whatsapp_pide_mercado_pago(self) -> None:
        with pytest.raises(ValidationException) as exc:
            resolve_deposit_channel(
                "manual",
                channels=replace(SOLO_MP, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
        assert "requiere pagar la seña con Mercado Pago" in exc.value.message

    def test_sena_opcional_no_se_cobra(self) -> None:
        assert (
            resolve_deposit_channel(
                "manual",
                channels=replace(AMBOS, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is None
        )

    def test_sena_none_no_se_cobra(self) -> None:
        assert (
            resolve_deposit_channel(
                "manual",
                channels=replace(SIN_CANALES, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="none",
                allow_manual_coordination=False,
            )
            is None
        )


class TestAuto:
    def test_pagos_habilitados_y_sena_positiva_cobra_por_mercado_pago(self) -> None:
        assert (
            resolve_deposit_channel(
                "auto",
                channels=replace(SOLO_MP, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            == "mercadopago"
        )

    def test_pagos_deshabilitados_no_cobra(self) -> None:
        assert (
            resolve_deposit_channel(
                "auto",
                channels=replace(SIN_CANALES, payments_enabled=False),
                deposit_amount=Decimal("100"),
                deposit_mode="optional",
                allow_manual_coordination=False,
            )
            is None
        )

    def test_sena_cero_no_cobra(self) -> None:
        assert (
            resolve_deposit_channel(
                "auto",
                channels=replace(AMBOS, payments_enabled=True),
                deposit_amount=Decimal("0"),
                deposit_mode="required",
                allow_manual_coordination=False,
            )
            is None
        )

    def test_sena_obligatoria_prefiere_mercado_pago(self) -> None:
        assert (
            resolve_deposit_channel(
                "auto",
                channels=replace(AMBOS, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
            == "mercadopago"
        )

    def test_sena_obligatoria_sin_mp_conectado_va_por_whatsapp(self) -> None:
        assert (
            resolve_deposit_channel(
                "auto",
                channels=replace(SOLO_WHATSAPP, payments_enabled=True),
                deposit_amount=Decimal("100"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
            == "whatsapp"
        )


class TestSinCanal:
    """2026-10-03, QA en navegador (``barberia-sentinel``): con MP sin
    conectar, cobros apagados y sin WhatsApp, la reserva de un servicio con
    sena obligatoria salia ``pending`` sin cobro y nadie podia completarla."""

    @pytest.mark.parametrize("metodo", ["auto", "manual"])
    def test_sena_obligatoria_sin_canal_no_se_reserva(self, metodo: str) -> None:
        with pytest.raises(AppException) as exc:
            resolve_deposit_channel(
                metodo,
                channels=replace(SIN_CANALES, payments_enabled=False),
                deposit_amount=Decimal("3000"),
                deposit_mode="required",
                allow_manual_coordination=True,
            )
        assert exc.value.http_status == 409
        assert exc.value.error_code == "DEPOSIT_CHANNEL_UNAVAILABLE"


class TestPagoOnlineObligatorio:
    """``online_payment_mandatory`` del preview: el portal no ofrece el boton
    de WhatsApp cuando la reserva por ese canal va a rebotar."""

    def test_con_mp_y_sin_coordinacion_manual(self) -> None:
        assert online_payment_mandatory(
            channels=AMBOS,
            deposit_amount=Decimal("100"),
            deposit_mode="required",
            allow_manual_coordination=False,
        )

    def test_con_mp_y_sin_whatsapp(self) -> None:
        assert online_payment_mandatory(
            channels=SOLO_MP,
            deposit_amount=Decimal("100"),
            deposit_mode="required",
            allow_manual_coordination=True,
        )

    def test_con_whatsapp_y_coordinacion_manual(self) -> None:
        assert not online_payment_mandatory(
            channels=AMBOS,
            deposit_amount=Decimal("100"),
            deposit_mode="required",
            allow_manual_coordination=True,
        )

    def test_sin_mp_nunca(self) -> None:
        assert not online_payment_mandatory(
            channels=SOLO_WHATSAPP,
            deposit_amount=Decimal("100"),
            deposit_mode="required",
            allow_manual_coordination=False,
        )

    def test_sena_opcional_nunca(self) -> None:
        assert not online_payment_mandatory(
            channels=SOLO_MP,
            deposit_amount=Decimal("100"),
            deposit_mode="optional",
            allow_manual_coordination=False,
        )
