from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import sentry_sdk
import pytest
from kombu.exceptions import OperationalError as KombuOperationalError
from redis.asyncio import from_url
from redis.exceptions import ConnectionError as RedisConnectionError
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import HttpTransport, Transport

from core import observability
from core.config import settings
from core.observability import OncePer
from modules.ops import router as ops_router
from modules.ops import tasks as slo_tasks


class _Scope:
    def __init__(self) -> None:
        self.tags: dict[str, str] = {}
        self.context: dict[str, dict[str, Any]] = {}
        self.fingerprint: list[str] = []

    def __enter__(self) -> _Scope:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def set_context(self, key: str, value: dict[str, Any]) -> None:
        self.context[key] = value


class _SharedRedisState:
    def __init__(self) -> None:
        self.active: dict[str, dict[str, Any]] = {}
        self.last_active_at: dict[str, float] = {}
        self.locks: dict[str, str] = {}


class _RedisClient:
    def __init__(self, shared: _SharedRedisState) -> None:
        self.shared = shared

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self.shared.locks:
            return None
        self.shared.locks[key] = value
        return True

    async def eval(
        self,
        script: str,
        _key_count: int,
        *args: str,
    ) -> list[str]:
        if script == slo_tasks._RELEASE_SLO_ALERT_LOCK:
            _key, token = args
            if self.shared.locks.get(_key) == token:
                del self.shared.locks[_key]
            return []
        if script == slo_tasks._ACK_SLO_ALERT_TRANSITION:
            _key, code, state, token, raw_now = args
            current = self.shared.active.get(code)
            if not current or current.get("pending_token") != token:
                return []
            if state == "active":
                current["reported"] = True
                self.shared.last_active_at[code] = float(raw_now)
                current.pop("pending_state", None)
                current.pop("pending_token", None)
                current.pop("pending_until", None)
            else:
                del self.shared.active[code]
            return []
        if script == slo_tasks._RELEASE_SLO_ALERT_TRANSITION:
            _key, code, token, raw_now, raw_cooldown = args
            current = self.shared.active.get(code)
            if current and current.get("pending_token") == token:
                current.pop("pending_state", None)
                current.pop("pending_token", None)
                current.pop("pending_until", None)
                current["next_attempt_at"] = float(raw_now) + float(raw_cooldown)
            return []
        assert script == slo_tasks._UPDATE_SLO_ALERT_STATE
        _key, serialized_alerts, raw_now, raw_cooldown, claim, raw_lease = args
        now = float(raw_now)
        cooldown = float(raw_cooldown)
        lease = float(raw_lease)
        alerts = json.loads(serialized_alerts)
        current = {str(alert["code"]): alert for alert in alerts}
        transitions: list[str] = []

        for code, alert in current.items():
            previous = self.shared.active.get(code, {"reported": False})
            if previous.get("pending_state") == "resolved":
                previous.pop("pending_state", None)
                previous.pop("pending_token", None)
                previous.pop("pending_until", None)
            if not previous["reported"]:
                pending_until = previous.get("pending_until", 0)
                next_attempt_at = previous.get("next_attempt_at", 0)
                if (
                    not previous.get("pending_token") or pending_until <= now
                ) and next_attempt_at <= now:
                    last_active = self.shared.last_active_at.get(code, 0)
                    if now - last_active >= cooldown:
                        previous["pending_state"] = "active"
                        previous["pending_token"] = claim
                        previous["pending_until"] = now + lease
                        previous.pop("next_attempt_at", None)
                        previous["alert"] = alert
                        transitions.append(
                            json.dumps(
                                {"state": "active", "alert": alert, "token": claim}
                            )
                        )
            else:
                previous["alert"] = alert
            self.shared.active[code] = previous

        for code in self.shared.active.keys() - current.keys():
            previous = self.shared.active[code]
            if previous["reported"]:
                pending_until = previous.get("pending_until", 0)
                next_attempt_at = previous.get("next_attempt_at", 0)
                if (
                    previous.get("pending_state") != "resolved" or pending_until <= now
                ) and next_attempt_at <= now:
                    previous["pending_state"] = "resolved"
                    previous["pending_token"] = claim
                    previous["pending_until"] = now + lease
                    previous.pop("next_attempt_at", None)
                    transitions.append(
                        json.dumps(
                            {
                                "state": "resolved",
                                "alert": previous["alert"],
                                "token": claim,
                            }
                        )
                    )
            elif (
                previous.get("pending_state") != "active"
                or previous.get("pending_until", 0) <= now
            ):
                del self.shared.active[code]
        return transitions


