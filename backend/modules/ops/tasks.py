from __future__ import annotations

import logging
import json
import time
from typing import Any, Literal
from uuid import uuid4

import sentry_sdk
from celery.app.task import Task
from celery.exceptions import SoftTimeLimitExceeded

from core.celery_app import celery_app
from core.config import settings
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.observability import OncePer, report_exception
from core.redis import get_redis
from core.worker_loop import run_in_worker_loop
from modules.ops.router import _slo_alerts, _slo_metrics, _slo_thresholds

logger = logging.getLogger(__name__)

SLO_ALERT_COOLDOWN_SECONDS = 1800.0
SLO_ALERT_DELIVERY_LEASE_SECONDS = 240.0
SLO_ALERT_STATE_KEY = "shifty:ops:slo-alert-state:v1"
SLO_ALERT_LOCK_KEY = "shifty:ops:slo-alert-dispatch-lock:v1"
_MONITOR_FAILURE_COOLDOWN = OncePer(SLO_ALERT_COOLDOWN_SECONDS)
_UPDATE_SLO_ALERT_STATE = """
local raw = redis.call('GET', KEYS[1])
local state = raw and cjson.decode(raw) or {active = {}, last_active_at = {}}
local alerts = cjson.decode(ARGV[1])
local now = tonumber(ARGV[2])
local cooldown = tonumber(ARGV[3])
local present = {}
local transitions = {}
local claim = ARGV[4]
local lease_until = now + tonumber(ARGV[5])

for _, alert in ipairs(alerts) do
  local code = alert.code
  present[code] = true
  local previous = state.active[code] or {reported = false}
  if previous.pending_state == 'resolved' then
    previous.pending_state = nil
    previous.pending_token = nil
    previous.pending_until = nil
  end
  if not previous.reported then
    local pending_until = tonumber(previous.pending_until) or 0
    if not previous.pending_token or pending_until <= now then
      local last_active = tonumber(state.last_active_at[code]) or 0
      if now - last_active >= cooldown then
        previous.pending_state = 'active'
        previous.pending_token = claim
        previous.pending_until = lease_until
        table.insert(transitions, cjson.encode({state = 'active', alert = alert, token = claim}))
      end
    end
  end
  previous.alert = alert
  state.active[code] = previous
end

for code, previous in pairs(state.active) do
  if not present[code] then
    if previous.reported then
      local pending_until = tonumber(previous.pending_until) or 0
      if previous.pending_state ~= 'resolved' or pending_until <= now then
        previous.pending_state = 'resolved'
        previous.pending_token = claim
        previous.pending_until = lease_until
        table.insert(transitions, cjson.encode({state = 'resolved', alert = previous.alert, token = claim}))
      end
    elseif previous.pending_state == 'active' and (tonumber(previous.pending_until) or 0) > now then
      -- Un worker puede estar enviando la activacion: conservar el claim
      -- hasta su ACK o vencimiento antes de decidir si hubo una alerta real.
    else
      state.active[code] = nil
    end
  end
end

redis.call('SET', KEYS[1], cjson.encode(state), 'EX', 2592000)
return transitions
"""
_ACK_SLO_ALERT_TRANSITION = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local state = cjson.decode(raw)
local code = ARGV[1]
local transition_state = ARGV[2]
local token = ARGV[3]
local now = tonumber(ARGV[4])
local previous = state.active[code]
if not previous or previous.pending_token ~= token or previous.pending_state ~= transition_state then
  return 0
end
if transition_state == 'active' then
  previous.reported = true
  state.last_active_at[code] = now
  previous.pending_state = nil
  previous.pending_token = nil
  previous.pending_until = nil
else
  state.active[code] = nil
