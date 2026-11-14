from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core import mail_budget
from core.mail_budget import MailReservation, mail_delivery_context
from core.config import Settings, settings
from modules.notifications import tasks
from tests.redis_mail_budget_double import AtomicMailBudgetRedis

_real_budget_window = mail_budget._window


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> AtomicMailBudgetRedis:
    double = AtomicMailBudgetRedis()

    async def fake_get_redis() -> AtomicMailBudgetRedis:
        return double

    monkeypatch.setattr(mail_budget, "get_redis", fake_get_redis)
    monkeypatch.setattr(mail_budget, "_window", lambda now=None: ("test-window", 3600))
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 0)
    return double


@pytest.mark.asyncio
async def test_prioriza_criticos_y_difiere_o_descarta_el_resto(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 10)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 20)
    monkeypatch.setattr(settings, "MAIL_BUDGET_ALERT_PERCENT", 80)
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mail_budget, "_report_threshold", lambda *args: alerts.append(args)
    )

    admitted = [
        await mail_budget.reserve_mail(priority="medium", message_id=f"reminder:{i}")
        for i in range(8)
    ]
    deferred = await mail_budget.reserve_mail(
        priority="high", message_id="booking:deferred"
    )
    deferred_again = await mail_budget.reserve_mail(
        priority="high", message_id="booking:deferred"
    )
    dropped_low = await mail_budget.reserve_mail(
        priority="low", message_id="rebook:dropped"
    )
    critical_a = await mail_budget.reserve_mail(priority="critical", message_id="otp:a")
    critical_b = await mail_budget.reserve_mail(
        priority="critical", message_id="password-reset:b"
    )
    critical_at_cap = await mail_budget.reserve_mail(
        priority="critical", message_id="otp:at-cap"
    )

    assert all(item.decision == "admitted" for item in admitted)
    assert deferred.decision == deferred_again.decision == "deferred"
    assert dropped_low.decision == "dropped"
    assert critical_a.decision == critical_b.decision == "admitted"
    assert critical_at_cap.decision == "dropped"
    assert len(alerts) == 1

    metrics = await mail_budget.read_mail_budget_metrics()
    assert metrics["admitted"] == 10
    assert metrics["deferred"] == 1
    assert metrics["dropped"] == 2
    assert metrics["priority:critical"] == 2
    assert redis.hashes


@pytest.mark.asyncio
async def test_cupo_brevo_aprobado_reserva_50_y_alerta_en_200(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 250)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 20)
    monkeypatch.setattr(settings, "MAIL_BUDGET_ALERT_PERCENT", 80)
    alerts: list[tuple[str, int, int]] = []
    monkeypatch.setattr(
        mail_budget, "_report_threshold", lambda *args: alerts.append(args)
    )

    ordinary = [
        await mail_budget.reserve_mail(priority="high", message_id=f"high:{i}")
        for i in range(200)
    ]
    ordinary_at_limit = await mail_budget.reserve_mail(
        priority="medium", message_id="reminder:201"
    )
    critical = [
        await mail_budget.reserve_mail(priority="critical", message_id=f"otp:{i}")
        for i in range(50)
    ]
    critical_at_cap = await mail_budget.reserve_mail(
        priority="critical", message_id="otp:at-cap"
    )

    assert all(item.decision == "admitted" for item in ordinary)
    assert ordinary_at_limit.decision == "deferred"
    assert all(item.decision == "admitted" for item in critical)
    assert critical_at_cap.decision == "dropped"
    assert alerts == [("test-window", 200, 250)]
    metrics = await mail_budget.read_mail_budget_metrics()
    assert metrics["admitted"] == 250
    assert metrics["deferred"] == 1
    assert metrics["priority:critical"] == 50


