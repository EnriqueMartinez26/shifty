"""Reglas puras de la sena por WhatsApp (revision 4R de la PR #108).

- Retencion (decision de Mateo, 2026-10-03): hasta 2 h antes del turno, con un
  piso de 30 minutos desde ahora y nunca despues del inicio. La de MP (30
  minutos) no cambia.
- "MP conectado" es UN predicado (``gateway_has_usable_token``): el canal de
  la sena y la preferencia de MP no pueden discrepar. El ``"pending"`` que
  deja un alta de OAuth sin terminar no cuenta.
- Una reserva rechazada por falta de canal deja rastro con tope: un warning
  por tienda y hora, y un solo evento a Sentry por tienda.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import modules.payments.deposit_channels as deposit_channels
from core.crypto import encrypt_secret
from modules.payments.deposit_channels import (
    WHATSAPP_HOLD_LEAD,
    WHATSAPP_MIN_HOLD,
    deposit_mode_of,
    provider_for,
    report_deposit_channel_unavailable,
    whatsapp_hold_deadline,
)
from modules.payments.model import (
    PAYMENT_PROVIDER_MANUAL,
    PAYMENT_PROVIDER_MERCADOPAGO,
    PaymentGatewayConfig,
)
from modules.payments.service import gateway_has_usable_token

AHORA = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)


class TestRetencionPorWhatsApp:
    def test_las_constantes_son_las_de_la_decision(self) -> None:
        assert WHATSAPP_HOLD_LEAD == timedelta(hours=2)
        assert WHATSAPP_MIN_HOLD == timedelta(minutes=30)

    def test_turno_lejano_se_retiene_hasta_dos_horas_antes(self) -> None:
        inicio = AHORA + timedelta(days=2)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == inicio - timedelta(hours=2)

    def test_justo_en_el_borde_usa_dos_horas_antes(self) -> None:
        """inicio - 2 h == ahora + 30 min: el plazo y el piso coinciden."""
        inicio = AHORA + timedelta(hours=2, minutes=30)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == AHORA + timedelta(
            minutes=30
        )

    def test_un_minuto_despues_del_borde_ya_es_dos_horas_antes(self) -> None:
        inicio = AHORA + timedelta(hours=2, minutes=31)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == AHORA + timedelta(
            minutes=31
        )

    def test_un_minuto_antes_del_borde_usa_el_piso(self) -> None:
        inicio = AHORA + timedelta(hours=2, minutes=29)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == AHORA + timedelta(
            minutes=30
        )

    def test_con_menos_de_dos_horas_usa_el_piso(self) -> None:
        inicio = AHORA + timedelta(hours=1)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == AHORA + timedelta(
            minutes=30
        )

    def test_el_piso_nunca_pasa_el_inicio(self) -> None:
        inicio = AHORA + timedelta(minutes=10)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == inicio

    def test_un_turno_ya_empezado_vence_en_su_inicio(self) -> None:
        inicio = AHORA - timedelta(minutes=5)
        assert whatsapp_hold_deadline(inicio, now=AHORA) == inicio

    def test_un_inicio_naive_se_toma_como_utc_y_vuelve_aware(self) -> None:
        inicio = (AHORA + timedelta(days=1)).replace(tzinfo=None)
        plazo = whatsapp_hold_deadline(inicio, now=AHORA)
        assert plazo.tzinfo is not None
        assert plazo == AHORA + timedelta(days=1) - timedelta(hours=2)


def test_el_proveedor_sale_del_canal() -> None:
    assert provider_for("whatsapp") == PAYMENT_PROVIDER_MANUAL
    assert provider_for("mercadopago") == PAYMENT_PROVIDER_MERCADOPAGO


def test_el_modo_de_sena_por_defecto_es_none() -> None:
    assert deposit_mode_of(SimpleNamespace(deposit_mode="required")) == "required"
    assert deposit_mode_of(SimpleNamespace(deposit_mode=None)) == "none"
    assert deposit_mode_of(object()) == "none"


@pytest.mark.parametrize(
    ("token", "conectado"),
    [
        (encrypt_secret("APP_USR-token-real"), True),
        # El alta de OAuth guarda "pending" hasta aplicar el payload.
        ("pending", False),
        ("", False),
    ],
)
def test_mp_conectado_exige_un_token_que_se_pueda_descifrar(
    token: str | None, conectado: bool
) -> None:
    config = PaymentGatewayConfig(
        store_id="tienda", provider="mercadopago", encrypted_access_token=token
    )
    assert gateway_has_usable_token(config) is conectado
    assert gateway_has_usable_token(None) is False


class TestRastroSinCanal:
    @pytest.fixture(autouse=True)
    def _limpio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(deposit_channels, "_last_logged", {})
        monkeypatch.setattr(deposit_channels, "_reported_to_sentry", set())

    def test_un_warning_por_tienda_y_hora_y_un_solo_sentry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[dict[str, Any]] = []
        sentry: list[dict[str, Any]] = []
        monkeypatch.setattr(
            deposit_channels.logger,
            "warning",
            lambda evento, **ctx: warnings.append({"evento": evento, **ctx}),
        )
        monkeypatch.setattr(
            deposit_channels,
            "report_exception",
            lambda exc, **ctx: sentry.append(ctx),
        )

        for segundo in (0.0, 10.0, 3599.0):
            report_deposit_channel_unavailable(
                store_id="t1", service_id="s1", clock=segundo
            )
        assert warnings == [
            {
                "evento": "deposit_channel_unavailable",
                "store_id": "t1",
                "service_id": "s1",
            }
        ]
        assert sentry == [{"store_id": "t1", "service_id": "s1"}]

        # Pasada la hora vuelve el warning, pero Sentry ya lo tiene.
        report_deposit_channel_unavailable(store_id="t1", service_id="s1", clock=3600.0)
        assert len(warnings) == 2
        assert len(sentry) == 1

        # Otra tienda tiene su propio tope.
        report_deposit_channel_unavailable(store_id="t2", service_id="s9", clock=1.0)
        assert len(warnings) == 3
        assert sentry[-1] == {"store_id": "t2", "service_id": "s9"}