end
redis.call('SET', KEYS[1], cjson.encode(state), 'EX', 2592000)
return 1
"""
_RELEASE_SLO_ALERT_TRANSITION = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local state = cjson.decode(raw)
local previous = state.active[ARGV[1]]
if not previous or previous.pending_token ~= ARGV[2] then return 0 end
previous.pending_state = nil
previous.pending_token = nil
previous.pending_until = nil
redis.call('SET', KEYS[1], cjson.encode(state), 'EX', 2592000)
return 1
"""
_RELEASE_SLO_ALERT_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _capture_slo_transition(transition: dict[str, Any]) -> bool:
    alert = transition["alert"]
    code = str(alert["code"])
    state = str(transition["state"])
    level: Literal["error", "warning", "info"]
    if state != "active":
        level = "info"
    elif alert["severity"] == "critical":
        level = "error"
    else:
        level = "warning"
    message = (
        "SLO threshold exceeded" if state == "active" else "SLO threshold recovered"
    )
    if not settings.SENTRY_DSN:
        logger.warning(
            "ops_slo_transition",
            extra={
                "code": code,
                "severity": alert["severity"],
                "state": state,
                "value": alert["value"],
                "threshold": alert["threshold"],
            },
        )
        return True

    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("slo.alert_code", code)
            scope.set_context(
                "slo",
                {
                    "code": code,
                    "severity": alert["severity"],
                    "state": state,
                    "value": alert["value"],
                    "threshold": alert["threshold"],
                },
            )
            scope.fingerprint = ["ops-slo", code]
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        logger.warning("ops_slo_sentry_report_failed", exc_info=True)
        raise
    return True


async def _update_slo_alerts(
    alerts: list[dict[str, Any]], *, now: float | None = None
) -> None:
    """Claim, send and ACK SLO transitions with shared cross-worker state."""
    redis = await get_redis()
    timestamp = time.time() if now is None else now
    claim = uuid4().hex
    lock = await redis.set(
        SLO_ALERT_LOCK_KEY,
        claim,
        nx=True,
        ex=int(SLO_ALERT_DELIVERY_LEASE_SECONDS),
    )
    if not lock:
        return
    try:
        transitions = await redis.eval(
            _UPDATE_SLO_ALERT_STATE,
            1,
            SLO_ALERT_STATE_KEY,
            json.dumps(alerts, separators=(",", ":")),
            str(timestamp),
            str(SLO_ALERT_COOLDOWN_SECONDS),
            claim,
            str(SLO_ALERT_DELIVERY_LEASE_SECONDS),
        )
        for transition in transitions:
            event = json.loads(transition)
            state = str(event["state"])
            alert = event["alert"]
            code = str(alert["code"])
            token = str(event["token"])
            try:
                _capture_slo_transition(event)
            except Exception:
                await redis.eval(
                    _RELEASE_SLO_ALERT_TRANSITION,
                    1,
                    SLO_ALERT_STATE_KEY,
                    code,
                    token,
                )
                raise
            await redis.eval(
                _ACK_SLO_ALERT_TRANSITION,
                1,
                SLO_ALERT_STATE_KEY,
                code,
                state,
                token,
                str(timestamp),
            )
    finally:
        await redis.eval(
            _RELEASE_SLO_ALERT_LOCK,
            1,
            SLO_ALERT_LOCK_KEY,
            claim,
        )


@celery_app.task(name="monitor_ops_slo", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def monitor_ops_slo(self: Task) -> dict[str, int]:
    """Mide el agregado global con RLS interno y alerta umbrales existentes.

    No llama al endpoint autenticado, no crea credenciales ni modifica datos.
    """

    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                metrics = await _slo_metrics(db, None)
            finally:
                set_tenant_context(None, False)

        alerts = _slo_alerts(metrics, _slo_thresholds())
        await _update_slo_alerts(alerts)
        return {
            "metrics_checked": len(metrics),
            "alerts": len(alerts),
        }

    try:
        return run_in_worker_loop(_run())
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning(
            "ops_slo_monitor_failed", extra={"error_type": type(exc).__name__}
        )
        if _MONITOR_FAILURE_COOLDOWN.allow("ops_slo_monitor"):
            report_exception(
                RuntimeError("Critical SLO monitor failed"),
                component="ops_slo_monitor",
                error_type=type(exc).__name__,
            )
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))
