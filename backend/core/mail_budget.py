"""Atomic admission control and counters for the shared SMTP sink.

The configured limit is intentionally optional: deploys must set it only after
checking the actual provider account and its quota reset window.
"""

import asyncio
import hashlib
import math
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Literal, cast
from zoneinfo import ZoneInfo

import sentry_sdk
import structlog

from core.config import settings
from core.observability import report_mail_failure
from core.redis import REDIS_UNAVAILABLE_ERRORS, get_redis

MailPriority = Literal["critical", "high", "medium", "low"]
MailDecision = Literal["admitted", "duplicate", "deferred", "dropped", "unavailable"]
_PRIORITIES: frozenset[str] = frozenset({"critical", "high", "medium", "low"})
_REDIS_RETRIES = 2
_MAIL_CONTEXT: ContextVar[tuple[MailPriority, str] | None] = ContextVar(
    "mail_budget_context", default=None
)
_MAIL_PRE_DATA_RETRY: ContextVar[bool] = ContextVar(
    "mail_pre_data_retry", default=False
)

logger = structlog.get_logger()

_RESERVE_SCRIPT = """
local counts = KEYS[1]
local messages = KEYS[2]
local message_id = ARGV[1]
local token = ARGV[2]
local priority = ARGV[3]
local budget = tonumber(ARGV[4])
local reserve = tonumber(ARGV[5])
local alert_at = tonumber(ARGV[6])
local ttl = tonumber(ARGV[7])
local state = redis.call('HGET', messages, message_id)

if state and state ~= 'deferred' and state ~= 'retryable' then
    if state == 'reserved:' .. token then
        return {1, tonumber(redis.call('HGET', counts, 'admitted') or '0'), 0}
    end
    if state == 'dropped' then
        return {-1, tonumber(redis.call('HGET', counts, 'admitted') or '0'), 0}
    end
    return {2, tonumber(redis.call('HGET', counts, 'admitted') or '0'), 0}
end

local admitted = tonumber(redis.call('HGET', counts, 'admitted') or '0')
if state == 'retryable' then
    -- Reuse the logical message's existing admission; a bounded outbox retry
    -- must not consume another slot or be denied after the cap was reached.
    redis.call('HSET', messages, message_id, 'reserved:' .. token)
    redis.call('EXPIRE', messages, ttl)
    redis.call('EXPIRE', counts, ttl)
    return {1, admitted, 0}
end
if budget > 0 then
    local normal_limit = budget - reserve
    if priority ~= 'critical' and admitted >= normal_limit then
        if priority == 'low' then
            redis.call('HSET', messages, message_id, 'dropped')
            redis.call('HINCRBY', counts, 'dropped', 1)
            redis.call('EXPIRE', messages, ttl)
            redis.call('EXPIRE', counts, ttl)
            return {-1, admitted, 0}
        end
        if state ~= 'deferred' then
            redis.call('HINCRBY', counts, 'deferred', 1)
        end
        redis.call('HSET', messages, message_id, 'deferred')
        redis.call('EXPIRE', messages, ttl)
        redis.call('EXPIRE', counts, ttl)
        return {0, admitted, 0}
    end
    if admitted >= budget then
        redis.call('HSET', messages, message_id, 'dropped')
        redis.call('HINCRBY', counts, 'dropped', 1)
        redis.call('EXPIRE', messages, ttl)
        redis.call('EXPIRE', counts, ttl)
        return {-1, admitted, 0}
    end
end

redis.call('HSET', messages, message_id, 'reserved:' .. token)
admitted = redis.call('HINCRBY', counts, 'admitted', 1)
redis.call('HINCRBY', counts, 'priority:' .. priority, 1)
local alert = 0
if budget > 0 and admitted >= alert_at and redis.call('HGET', counts, 'alerted') ~= '1' then
    redis.call('HSET', counts, 'alerted', '1')
    alert = 1
end
redis.call('EXPIRE', messages, ttl)
redis.call('EXPIRE', counts, ttl)
return {1, admitted, alert}
"""