def test_slo_monitor_deduplicates_across_workers_and_reports_recovery_recurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://sentry.invalid/1")
    scopes: list[_Scope] = []
    events: list[tuple[str, str, dict[str, Any]]] = []

    def new_scope() -> _Scope:
        scope = _Scope()
        scopes.append(scope)
        return scope

    def capture_message(message: str, *, level: str) -> str:
        scope = scopes[-1]
        events.append((message, level, scope.context["slo"]))
        return "captured-event-id"

    monkeypatch.setattr(sentry_sdk, "new_scope", new_scope)
    monkeypatch.setattr(sentry_sdk, "capture_message", capture_message)
    critical = [
        {
            "code": "pending_webhooks_high",
            "severity": "critical",
            "value": 8,
            "threshold": 5,
        }
    ]

    shared = _SharedRedisState()
    worker_a = _RedisClient(shared)
    worker_b = _RedisClient(shared)
    client = [worker_a]

    async def get_worker_redis() -> _RedisClient:
        return client[0]

    monkeypatch.setattr(slo_tasks, "get_redis", get_worker_redis)
    asyncio.run(slo_tasks._update_slo_alerts(critical, now=10_000))
    client[0] = worker_b
    asyncio.run(slo_tasks._update_slo_alerts(critical, now=10_200))
    asyncio.run(slo_tasks._update_slo_alerts([], now=10_300))
    # A reopened alert inside cooldown is held until it remains active past it.
    client[0] = worker_a
    asyncio.run(slo_tasks._update_slo_alerts(critical, now=10_400))
    client[0] = worker_b
    asyncio.run(slo_tasks._update_slo_alerts(critical, now=11_801))

    assert [(message, level) for message, level, _ in events] == [
        ("SLO threshold exceeded", "error"),
        ("SLO threshold recovered", "info"),
        ("SLO threshold exceeded", "error"),
    ]
    assert [event[2]["state"] for event in events] == [
        "active",
        "resolved",
        "active",
    ]
    assert all(event[2]["code"] == "pending_webhooks_high" for event in events)


