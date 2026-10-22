"""Regla de la reserva lejana (decision de Mateo, 2026-10-20).

Un turno que empieza a mas de ``FAR_BOOKING_DAYS`` (30) dias de calendario
argentino y pide una sena OBLIGATORIA solo se cobra por Mercado Pago:

- con MP usable, ``auto`` y ``mercadopago`` cobran por MP y ``manual``
  (WhatsApp) es 422 ``FAR_BOOKING_REQUIRES_MERCADOPAGO``;
- sin MP usable la reserva no entra, pague como pague: 422
  ``FAR_BOOKING_UNAVAILABLE``;
- una sena opcional, sin sena o de importe cero no cambian.

El dia se cuenta en hora argentina (regla 24): hoy + 30 todavia no es lejano,
hoy + 31 si, aunque el instante UTC ya caiga en el dia siguiente.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.exceptions import AppException
from core.utils import ARGENTINA_TZ
from modules.payments.deposit_channels import (
    FAR_BOOKING_DAYS,
    DepositChannels,
    DepositChannelUnavailableError,
    FarBookingRequiresMercadoPagoError,
    FarBookingUnavailableError,
    booking_blocked_code,
    far_booking_rule_applies,
    is_far_booking,
    is_far_day,
    online_payment_mandatory,
    resolve_deposit_channel,
)

HOY = date(2026, 10, 20)
LIMITE = HOY + timedelta(days=FAR_BOOKING_DAYS)  # 2026-11-19: todavia no lejano

SIN_CANALES = DepositChannels(mercadopago=False, whatsapp=False, payments_enabled=False)
SOLO_MP = DepositChannels(mercadopago=True, whatsapp=False, payments_enabled=True)
SOLO_WHATSAPP = DepositChannels(mercadopago=False, whatsapp=True, payments_enabled=True)
AMBOS = DepositChannels(mercadopago=True, whatsapp=True, payments_enabled=True)

SENA = Decimal("1500")


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ARGENTINA_TZ)


def _resolver(
    payment_method: str,
    channels: DepositChannels,
    *,
    far_booking: bool = True,
    deposit_mode: str = "required",
    deposit_amount: Decimal = SENA,
    allow_manual_coordination: bool = True,
) -> str | None:
    return resolve_deposit_channel(
        payment_method,
        channels=channels,
        deposit_amount=deposit_amount,
        deposit_mode=deposit_mode,
        allow_manual_coordination=allow_manual_coordination,
        far_booking=far_booking,
    )


class TestDiaLejanoEnHoraArgentina:
    def test_la_constante_es_30_dias(self) -> None:
        assert FAR_BOOKING_DAYS == 30

    def test_hoy_mas_30_no_es_lejano_y_hoy_mas_31_si(self) -> None:
        assert not is_far_day(LIMITE, today=HOY)
        assert is_far_day(LIMITE + timedelta(days=1), today=HOY)
        assert not is_far_day(HOY, today=HOY)

    def test_las_23_30_locales_del_dia_limite_no_son_lejanas(self) -> None:
        # 23:30 del 19/11 en Argentina es 02:30 UTC del 20/11: el dia UTC ya
        # es el 31, el de negocio todavia es el 30.
        inicio = _local(LIMITE, 23, 30)
        assert inicio.astimezone(timezone.utc).date() == LIMITE + timedelta(days=1)
        assert not is_far_booking(inicio, today=HOY)

    def test_la_medianoche_local_del_dia_31_es_lejana(self) -> None:
        assert is_far_booking(_local(LIMITE + timedelta(days=1), 0, 0), today=HOY)

    def test_el_mismo_instante_en_utc_da_lo_mismo(self) -> None:
        cerca = _local(LIMITE, 23, 30).astimezone(timezone.utc)
        lejos = _local(LIMITE + timedelta(days=1), 0, 0).astimezone(timezone.utc)
        assert not is_far_booking(cerca, today=HOY)
        assert is_far_booking(lejos, today=HOY)

    def test_un_naive_es_utc(self) -> None:
        # 02:30 UTC del 20/11 (naive) son las 23:30 del 19/11 locales.
        naive = datetime(2026, 11, 20, 2, 30)
        assert not is_far_booking(naive, today=HOY)
        assert is_far_booking(datetime(2026, 11, 20, 3, 0), today=HOY)

    def test_una_fecha_que_desborda_cuenta_como_lejana_sin_500(self) -> None:
        # 23:00 con offset -5 del 31/12/9999 en hora argentina es el anio 10000.
        borde = datetime(9999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
        assert is_far_booking(borde, today=HOY)

    def test_sin_today_usa_el_dia_local_de_hoy(self) -> None:
        ahora = datetime.now(timezone.utc)
        assert not is_far_booking(ahora + timedelta(days=1))
        assert is_far_booking(ahora + timedelta(days=FAR_BOOKING_DAYS + 2))


class TestSenaObligatoriaLejana:
    @pytest.mark.parametrize("metodo", ["auto", "mercadopago"])
    def test_con_mp_se_cobra_por_mp(self, metodo: str) -> None:
        assert _resolver(metodo, AMBOS) == "mercadopago"
        assert _resolver(metodo, SOLO_MP) == "mercadopago"

    @pytest.mark.parametrize("permite_coordinar", [True, False])
    def test_whatsapp_elegido_es_422_aunque_la_tienda_lo_tenga(
        self, permite_coordinar: bool
    ) -> None:
        with pytest.raises(FarBookingRequiresMercadoPagoError) as exc:
            _resolver("manual", AMBOS, allow_manual_coordination=permite_coordinar)
        assert exc.value.http_status == 422
        assert exc.value.error_code == "FAR_BOOKING_REQUIRES_MERCADOPAGO"
        assert "Mercado Pago" in exc.value.message

    @pytest.mark.parametrize("metodo", ["auto", "manual", "mercadopago"])
    @pytest.mark.parametrize("canales", [SOLO_WHATSAPP, SIN_CANALES])
    def test_sin_mp_no_se_reserva_pague_como_pague(
        self, metodo: str, canales: DepositChannels
    ) -> None:
        with pytest.raises(FarBookingUnavailableError) as exc:
            _resolver(metodo, canales)
        assert exc.value.http_status == 422
        assert exc.value.error_code == "FAR_BOOKING_UNAVAILABLE"
        # Neutro (regla 20): no dice que le falta a la tienda.
        assert "Mercado Pago" not in exc.value.message
        assert "30 días" in exc.value.message

    def test_sin_mp_con_flag_de_cobros_prendido_tampoco(self) -> None:
        # El flag solo no alcanza: "MP usable" es la cuenta conectada.
        with pytest.raises(FarBookingUnavailableError):
            _resolver("auto", replace(SOLO_WHATSAPP, payments_enabled=True))

    def test_importe_cero_no_cobra_y_no_rechaza(self) -> None:
        assert _resolver("manual", SIN_CANALES, deposit_amount=Decimal("0")) is None


class TestSinSenaObligatoriaNoCambia:
    @pytest.mark.parametrize("modo", ["optional", "none"])
    def test_manual_lejano_sin_cobro(self, modo: str) -> None:
        assert _resolver("manual", SOLO_WHATSAPP, deposit_mode=modo) is None
        assert _resolver("manual", SIN_CANALES, deposit_mode=modo) is None

    def test_opcional_auto_con_cobros_sigue_por_mp(self) -> None:
        assert _resolver("auto", SOLO_MP, deposit_mode="optional") == "mercadopago"

    def test_opcional_auto_sin_cobros_sin_cobro(self) -> None:
        assert _resolver("auto", SIN_CANALES, deposit_mode="optional") is None

    def test_la_regla_solo_alcanza_a_la_obligatoria_con_importe(self) -> None:
        assert far_booking_rule_applies(
            far_booking=True, deposit_mode="required", deposit_amount=SENA
        )
        assert not far_booking_rule_applies(
            far_booking=True, deposit_mode="optional", deposit_amount=SENA
        )
        assert not far_booking_rule_applies(
            far_booking=True, deposit_mode="required", deposit_amount=Decimal("0")
        )
        assert not far_booking_rule_applies(
            far_booking=False, deposit_mode="required", deposit_amount=SENA
        )


class TestReservaCercanaNoCambia:
    def test_whatsapp_sigue_valiendo(self) -> None:
        assert _resolver("manual", SOLO_WHATSAPP, far_booking=False) == "whatsapp"
        assert _resolver("manual", AMBOS, far_booking=False) == "whatsapp"
        assert _resolver("auto", SOLO_WHATSAPP, far_booking=False) == "whatsapp"

    def test_sin_canal_sigue_siendo_409(self) -> None:
        with pytest.raises(DepositChannelUnavailableError) as exc:
            _resolver("auto", SIN_CANALES, far_booking=False)
        assert exc.value.http_status == 409

    def test_sin_far_booking_el_default_es_cercano(self) -> None:
        assert (
            resolve_deposit_channel(
                "manual",
                channels=SOLO_WHATSAPP,
                deposit_amount=SENA,
                deposit_mode="required",
                allow_manual_coordination=True,
            )
            == "whatsapp"
        )


class TestPreview:
    def test_online_payment_mandatory_lejano_con_mp(self) -> None:
        for lejana in (False, True):
            assert (
                online_payment_mandatory(
                    channels=AMBOS,
                    deposit_amount=SENA,
                    deposit_mode="required",
                    allow_manual_coordination=True,
                    far_booking=lejana,
                )
                is lejana
            )

    def test_online_payment_mandatory_lejano_sin_mp_es_falso(self) -> None:
        # Sin MP no hay pago online que exigir: lo dice booking_blocked_code.
        assert not online_payment_mandatory(
            channels=SOLO_WHATSAPP,
            deposit_amount=SENA,
            deposit_mode="required",
            allow_manual_coordination=True,
            far_booking=True,
        )

    @pytest.mark.parametrize(
        ("canales", "lejana", "modo", "esperado"),
        [
            (SOLO_WHATSAPP, True, "required", "FAR_BOOKING_UNAVAILABLE"),
            (SIN_CANALES, True, "required", "FAR_BOOKING_UNAVAILABLE"),
            (SIN_CANALES, False, "required", "DEPOSIT_CHANNEL_UNAVAILABLE"),
            (AMBOS, True, "required", None),
            (SOLO_WHATSAPP, False, "required", None),
            (SIN_CANALES, True, "optional", None),
            (SIN_CANALES, True, "none", None),
        ],
    )
    def test_booking_blocked_code(
        self,
        canales: DepositChannels,
        lejana: bool,
        modo: str,
        esperado: str | None,
    ) -> None:
        assert (
            booking_blocked_code(
                channels=canales,
                deposit_amount=SENA,
                deposit_mode=modo,
                allow_manual_coordination=True,
                far_booking=lejana,
            )
            == esperado
        )


def test_los_dos_errores_son_app_exception() -> None:
    assert issubclass(FarBookingRequiresMercadoPagoError, AppException)
    assert issubclass(FarBookingUnavailableError, AppException)