@pytest.mark.asyncio
async def test_concurrencia_no_supera_el_tope_ni_cuenta_dos_veces(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 7)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 20)

    reservations = await asyncio.gather(
        *(
            mail_budget.reserve_mail(priority="critical", message_id=f"otp:{i}")
            for i in range(30)
        )
    )
    admitted = [item for item in reservations if item.decision == "admitted"]
    dropped = [item for item in reservations if item.decision == "dropped"]
    await asyncio.gather(
        *(mail_budget.finish_mail(item, sent=True) for item in admitted)
    )
    await mail_budget.finish_mail(admitted[0], sent=True)

    metrics = await mail_budget.read_mail_budget_metrics()
    assert len(admitted) == 7
    assert len(dropped) == 23
    assert metrics["admitted"] == 7
    assert metrics["sent"] == 7
    assert metrics["dropped"] == 23


@pytest.mark.asyncio
async def test_el_fallo_no_se_cuenta_como_enviado_ni_reintenta_un_resultado_ambiguo(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    reservation = await mail_budget.reserve_mail(
        priority="critical", message_id="otp:ambiguous"
    )
    await mail_budget.finish_mail(reservation, sent=False)

    retry = await mail_budget.reserve_mail(
        priority="critical", message_id="otp:ambiguous"
    )
    metrics = await mail_budget.read_mail_budget_metrics()

    assert retry.decision == "duplicate"
    assert metrics["admitted"] == 1
    assert metrics["sent"] == 0
    assert metrics["failed"] == 1


@pytest.mark.asyncio
async def test_fallo_pre_data_reusa_el_cupo_del_mismo_mensaje_logico(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    first = await mail_budget.reserve_mail(
        priority="high", message_id="outbox:pre-data-retry"
    )
    await mail_budget.finish_mail(first, sent=False, retryable=True)

    retry = await mail_budget.reserve_mail(
        priority="high", message_id="outbox:pre-data-retry"
    )
    assert retry.decision == "admitted"
    await mail_budget.finish_mail(retry, sent=True)
    duplicate = await mail_budget.reserve_mail(
        priority="high", message_id="outbox:pre-data-retry"
    )
    metrics = await mail_budget.read_mail_budget_metrics()

    assert duplicate.decision == "duplicate"
    assert metrics["admitted"] == 1
    assert metrics["priority:high"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 1


@pytest.mark.asyncio
async def test_retry_pre_data_tras_reset_admite_el_mismo_id_en_la_nueva_ventana(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    monkeypatch.setattr(
        settings, "MAIL_BUDGET_TIMEZONE", "America/Argentina/Buenos_Aires"
    )
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 6)
    zone = ZoneInfo("America/Argentina/Buenos_Aires")
    instant = [datetime(2026, 11, 13, 5, tzinfo=zone)]
    monkeypatch.setattr(
        mail_budget,
        "_window",
        lambda now=None: _real_budget_window(now or instant[0]),
    )

    first = await mail_budget.reserve_mail(
        priority="high", message_id="outbox:retry-crossing-reset"
    )
    await mail_budget.finish_mail(first, sent=False, retryable=True)
    same_window_retry = await mail_budget.reserve_mail(
        priority="high", message_id="outbox:retry-crossing-reset"
    )
    await mail_budget.finish_mail(same_window_retry, sent=False, retryable=True)

    instant[0] = datetime(2026, 11, 13, 6, 1, tzinfo=zone)
    next_window_retry = await mail_budget.reserve_mail(
        priority="high", message_id="outbox:retry-crossing-reset"
    )
    await mail_budget.finish_mail(next_window_retry, sent=True)

    old_counts, _ = mail_budget._redis_keys(first.window_id)
    new_counts, _ = mail_budget._redis_keys(next_window_retry.window_id)
    old_metrics = await redis.hgetall(old_counts)
    new_metrics = await redis.hgetall(new_counts)

    assert same_window_retry.decision == "admitted"
    assert same_window_retry.window_id == first.window_id
    assert next_window_retry.decision == "admitted"
    assert next_window_retry.window_id != first.window_id
    assert old_metrics["admitted"] == "1"
    assert old_metrics["failed"] == "2"
    assert new_metrics["admitted"] == "1"
    assert new_metrics["sent"] == "1"


@pytest.mark.asyncio
async def test_un_mismo_id_logico_concurrente_solo_reserva_un_cupo(
    redis: AtomicMailBudgetRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 10)

    reservations = await asyncio.gather(
        *(
            mail_budget.reserve_mail(priority="high", message_id="outbox:row-123")
            for _ in range(8)
        )
    )
    assert sum(item.decision == "admitted" for item in reservations) == 1
    assert sum(item.decision == "duplicate" for item in reservations) == 7


def test_la_ventana_respeta_zona_y_hora_de_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 250)
    monkeypatch.setattr(
        settings, "MAIL_BUDGET_TIMEZONE", "America/Argentina/Buenos_Aires"
    )
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 6)
    zone = ZoneInfo("America/Argentina/Buenos_Aires")

    antes_del_reset = datetime(2026, 11, 13, 5, tzinfo=zone).astimezone(timezone.utc)
    despues_del_reset = datetime(2026, 11, 13, 7, tzinfo=zone).astimezone(timezone.utc)

    assert mail_budget._window(antes_del_reset)[0] == "20261112T06-0300"
    assert mail_budget._window(despues_del_reset)[0] == "20261113T06-0300"


def test_rechaza_zona_que_no_sea_iana() -> None:
    with pytest.raises(ValueError, match="MAIL_BUDGET_TIMEZONE"):
        Settings.model_validate(
            {
                **settings.model_dump(),
                "MAIL_DAILY_BUDGET": None,
                "MAIL_BUDGET_TIMEZONE": "No/Existe",
            }
        )


def test_la_ventana_sin_tope_no_asume_hora_de_reset_del_proveedor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", None)
    monkeypatch.setattr(
        settings, "MAIL_BUDGET_TIMEZONE", "America/Argentina/Buenos_Aires"
    )
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 5)

    assert mail_budget._window(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))[0] == (
        "20261113T00+0000"
    )


