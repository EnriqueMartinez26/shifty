"""Etapas del recordatorio (24h y 2h): logica pura con fechas fijas."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from modules.notifications.reminders import (
    STAGE_2H,
    STAGE_24H,
    due_stages,
    stage_is_due,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _turno(horas_hasta: float, *, reservado_hace_horas: float = 72.0, **marcas: object):
    starts_at = NOW + timedelta(hours=horas_hasta)
    campos: dict[str, object] = {
        "starts_at": starts_at,
        "created_at": NOW - timedelta(hours=reservado_hace_horas),
        "reminder_24h_sent_at": None,
        "reminder_2h_sent_at": None,
    }
    campos.update(marcas)
    return SimpleNamespace(**campos)


def test_a_23_horas_solo_corresponde_el_de_24() -> None:
    assert [s.name for s in due_stages(_turno(23), NOW)] == ["24h"]


def test_a_hora_y_media_solo_corresponde_el_de_2() -> None:
    # Piso del de 24h: si faltan menos de dos horas no se manda (iria pegado
    # al de 2h).
    assert [s.name for s in due_stages(_turno(1.5), NOW)] == ["2h"]


def test_a_30_horas_no_corresponde_ninguno() -> None:
    assert due_stages(_turno(30), NOW) == []


def test_ya_enviado_no_se_repite() -> None:
    turno = _turno(23, reminder_24h_sent_at=NOW - timedelta(minutes=15))
    assert due_stages(turno, NOW) == []


def test_turno_pasado_no_recibe_nada() -> None:
    assert due_stages(_turno(-0.5), NOW) == []


def test_reserva_de_ultimo_momento_no_recibe_el_de_24() -> None:
    # Reservado hace 10 minutos para dentro de 20 horas: el mail de reserva
    # acaba de salir; solo recibira el de 2h cuando toque.
    turno = _turno(20, reservado_hace_horas=10 / 60)
    assert due_stages(turno, NOW) == []


def test_reserva_hecha_media_hora_antes_no_recibe_el_de_2() -> None:
    turno = _turno(0.5, reservado_hace_horas=5 / 60)
    assert due_stages(turno, NOW) == []


def test_reserva_con_antelacion_recibe_ambos_en_su_momento() -> None:
    turno = _turno(23)
    assert stage_is_due(
        STAGE_24H,
        starts_at=turno.starts_at,
        created_at=turno.created_at,
        now=NOW,
        already_sent=False,
    )
    mas_tarde = NOW + timedelta(hours=21.5)
    assert stage_is_due(
        STAGE_2H,
        starts_at=turno.starts_at,
        created_at=turno.created_at,
        now=mas_tarde,
        already_sent=False,
    )


def test_acepta_fechas_naive_como_utc() -> None:
    # SQLite devuelve naive aun con timezone=True.
    turno = SimpleNamespace(
        starts_at=(NOW + timedelta(hours=23)).replace(tzinfo=None),
        created_at=(NOW - timedelta(days=3)).replace(tzinfo=None),
        reminder_24h_sent_at=None,
        reminder_2h_sent_at=None,
    )
    assert [s.name for s in due_stages(turno, NOW)] == ["24h"]
