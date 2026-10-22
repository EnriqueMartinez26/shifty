"""``within_booking_horizon``: el borde de los 120 dias locales del portal.

Paquete antiabuso (2026-10-22, D-20261022-01, propuesta por Mateo, pendiente
de OK del dueno). Los tests HTTP cubren el camino; aca el borde exacto, que
por la grilla semanal de los tests de integracion no se puede pedir: el dia
120 entra, el 121 no, y ``keep_up_to`` corre el tope al dia del inicio
actual cuando es mas tarde.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from core.utils import (
    ARGENTINA_TZ,
    BOOKING_HORIZON_DAYS,
    today_local,
    within_booking_horizon,
)


def _local(dias: int, hora: time = time(23, 30)) -> datetime:
    """Un instante del dia local ``hoy + dias`` (23:30 local: ya es el dia
    siguiente en UTC, asi el borde es de dia LOCAL y no de dia UTC)."""
    dia = today_local() + timedelta(days=dias)
    return datetime.combine(dia, hora, tzinfo=ARGENTINA_TZ).astimezone(timezone.utc)


def test_el_dia_120_entra_y_el_121_no() -> None:
    assert within_booking_horizon(_local(BOOKING_HORIZON_DAYS))
    assert not within_booking_horizon(_local(BOOKING_HORIZON_DAYS + 1, time(0, 0)))


def test_keep_up_to_corre_el_tope_al_dia_del_inicio_actual() -> None:
    actual = _local(150, time(10, 0))

    assert within_booking_horizon(_local(150), keep_up_to=actual)
    assert within_booking_horizon(_local(140), keep_up_to=actual)
    assert not within_booking_horizon(_local(151, time(0, 0)), keep_up_to=actual)


def test_keep_up_to_mas_cerca_no_achica_el_tope() -> None:
    assert within_booking_horizon(_local(BOOKING_HORIZON_DAYS), keep_up_to=_local(3))


def test_una_fecha_que_desborda_queda_afuera_sin_500() -> None:
    # Llevarla a hora argentina pasa del anio 9999: ``OverflowError``.
    lejisimo = datetime(9999, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-10)))

    assert not within_booking_horizon(lejisimo)
    assert not within_booking_horizon(lejisimo, keep_up_to=_local(150))