def test_la_ventana_con_tope_rechaza_reset_no_confirmado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 250)
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", None)
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", None)

    with pytest.raises(ValueError, match="MAIL_BUDGET_RESET_HOUR"):
        mail_budget._window(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_redis_falla_cerrado_solo_cuando_el_cap_esta_configurado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def unavailable() -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("redis unavailable")

    monkeypatch.setattr(mail_budget, "get_redis", unavailable)
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 25)
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 0)
    closed = await mail_budget.reserve_mail(
        priority="critical", message_id="otp:closed"
    )
    assert closed.decision == "unavailable"
    assert attempts == 2

    attempts = 0
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", None)
    open_unlimited = await mail_budget.reserve_mail(
        priority="critical", message_id="otp:unlimited"
    )
    assert open_unlimited.decision == "admitted"
    assert open_unlimited.tracked is False
    assert attempts == 1


@pytest.mark.asyncio
async def test_sink_respeta_contexto_de_prioridad_y_no_manda_un_diferido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vistos: list[tuple[str, str]] = []
    enviados: list[object] = []

    async def admitido(**kwargs: Any) -> MailReservation:
        vistos.append((kwargs["priority"], kwargs["message_id"]))
        return MailReservation(
            decision="admitted",
            window_id="test-window",
            message_key="message",
            attempt_token="attempt",
            priority=kwargs["priority"],
            tracked=False,
        )

    async def finish(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(tasks, "reserve_mail", admitido)
    monkeypatch.setattr(tasks, "finish_mail", finish)
    smtp = tasks.SmtpSession()
    monkeypatch.setattr(smtp, "_send_sync", lambda message: enviados.append(message))

    with mail_delivery_context(priority="critical", message_id="otp:stable-id"):
        assert await smtp.send("person@example.com", "OTP", "123456")
    assert vistos == [("critical", "otp:stable-id")]
    assert len(enviados) == 1

    async def deferred(**kwargs: Any) -> MailReservation:
        return MailReservation(
            decision="deferred",
            window_id="test-window",
            message_key="message",
            attempt_token="attempt",
            priority=kwargs["priority"],
        )

    monkeypatch.setattr(tasks, "reserve_mail", deferred)
    assert not await smtp.send("person@example.com", "Reminder", "body")
    assert len(enviados) == 1
    assert smtp.last_budget_decision == "deferred"
