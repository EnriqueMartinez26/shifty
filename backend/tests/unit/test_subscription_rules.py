"""Ciclo de vida de la suscripcion (Fase 6): logica pura con fechas fijas."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from modules.billing.subscription_rules import (
    SUBSCRIPTION_GRACE_DAYS,
    SUBSCRIPTION_WARN_DAYS,
    InvalidSubscriptionTransition,
    apply_subscription_transition,
    daily_action,
    outlook,
)

HOY = date(2026, 9, 10)


def _sub(estado: str, vence: str | None, *, avisada: bool = False) -> SimpleNamespace:
    # 03:00 UTC del dia siguiente = ese dia a las 00:00 en Argentina; se usa
    # mediodia UTC para que el dia local sea inequivoco.
    fin = datetime.fromisoformat(vence + "T12:00:00+00:00") if vence else None
    return SimpleNamespace(
        status=estado,
        current_period_end=fin,
        plan_name="Plan Pro",
        expiry_warning_sent_at=datetime.now(timezone.utc) if avisada else None,
    )


def test_avisa_una_sola_vez_dentro_de_la_ventana() -> None:
    sub = _sub("active", "2026-09-15")
    accion = daily_action(sub, today=HOY)
    assert accion.send_warning is True and accion.new_status is None
    ya_avisada = _sub("active", "2026-09-15", avisada=True)
    assert daily_action(ya_avisada, today=HOY).send_warning is False


def test_fuera_de_la_ventana_no_avisa() -> None:
    lejos = _sub("active", "2026-10-30")
    assert daily_action(lejos, today=HOY).send_warning is False
    justo = _sub("active", "2026-09-17")  # 7 dias
    assert justo.current_period_end is not None
    assert daily_action(justo, today=HOY).send_warning is True


def test_al_vencer_pasa_a_past_due_y_no_antes() -> None:
    ultimo_dia = _sub("active", "2026-09-10")
    assert daily_action(ultimo_dia, today=HOY).new_status is None
    vencida = _sub("active", "2026-09-09")
    assert daily_action(vencida, today=HOY).new_status == "past_due"


def test_al_agotar_la_gracia_pasa_a_suspended() -> None:
    en_gracia = _sub("past_due", "2026-09-05")
    assert daily_action(en_gracia, today=HOY).new_status is None
    agotada = _sub("past_due", "2026-09-02")  # vencio hace 8 dias, gracia 7
    assert daily_action(agotada, today=HOY).new_status == "suspended"
    assert SUBSCRIPTION_GRACE_DAYS == 7 and SUBSCRIPTION_WARN_DAYS == 7


def test_cancelada_y_suspendida_no_se_mueven_solas() -> None:
    assert daily_action(_sub("cancelled", "2026-01-01"), today=HOY).new_status is None
    assert daily_action(_sub("suspended", "2026-01-01"), today=HOY).new_status is None


def test_sin_vencimiento_no_pasa_nada() -> None:
    accion = daily_action(_sub("active", None), today=HOY)
    assert accion.new_status is None and accion.send_warning is False


def test_el_grafo_rechaza_saltos_invalidos() -> None:
    sub = _sub("active", "2026-09-15")
    with pytest.raises(InvalidSubscriptionTransition):
        apply_subscription_transition(sub, "suspended")
    apply_subscription_transition(sub, "past_due")
    apply_subscription_transition(sub, "suspended")
    assert sub.status == "suspended"
    # Reactivar siempre se puede: es lo que hace el superadmin al cobrar.
    apply_subscription_transition(sub, "active")
    assert sub.status == "active"


def test_la_vista_del_dueno_cuenta_dias_locales_y_marca_el_bloqueo() -> None:
    proxima = outlook(_sub("active", "2026-09-13"), today=HOY)
    assert proxima.days_left == 3 and proxima.warn is True
    assert proxima.blocks_writes is False
    suspendida = outlook(_sub("suspended", "2026-08-01"), today=HOY)
    assert suspendida.blocks_writes is True and suspendida.public_page_hidden is True
    sin_plan = outlook(None, today=HOY)
    assert sin_plan.status == "none" and sin_plan.blocks_writes is False