def test_slo_sentry_failure_releases_pending_transition_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = _SharedRedisState()
    clients = [_RedisClient(shared), _RedisClient(shared)]
    client_index = [0]
    calls = 0

    async def get_worker_redis() -> _RedisClient:
        return clients[client_index[0]]

    def capture(transition: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary Sentry failure")

    monkeypatch.setattr(slo_tasks, "get_redis", get_worker_redis)
    monkeypatch.setattr(slo_tasks, "_capture_slo_transition", capture)
    alert = [
        {
            "code": "dead_letter_webhooks",
            "severity": "critical",
            "value": 1,
            "threshold": 0,
        }
    ]

    with pytest.raises(RuntimeError, match="temporary Sentry failure"):
        asyncio.run(slo_tasks._update_slo_alerts(alert, now=20_000))
    assert shared.active["dead_letter_webhooks"]["reported"] is False
    assert "pending_token" not in shared.active["dead_letter_webhooks"]

    client_index[0] = 1
    asyncio.run(
        slo_tasks._update_slo_alerts(
            alert,
            now=20_000 + slo_tasks.SLO_ALERT_CAPTURE_RETRY_COOLDOWN_SECONDS,
        )
    )
    client_index[0] = 0
    asyncio.run(
        slo_tasks._update_slo_alerts(
            alert,
            now=20_000 + slo_tasks.SLO_ALERT_CAPTURE_RETRY_COOLDOWN_SECONDS + 1,
        )
    )

    assert calls == 2
    assert shared.active["dead_letter_webhooks"]["reported"] is True
    assert shared.locks == {}


def test_slo_sentry_drop_releases_pending_transition_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://sentry.invalid/1")
    monkeypatch.setattr(sentry_sdk, "new_scope", _Scope)
    captured: list[str | None] = [None]

    def capture_message(_message: str, *, level: str) -> str | None:
        assert level == "error"
        return captured[0]

    monkeypatch.setattr(sentry_sdk, "capture_message", capture_message)
    shared = _SharedRedisState()

    async def get_worker_redis() -> _RedisClient:
        return _RedisClient(shared)

    monkeypatch.setattr(slo_tasks, "get_redis", get_worker_redis)
    alert = [
        {
            "code": "failed_webhooks_high",
            "severity": "critical",
            "value": 1,
            "threshold": 0,
        }
    ]

    with pytest.raises(RuntimeError, match="did not capture the SLO transition"):
        asyncio.run(slo_tasks._update_slo_alerts(alert, now=25_000))

    transition = shared.active["failed_webhooks_high"]
    assert transition["reported"] is False
    assert "pending_token" not in transition
    assert transition["next_attempt_at"] == (
        25_000 + slo_tasks.SLO_ALERT_CAPTURE_RETRY_COOLDOWN_SECONDS
    )
    assert shared.locks == {}

    # Celery's shorter retry does not re-capture during the per-code cooldown.
    asyncio.run(slo_tasks._update_slo_alerts(alert, now=25_001))
    assert transition["reported"] is False

    captured[0] = "captured-event-id"
    asyncio.run(
        slo_tasks._update_slo_alerts(
            alert,
            now=25_000 + slo_tasks.SLO_ALERT_CAPTURE_RETRY_COOLDOWN_SECONDS - 1,
        )
    )
    assert transition["reported"] is False
    asyncio.run(
        slo_tasks._update_slo_alerts(
            alert,
            now=25_000 + slo_tasks.SLO_ALERT_CAPTURE_RETRY_COOLDOWN_SECONDS,
        )
    )

    assert shared.active["failed_webhooks_high"]["reported"] is True
    assert shared.locks == {}


def test_slo_monitor_reports_warning_severity_from_shared_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://sentry.invalid/1")
    scope = _Scope()
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(sentry_sdk, "new_scope", lambda: scope)

    def capture_message(message: str, *, level: str) -> str:
        messages.append((message, level))
        return "captured-event-id"

    monkeypatch.setattr(sentry_sdk, "capture_message", capture_message)
    alert = {
        "code": "pending_outbox_high",
        "severity": "warning",
        "value": 4,
        "threshold": 3,
    }
    shared = _SharedRedisState()

    async def get_worker_redis() -> _RedisClient:
        return _RedisClient(shared)

    monkeypatch.setattr(slo_tasks, "get_redis", get_worker_redis)
    asyncio.run(slo_tasks._update_slo_alerts([alert], now=100_000))

    assert messages == [("SLO threshold exceeded", "warning")]
    assert scope.context["slo"]["severity"] == "warning"


@pytest.mark.asyncio
async def test_slo_alert_lua_executes_against_real_redis_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.getenv("SLO_TEST_REDIS_URL")
    if not url:
        pytest.skip("set SLO_TEST_REDIS_URL to a local disposable Redis for EVAL test")
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("real EVAL test only accepts loopback Redis")

    client = from_url(url, decode_responses=True)
    second_client = from_url(url, decode_responses=True)
    state_key = f"{slo_tasks.SLO_ALERT_STATE_KEY}:test:{uuid4().hex}"
    lock_key = f"{slo_tasks.SLO_ALERT_LOCK_KEY}:test:{uuid4().hex}"
    await client.delete(state_key, lock_key)
    monkeypatch.setattr(slo_tasks, "SLO_ALERT_STATE_KEY", state_key)
    monkeypatch.setattr(slo_tasks, "SLO_ALERT_LOCK_KEY", lock_key)

    async def get_local_redis() -> Any:
        return client

    monkeypatch.setattr(slo_tasks, "get_redis", get_local_redis)
    monkeypatch.setattr(settings, "SENTRY_DSN", "")
    alert = [
        {
            "code": "pending_webhooks_high",
            "severity": "critical",
            "value": 9,
            "threshold": 5,
        }
    ]

    try:
        serialized_alerts = json.dumps(alert, separators=(",", ":"))
        check_args = (
            slo_tasks._UPDATE_SLO_ALERT_STATE,
            1,
            state_key,
            serialized_alerts,
            "30000",
            str(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
        )
        concurrent_claims = await asyncio.gather(
            client.eval(
                *check_args,
                "worker-a-claim",
                str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
            ),
            second_client.eval(
                *check_args,
                "worker-b-claim",
                str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
            ),
        )
        claims = [json.loads(event) for batch in concurrent_claims for event in batch]
        assert len(claims) == 1
        transition = claims[0]
        assert (
            await second_client.eval(
                slo_tasks._ACK_SLO_ALERT_TRANSITION,
                1,
                state_key,
                "pending_webhooks_high",
                "active",
                transition["token"],
                "30000",
            )
            == 1
        )
        await client.delete(state_key)

        interrupted = json.dumps(
            [
                {
                    "code": "failed_webhooks_high",
                    "severity": "critical",
                    "value": 21,
                    "threshold": 20,
                }
            ],
            separators=(",", ":"),
        )
        abandoned = await client.eval(
            slo_tasks._UPDATE_SLO_ALERT_STATE,
            1,
            state_key,
            interrupted,
            "30000",
            str(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
            "interrupted-worker",
            str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
        )
        assert len(abandoned) == 1
        recovered_claim = await second_client.eval(
            slo_tasks._UPDATE_SLO_ALERT_STATE,
            1,
            state_key,
            interrupted,
            "30241",
            str(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
            "replacement-worker",
            str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
        )
        assert len(recovered_claim) == 1
        recovered_transition = json.loads(recovered_claim[0])
        assert recovered_transition["token"] == "replacement-worker"

        await client.delete(state_key)
        capture_failed = await client.eval(
            slo_tasks._UPDATE_SLO_ALERT_STATE,
            1,
            state_key,
            interrupted,
            "31000",
            str(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
            "capture-failed-worker",
            str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
        )
        failed_transition = json.loads(capture_failed[0])
        assert (
            await client.eval(
                slo_tasks._RELEASE_SLO_ALERT_TRANSITION,
                1,
                state_key,
                "failed_webhooks_high",
                failed_transition["token"],
                "31000",
                str(slo_tasks.SLO_ALERT_CAPTURE_RETRY_COOLDOWN_SECONDS),
            )
            == 1
        )
        too_soon = await client.eval(
            slo_tasks._UPDATE_SLO_ALERT_STATE,
            1,
            state_key,
            interrupted,
            "31299",
            str(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
            "early-retry-worker",
            str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
        )
        assert too_soon == []
        after_cooldown = await client.eval(
            slo_tasks._UPDATE_SLO_ALERT_STATE,
            1,
            state_key,
            interrupted,
            "31300",
            str(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
            "scheduled-retry-worker",
            str(slo_tasks.SLO_ALERT_DELIVERY_LEASE_SECONDS),
        )
        assert len(after_cooldown) == 1

        # Start the ordinary monitor transitions with an empty state key.
        await client.delete(state_key)

        await slo_tasks._update_slo_alerts(alert, now=30_000)
        raw_state = await client.get(state_key)
        assert raw_state is not None
        state = json.loads(raw_state)
        assert state["active"]["pending_webhooks_high"]["reported"] is True
        assert state["last_active_at"]["pending_webhooks_high"] == 30_000

        await slo_tasks._update_slo_alerts(alert, now=30_100)
        await slo_tasks._update_slo_alerts([], now=30_200)
        raw_state = await client.get(state_key)
        assert raw_state is not None
        assert json.loads(raw_state)["active"] == {}

        # Recovery resets the active state; recurrence is held until cooldown.
        await slo_tasks._update_slo_alerts(alert, now=30_300)
        raw_state = await client.get(state_key)
        assert raw_state is not None
        assert (
            json.loads(raw_state)["active"]["pending_webhooks_high"]["reported"]
            is False
        )
        await slo_tasks._update_slo_alerts(alert, now=31_801)
        raw_state = await client.get(state_key)
        assert raw_state is not None
        assert (
            json.loads(raw_state)["active"]["pending_webhooks_high"]["reported"] is True
        )
    finally:
        await client.delete(state_key, lock_key)
        await client.aclose()
        await second_client.aclose()


def test_slo_monitor_uses_shared_global_metrics_and_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    async def apply_context(_db: FakeSession) -> None:
        calls.append("apply")

    async def get_metrics(_db: FakeSession, store_id: str | None) -> dict[str, int]:
        calls.append(("metrics", store_id))
        return {"pending_webhooks": 0}

    def thresholds() -> dict[str, int]:
        calls.append("thresholds")
        return {"pending_webhooks": 5}

    alerts = [
        {
            "code": "pending_webhooks_high",
            "severity": "critical",
            "value": 0,
            "threshold": 5,
        }
    ]
    context_changes: list[tuple[str | None, bool]] = []
    monkeypatch.setattr(slo_tasks, "AsyncSessionFactory", lambda: FakeSession())
    monkeypatch.setattr(slo_tasks, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(
        slo_tasks,
        "set_tenant_context",
        lambda store_id, is_admin: context_changes.append((store_id, is_admin)),
    )
    monkeypatch.setattr(slo_tasks, "_slo_metrics", get_metrics)
    monkeypatch.setattr(slo_tasks, "_slo_thresholds", thresholds)
    monkeypatch.setattr(slo_tasks, "_slo_alerts", lambda metrics, limits: alerts)

    async def update_alerts(current: list[dict[str, str | int]]) -> None:
        calls.append(current)

    monkeypatch.setattr(slo_tasks, "_update_slo_alerts", update_alerts)
    monkeypatch.setattr(
        slo_tasks,
        "run_in_worker_loop",
        lambda coro: asyncio.run(coro),
    )

    result = slo_tasks.monitor_ops_slo.run()

    assert result == {"metrics_checked": 1, "alerts": 1}
    assert calls == ["apply", ("metrics", None), "thresholds", alerts]
    assert context_changes == [(None, True), (None, False)]


# --- Public task interface with the real Sentry SDK -----------------------
#
# 2026-11-16 (PR #308 review): the tests above drive ``_update_slo_alerts``
# with a stubbed SDK. These run ``monitor_ops_slo`` itself, with the real
# ``sentry_sdk`` client and the production ``before_send`` scrubber, and only
# replace the network edge (transport) and the stores (database, Redis).

_SECRET = "s3cr3t-redis-pass"
_SECRET_URL = f"redis://:{_SECRET}@redis_state:6379/0"
_SENTRY_TEST_DSN = "https://public@sentry.invalid/1"

_Monitor = tuple[list[dict[str, int]], _SharedRedisState, list[int]]


class _CapturingTransport(Transport):
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            payload = item.payload.json
            if item.type == "event" and payload is not None:
                self.events.append(payload)


class _Retried(Exception):
    def __init__(self, countdown: int) -> None:
        super().__init__(countdown)
        self.countdown = countdown


def _metrics(**overrides: int) -> dict[str, int]:
    metrics = {metric: 0 for metric, _code, _severity in ops_router._SLO_ALERTS}
    metrics.update(overrides)
    return metrics


def _close_sentry() -> None:
    sentry_sdk.get_client().close(timeout=0)
    sentry_sdk.get_global_scope().set_client(None)


@pytest.fixture
def real_sentry(monkeypatch: pytest.MonkeyPatch) -> Iterator[_CapturingTransport]:
    monkeypatch.setattr(settings, "SENTRY_DSN", _SENTRY_TEST_DSN)
    sentry_sdk.init(
        dsn=_SENTRY_TEST_DSN,
        transport=_CapturingTransport,
        default_integrations=False,
        auto_enabling_integrations=False,
        before_send=observability._scrub_event,
        environment="production",
    )
    transport = sentry_sdk.get_client().transport
    assert isinstance(transport, _CapturingTransport)
    try:
        yield transport
    finally:
        _close_sentry()


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Monitor]:
    """Wire ``monitor_ops_slo`` to a metrics queue, shared Redis and a fake
    retry. Yields (metrics per run, shared Redis state, retry countdowns)."""
    runs: list[dict[str, int]] = []
    shared = _SharedRedisState()
    countdowns: list[int] = []

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    async def apply_context(_db: FakeSession) -> None:
        return None

    async def get_metrics(_db: FakeSession, store_id: str | None) -> dict[str, int]:
        assert store_id is None
        return runs.pop(0)

    async def get_worker_redis() -> _RedisClient:
        return _RedisClient(shared)

    def retry(*, exc: BaseException, countdown: int) -> _Retried:
        countdowns.append(countdown)
        return _Retried(countdown)

    monkeypatch.setattr(slo_tasks, "AsyncSessionFactory", lambda: FakeSession())
    monkeypatch.setattr(slo_tasks, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(slo_tasks, "_slo_metrics", get_metrics)
    monkeypatch.setattr(slo_tasks, "get_redis", get_worker_redis)
    monkeypatch.setattr(slo_tasks.monitor_ops_slo, "retry", retry)
    monkeypatch.setattr(
        slo_tasks,
        "_MONITOR_FAILURE_COOLDOWN",
        OncePer(slo_tasks.SLO_ALERT_COOLDOWN_SECONDS),
    )
    yield runs, shared, countdowns


def _slo_events(transport: _CapturingTransport) -> list[dict[str, Any]]:
    return [e for e in transport.events if "slo.alert_code" in e.get("tags", {})]


def test_monitor_emits_one_slo_event_with_stable_attributes(
    real_sentry: _CapturingTransport, monitor: _Monitor
) -> None:
    runs, _shared, countdowns = monitor
    limit = settings.SLO_MAX_PENDING_WEBHOOKS
    runs.extend(
        [
            _metrics(pending_webhooks=limit + 1),
            _metrics(pending_webhooks=limit + 2),
            _metrics(),
        ]
    )

    assert slo_tasks.monitor_ops_slo.run() == {"metrics_checked": 9, "alerts": 1}
    # Still breached on the next run: no duplicate event.
    slo_tasks.monitor_ops_slo.run()
    events = _slo_events(real_sentry)
    assert len(events) == 1, events
    event = events[0]
    assert event["message"] == "SLO threshold exceeded"
    assert event["level"] == "error"
    assert event["environment"] == "production"
    assert event["fingerprint"] == ["ops-slo", "pending_webhooks_high", "active"]
    assert {k: v for k, v in event["tags"].items() if k.startswith("slo.")} == {
        "slo.alert_code": "pending_webhooks_high",
        "slo.severity": "critical",
        "slo.state": "active",
    }
    assert event["contexts"]["slo"] == {
        "code": "pending_webhooks_high",
        "severity": "critical",
        "state": "active",
        "value": limit + 1,
        "threshold": limit,
    }

    slo_tasks.monitor_ops_slo.run()
    events = _slo_events(real_sentry)
    assert len(events) == 2, events
    recovery = events[1]
    assert recovery["message"] == "SLO threshold recovered"
    assert recovery["level"] == "info"
    assert recovery["tags"]["slo.state"] == "resolved"
    # Recovery is its own issue: it never regresses the active one.
    assert recovery["fingerprint"] == ["ops-slo", "pending_webhooks_high", "resolved"]
    assert countdowns == []


@pytest.mark.parametrize(
    ("metric", "code", "severity"),
    list(ops_router._SLO_ALERTS),
    ids=[code for _metric, code, _severity in ops_router._SLO_ALERTS],
)
def test_every_slo_code_maps_its_severity_to_a_sentry_level(
    real_sentry: _CapturingTransport,
    monitor: _Monitor,
    metric: str,
    code: str,
    severity: str,
) -> None:
    runs, _shared, _countdowns = monitor
    runs.append(_metrics(**{metric: ops_router._slo_thresholds()[metric] + 1}))

    slo_tasks.monitor_ops_slo.run()

    (event,) = _slo_events(real_sentry)
    assert event["tags"]["slo.alert_code"] == code
    assert event["tags"]["slo.severity"] == severity
    assert event["level"] == ("error" if severity == "critical" else "warning")


def test_runbook_lists_exactly_the_slo_alert_codes() -> None:
    """The Sentry rule is keyed on ``slo.alert_code``: renaming a code without
    updating the documented rule would silently stop its email."""
    runbook = (
        Path(__file__).resolve().parents[3] / "docs" / "DEPLOY_RUNBOOK.md"
    ).read_text(encoding="utf-8")
    section = runbook.split("<!-- slo-alert-codes:start -->", 1)[1].split(
        "<!-- slo-alert-codes:end -->", 1
    )[0]
    documented = dict(
        re.findall(r"^\| `([a-z_]+)` \| (critical|warning) \|", section, re.M)
    )
    assert documented == {
        code: severity for _metric, code, severity in ops_router._SLO_ALERTS
    }


def test_monitor_redis_down_reports_once_without_secrets_and_retries(
    real_sentry: _CapturingTransport,
    monitor: _Monitor,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runs, _shared, countdowns = monitor
    runs.extend([_metrics(pending_webhooks=99), _metrics(pending_webhooks=99)])

    async def redis_down() -> None:
        raise RedisConnectionError(f"Error connecting to {_SECRET_URL}")

    monkeypatch.setattr(slo_tasks, "get_redis", redis_down)
    caplog.set_level(logging.DEBUG, logger=slo_tasks.logger.name)

    for _ in range(2):
        with pytest.raises(_Retried):
            slo_tasks.monitor_ops_slo.run()

    assert countdowns == [60, 60]
    assert _slo_events(real_sentry) == []
    # One failure notice per cooldown window, not one per run.
    assert len(real_sentry.events) == 1, real_sentry.events
    failure = real_sentry.events[0]
    assert failure["exception"]["values"][0]["value"] == "Critical SLO monitor failed"
    assert failure["contexts"]["shifty"] == {
        "component": "ops_slo_monitor",
        "error_type": "ConnectionError",
    }
    assert _SECRET not in json.dumps(real_sentry.events)
    assert _SECRET not in caplog.text


def test_monitor_broker_down_on_retry_still_reports_the_failure(
    real_sentry: _CapturingTransport,
    monitor: _Monitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RabbitMQ down: publishing the retry fails, but the failure notice is
    already queued in Sentry and the task fails fast instead of hanging."""
    runs, _shared, _countdowns = monitor
    runs.append(_metrics())

    async def redis_down() -> None:
        raise RedisConnectionError("Error connecting to redis_state:6379")

    def broker_down(*, exc: BaseException, countdown: int) -> None:
        raise KombuOperationalError("[Errno 111] Connection refused")

    monkeypatch.setattr(slo_tasks, "get_redis", redis_down)
    monkeypatch.setattr(slo_tasks.monitor_ops_slo, "retry", broker_down)

    started = time.monotonic()
    with pytest.raises(KombuOperationalError):
        slo_tasks.monitor_ops_slo.run()

    assert time.monotonic() - started < 5
    assert len(real_sentry.events) == 1
    assert real_sentry.events[0]["exception"]["values"][0]["value"] == (
        "Critical SLO monitor failed"
    )


def test_monitor_sentry_capture_raising_keeps_transition_pending(
    real_sentry: _CapturingTransport,
    monitor: _Monitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs, shared, countdowns = monitor
    runs.extend([_metrics(dead_letter_webhooks_24h=1)] * 2)
    real_capture = sentry_sdk.capture_message

    def broken_capture(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("sentry transport exploded")

    monkeypatch.setattr(sentry_sdk, "capture_message", broken_capture)
    with pytest.raises(_Retried):
        slo_tasks.monitor_ops_slo.run()

    assert countdowns == [60]
    pending = shared.active["dead_letter_webhooks"]
    assert pending["reported"] is False
    assert "pending_token" not in pending
    assert shared.locks == {}

    # SDK back, after the per-code retry cooldown: the transition goes out once.
    monkeypatch.setattr(sentry_sdk, "capture_message", real_capture)
    pending["next_attempt_at"] = 0
    slo_tasks.monitor_ops_slo.run()
    assert shared.active["dead_letter_webhooks"]["reported"] is True
    assert [e["tags"]["slo.alert_code"] for e in _slo_events(real_sentry)] == [
        "dead_letter_webhooks"
    ]


def test_monitor_sdk_dropping_the_event_is_not_acked(
    monitor: _Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``before_send`` (or sampling) dropping the event makes the SDK return
    ``None``: the transition must stay pending, not count as reported."""
    runs, shared, countdowns = monitor
    runs.append(_metrics(failed_webhooks=10_000))
    monkeypatch.setattr(settings, "SENTRY_DSN", _SENTRY_TEST_DSN)
    sentry_sdk.init(
        dsn=_SENTRY_TEST_DSN,
        transport=_CapturingTransport,
        default_integrations=False,
        auto_enabling_integrations=False,
        before_send=lambda _event, _hint: None,
    )
    try:
        with pytest.raises(_Retried):
            slo_tasks.monitor_ops_slo.run()
    finally:
        _close_sentry()

    assert countdowns == [60]
    assert shared.active["failed_webhooks_high"]["reported"] is False
    assert shared.locks == {}


def test_monitor_does_not_wait_for_a_hung_sentry_and_ack_is_not_delivery(
    monitor: _Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real HTTP transport queues events for a background thread: a hung
    Sentry does not block the Celery worker. The flip side: a queue overflow
    drops events after the SDK returned an id, so an ACK in Redis means
    "handed to the SDK", never "delivered" and never "emailed"."""
    runs, shared, _countdowns = monitor
    thresholds = ops_router._slo_thresholds()
    runs.append(
        _metrics(
            **{
                metric: thresholds[metric] + 1
                for metric, _code, _severity in ops_router._SLO_ALERTS
            }
        )
    )
    sent: list[bytes] = []

    def hung_send(_self: HttpTransport, body: bytes, *_args: Any, **_kw: Any) -> None:
        sent.append(body)
        time.sleep(3)

    dsn = "http://public@127.0.0.1:9/1"
    monkeypatch.setattr(HttpTransport, "_send_request", hung_send)
    monkeypatch.setattr(settings, "SENTRY_DSN", dsn)
    sentry_sdk.init(
        dsn=dsn,
        default_integrations=False,
        auto_enabling_integrations=False,
        transport_queue_size=1,
    )
    try:
        assert isinstance(sentry_sdk.get_client().transport, HttpTransport)
        started = time.monotonic()
        result = slo_tasks.monitor_ops_slo.run()
        elapsed = time.monotonic() - started
    finally:
        _close_sentry()

    codes = [code for _metric, code, _severity in ops_router._SLO_ALERTS]
    assert result["alerts"] == len(codes)
    assert elapsed < 2, f"the monitor waited for Sentry ({elapsed:.1f} s)"
    assert all(shared.active[code]["reported"] is True for code in codes)
    # One request in flight plus a one-slot queue: the rest were dropped
    # after the SDK handed back an event id.
    assert len(sent) <= 2