_FINISH_SCRIPT = """
local counts = KEYS[1]
local messages = KEYS[2]
local message_id = ARGV[1]
local token = ARGV[2]
local outcome = ARGV[3]
local message_state = ARGV[4]
local ttl = tonumber(ARGV[5])
if redis.call('HGET', messages, message_id) ~= 'reserved:' .. token then
    return 0
end
redis.call('HSET', messages, message_id, message_state)
redis.call('HINCRBY', counts, outcome, 1)
redis.call('EXPIRE', messages, ttl)
redis.call('EXPIRE', counts, ttl)
return 1
"""


@dataclass(frozen=True)
class MailReservation:
    decision: MailDecision
    window_id: str
    message_key: str
    attempt_token: str
    priority: MailPriority
    tracked: bool = True


@contextmanager
def mail_delivery_context(
    *, priority: MailPriority, message_id: str, retry_pre_data: bool = False
) -> Iterator[None]:
    """Carry priority, logical identity and retry policy to the SMTP sink."""
    token = _MAIL_CONTEXT.set((priority, message_id))
    retry_token = _MAIL_PRE_DATA_RETRY.set(retry_pre_data)
    try:
        yield
    finally:
        _MAIL_PRE_DATA_RETRY.reset(retry_token)
        _MAIL_CONTEXT.reset(token)


def current_mail_context() -> tuple[MailPriority, str] | None:
    return _MAIL_CONTEXT.get()


def current_mail_pre_data_retry() -> bool:
    return _MAIL_PRE_DATA_RETRY.get()


def _window(now: datetime | None = None) -> tuple[str, int]:
    """Return this provider calendar window and its remaining TTL.

    The quota resets at the configured wall-clock hour in the configured IANA
    timezone. Redis keeps the counters through the reset plus one day for
    diagnostics.
    """
    zone = ZoneInfo(settings.MAIL_BUDGET_TIMEZONE)
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("mail budget window requires an aware datetime")
    local = instant.astimezone(zone)
    boundary = datetime.combine(
        local.date(), time(hour=settings.MAIL_BUDGET_RESET_HOUR), tzinfo=zone
    )
    if local < boundary:
        boundary -= timedelta(days=1)
    next_boundary = boundary + timedelta(days=1)
    window_id = boundary.strftime("%Y%m%dT%H%z")
    ttl = max(60, int((next_boundary - local).total_seconds()) + 86_400)
    return window_id, ttl


def _redis_keys(window_id: str) -> tuple[str, str]:
    tag = f"{{mail-budget:{window_id}}}"
    return f"shifty:{tag}:counts", f"shifty:{tag}:messages"


def _safe_message_key(message_id: str) -> str:
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()


def _alert_threshold(budget: int) -> int:
    return max(1, math.ceil(budget * settings.MAIL_BUDGET_ALERT_PERCENT / 100))


def _report_threshold(window_id: str, admitted: int, budget: int) -> None:
    logger.warning(
        "mail_budget_early_alert",
        admitted=admitted,
        budget=budget,
        window=window_id,
        threshold_percent=settings.MAIL_BUDGET_ALERT_PERCENT,
    )
    try:
        sentry_sdk.capture_message(
            "Mail provider daily budget reached its configured early-alert threshold",
            level="warning",
        )
    except Exception as exc:
        logger.warning(
            "mail_budget_alert_reporting_failed", error_type=type(exc).__name__
        )


