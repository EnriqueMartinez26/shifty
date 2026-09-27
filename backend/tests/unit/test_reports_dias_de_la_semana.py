"""Cuantos lunes (o martes...) hay en un rango: aritmetica, no un recorrido.

2026-09-18, hallazgo B5-20: ``get_professionals`` contaba los dias de cada
horario recorriendo el rango fecha por fecha dentro del loop de profesionales
y horarios (20 profesionales x 7 horarios x 371 dias = ~52.000 iteraciones por
request). El resultado es aritmetica de calendario cerrada: semanas completas
mas un resto. El riesgo declarado es un off-by-one en ``available_minutes``,
asi que la formula se compara contra el recorrido de fuerza bruta en todos los
arranques de semana, todos los largos hasta el tope del reporte (371 dias) y
los siete dias; el numero final lo fija ademas
``tests/integration/test_reportes_funciones_cortas.py`` (480 minutos).
"""

from datetime import date, time, timedelta
from types import SimpleNamespace
from typing import cast

from modules.reports.service import _available_minutes, _weekday_count
from modules.staff.model import Schedule


def _fuerza_bruta(desde: date, dias: int, dia_semana: int) -> int:
    return sum(
        1
        for offset in range(dias)
        if (desde + timedelta(days=offset)).weekday() == dia_semana
    )


def test_la_formula_coincide_con_el_recorrido_en_todo_el_dominio() -> None:
    lunes = date(2026, 9, 14)
    for arranque in range(7):
        desde = lunes + timedelta(days=arranque)
        for dias in range(0, 372):
            for dia_semana in range(7):
                assert _weekday_count(desde, dias, dia_semana) == _fuerza_bruta(
                    desde, dias, dia_semana
                ), (desde, dias, dia_semana)


def test_minutos_disponibles_de_un_rango_de_un_anio() -> None:
    # 2026-01-01 (jueves) + 365 dias: 53 jueves y 52 lunes.
    horarios = [
        cast(
            Schedule,
            SimpleNamespace(day_of_week=0, start_time=time(9), end_time=time(13)),
        ),
        cast(
            Schedule,
            SimpleNamespace(day_of_week=3, start_time=time(10), end_time=time(12)),
        ),
    ]
    assert _available_minutes(horarios, date(2026, 1, 1), 365) == (52 * 240 + 53 * 120)
