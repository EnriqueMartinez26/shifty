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
import modules.payments.service as payments_service
from core.crypto import encrypt_secret
from core.observability import OncePer
from core.utils import format_ars
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
from modules.payments.service import (
    OAUTH_PENDING_ACCESS_TOKEN,
    gateway_has_usable_token,
)

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
        monkeypatch.setattr(deposit_channels, "_alertas", OncePer(3600.0))

    def test_un_warning_y_un_sentry_por_tienda_y_hora(
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

        # Pasada la hora vuelven los dos (re-revision: antes Sentry avisaba
        # una sola vez en la vida del proceso, con un set que solo crecia).
        report_deposit_channel_unavailable(store_id="t1", service_id="s1", clock=3600.0)
        assert len(warnings) == len(sentry) == 2

        # Otra tienda tiene su propio tope.
        report_deposit_channel_unavailable(store_id="t2", service_id="s9", clock=1.0)
        assert len(warnings) == len(sentry) == 3
        assert sentry[-1] == {"store_id": "t2", "service_id": "s9"}


class TestOncePer:
    def test_deja_pasar_una_vez_por_ventana_y_poda_lo_vencido(self) -> None:
        tope = OncePer(10.0)
        assert tope.allow("a", now=0.0)
        assert not tope.allow("a", now=9.9)
        assert tope.allow("a", now=10.0)
        assert tope.allow("b", now=10.0)
        # Con muchas claves, las vencidas se podan: la memoria queda acotada.
        for i in range(OncePer._PRUNE_ABOVE + 5):
            tope.allow(f"k{i}", now=100.0)
        tope.allow("nueva", now=200.0)
        assert len(tope._seen) == 1


class TestTokenIlegible:
    """Re-revision de la PR #108 (W2): un token de MP que no se descifra se
    veia como "MP no conectado" y la sena obligatoria pasaba en silencio a
    WhatsApp."""

    @pytest.fixture(autouse=True)
    def _limpio(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        avisos: list[dict[str, Any]] = []
        monkeypatch.setattr(payments_service, "_tokens_ilegibles", OncePer(3600.0))
        monkeypatch.setattr(
            payments_service,
            "report_exception",
            lambda exc, **ctx: avisos.append({"sentry": type(exc).__name__, **ctx}),
        )
        self.avisos = avisos
        return avisos

    def _config(self, token: str, store_id: str = "tienda") -> PaymentGatewayConfig:
        return PaymentGatewayConfig(
            id=f"cfg-{store_id}",
            store_id=store_id,
            provider="mercadopago",
            encrypted_access_token=token,
        )

    def test_un_token_roto_avisa_con_ids_una_vez_por_tienda(self) -> None:
        roto = self._config("gAAAA-no-es-un-token-cifrado")
        assert gateway_has_usable_token(roto) is False
        assert gateway_has_usable_token(roto) is False
        assert self.avisos == [
            {
                "sentry": "GatewayTokenUnreadable",
                "store_id": "tienda",
                "gateway_config_id": "cfg-tienda",
                "error_type": self.avisos[0]["error_type"],
            }
        ]
        # Ni el token cifrado ni su texto viajan.
        assert "gAAAA-no-es-un-token-cifrado" not in str(self.avisos)
        gateway_has_usable_token(self._config("otro-roto", store_id="otra"))
        assert len(self.avisos) == 2

    def test_el_placeholder_de_oauth_y_un_token_valido_no_avisan(self) -> None:
        assert (
            gateway_has_usable_token(self._config(OAUTH_PENDING_ACCESS_TOKEN)) is False
        )
        cifrado = encrypt_secret("APP_USR-token-real")
        assert cifrado is not None
        assert gateway_has_usable_token(self._config(cifrado)) is True
        assert self.avisos == []


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("3000.00", "$ 3.000"),
        (1234.5, "$ 1.234,50"),
        (-1500, "-$ 1.500"),
        # Un payload viejo o mal armado no rompe el aviso: vuelve tal cual.
        ("abc", "abc"),
        ("", ""),
        ("NaN", "NaN"),
        (None, "None"),
    ],
)
def test_format_ars_no_rompe_con_un_importe_que_no_es_numero(
    valor: object, esperado: str
) -> None:
    assert format_ars(valor) == esperado