async def reserve_mail(*, priority: MailPriority, message_id: str) -> MailReservation:
    """Atomically admit one logical email, reserving its quota before SMTP.

    ``message_id`` must identify the logical delivery, not its recipient or
    content. A repeated task/outbox delivery is suppressed without another
    count. Deferred messages can be reconsidered on the next outbox tick;
    bounded pre-DATA retries reuse the existing admission.
    """
    if priority not in _PRIORITIES:
        raise ValueError(f"invalid mail priority: {priority}")
    window_id, ttl = _window()
    counts_key, messages_key = _redis_keys(window_id)
    attempt_token = secrets.token_hex(16)
    reservation = MailReservation(
        decision="unavailable",
        window_id=window_id,
        message_key=_safe_message_key(message_id),
        attempt_token=attempt_token,
        priority=priority,
    )
    budget = settings.MAIL_DAILY_BUDGET or 0
    critical_reserve = math.ceil(budget * settings.MAIL_CRITICAL_RESERVE_PERCENT / 100)
    arguments = (
        2,
        counts_key,
        messages_key,
        reservation.message_key,
        attempt_token,
        priority,
        budget,
        critical_reserve,
        _alert_threshold(budget) if budget else 0,
        ttl,
    )
    redis_error: BaseException | None = None
    retries = _REDIS_RETRIES if budget else 1
    for attempt in range(retries):
        try:
            redis = await get_redis()
            result = await redis.eval(_RESERVE_SCRIPT, *arguments)
            code, admitted, alert = (int(value) for value in result)
            decision = cast(
                MailDecision,
                {
                    1: "admitted",
                    2: "duplicate",
                    0: "deferred",
                    -1: "dropped",
                }[code],
            )
            if alert:
                _report_threshold(window_id, admitted, budget)
            return MailReservation(
                decision=decision,
                window_id=window_id,
                message_key=reservation.message_key,
                attempt_token=attempt_token,
                priority=priority,
            )
        except REDIS_UNAVAILABLE_ERRORS as exc:
            redis_error = exc
            if attempt + 1 < retries:
                await asyncio.sleep(0.05)
    assert redis_error is not None
    if budget:
        report_mail_failure(
            component="mail_budget", error_type=type(redis_error).__name__
        )
        logger.error(
            "mail_budget_redis_unavailable",
            error_type=type(redis_error).__name__,
            configured_budget=True,
        )
        return reservation
    logger.warning(
        "mail_budget_metrics_unavailable",
        error_type=type(redis_error).__name__,
        configured_budget=False,
    )
    return MailReservation(
        decision="admitted",
        window_id=window_id,
        message_key=reservation.message_key,
        attempt_token=attempt_token,
        priority=priority,
        tracked=False,
    )


async def finish_mail(
    reservation: MailReservation, *, sent: bool, retryable: bool = False
) -> None:
    """Record a send result; retryable pre-DATA failures retain their quota slot."""
    if not reservation.tracked or reservation.decision != "admitted":
        return
    counts_key, messages_key = _redis_keys(reservation.window_id)
    outcome = "sent" if sent else "failed"
    message_state = "sent" if sent else "retryable" if retryable else "failed"
    _, ttl = _window()
    arguments = (
        2,
        counts_key,
        messages_key,
        reservation.message_key,
        reservation.attempt_token,
        outcome,
        message_state,
        ttl,
    )
    for attempt in range(_REDIS_RETRIES):
        try:
            redis = await get_redis()
            await redis.eval(_FINISH_SCRIPT, *arguments)
            return
        except REDIS_UNAVAILABLE_ERRORS as exc:
            if attempt + 1 < _REDIS_RETRIES:
                await asyncio.sleep(0.05)
            else:
                report_mail_failure(
                    component="mail_budget", error_type=type(exc).__name__
                )
                logger.error(
                    "mail_budget_result_unrecorded",
                    outcome=outcome,
                    error_type=type(exc).__name__,
                )


async def read_mail_budget_metrics() -> dict[str, int | str | None]:
    """Read current-window counters for operational inspection and tests."""
    window_id, _ = _window()
    counts_key, _ = _redis_keys(window_id)
    redis = await get_redis()
    values = await redis.hgetall(counts_key)
    metrics: dict[str, int | str | None] = {
        "window": window_id,
        "budget": settings.MAIL_DAILY_BUDGET,
        "admitted": 0,
        "sent": 0,
        "failed": 0,
        "deferred": 0,
        "dropped": 0,
    }
    for field in ("admitted", "sent", "failed", "deferred", "dropped"):
        metrics[field] = int(values.get(field, 0))
    for priority in _PRIORITIES:
        metrics[f"priority:{priority}"] = int(values.get(f"priority:{priority}", 0))
    return metrics
