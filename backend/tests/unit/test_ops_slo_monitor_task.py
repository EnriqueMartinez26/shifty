from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import sentry_sdk
import pytest
from redis.asyncio import from_url

from core.config import settings
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
            _key, code, token = args
            current = self.shared.active.get(code)
            if current and current.get("pending_token") == token:
                current.pop("pending_state", None)
                current.pop("pending_token", None)
                current.pop("pending_until", None)
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
                if not previous.get("pending_token") or pending_until <= now:
                    last_active = self.shared.last_active_at.get(code, 0)
                    if now - last_active >= cooldown:
                        previous["pending_state"] = "active"
                        previous["pending_token"] = claim
                        previous["pending_until"] = now + lease
                        previous["alert"] = alert
                        transitions.append(
                            json.dumps({"state": "active", "alert": alert, "token": claim})
                        )
            else:
                previous["alert"] = alert
            self.shared.active[code] = previous

        for code in self.shared.active.keys() - current.keys():
            previous = self.shared.active[code]
            if previous["reported"]:
                pending_until = previous.get("pending_until", 0)
                if (
                    previous.get("pending_state") != "resolved"
                    or pending_until <= now
                ):
                    previous["pending_state"] = "resolved"
                    previous["pending_token"] = claim
                    previous["pending_until"] = now + lease
                    transitions.append(
                        json.dumps(
                            {
                                "state": "resolved",
                                "alert": previous["alert"],
                                "token": claim,
                            }
                        )
                    )
            elif previous.get("pending_state") != "active" or previous.get(
                "pending_until", 0
            ) <= now:
                del self.shared.active[code]
        return transitions


def test_slo_monitor_deduplicates_across_workers_and_reports_recovery_recurrence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://sentry.invalid/1")
    scopes: list[_Scope] = []
    events: list[tuple[str, str, dict[str, Any]]] = []

    def new_scope() -> _Scope:
        scope = _Scope()
        scopes.append(scope)
        return scope

    def capture_message(message: str, *, level: str) -> None:
        scope = scopes[-1]
        events.append((message, level, scope.context["slo"]))

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


def test_slo_sentry_failure_releases_pending_transition_for_retry(monkeypatch) -> None:
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
    asyncio.run(slo_tasks._update_slo_alerts(alert, now=20_001))
    client_index[0] = 0
    asyncio.run(slo_tasks._update_slo_alerts(alert, now=20_002))

    assert calls == 2
    assert shared.active["dead_letter_webhooks"]["reported"] is True
    assert shared.locks == {}
def test_slo_monitor_reports_warning_severity_from_shared_alerts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://sentry.invalid/1")
    scope = _Scope()
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(sentry_sdk, "new_scope", lambda: scope)
    monkeypatch.setattr(
        sentry_sdk,
        "capture_message",
        lambda message, *, level: messages.append((message, level)),
    )
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
    monkeypatch,
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

    async def get_local_redis():
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
        assert await second_client.eval(
            slo_tasks._ACK_SLO_ALERT_TRANSITION,
            1,
            state_key,
            "pending_webhooks_high",
            "active",
            transition["token"],
            "30000",
        ) == 1
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

        # Start the ordinary monitor transitions with an empty state key.
        await client.delete(state_key)

        await slo_tasks._update_slo_alerts(alert, now=30_000)
        state = json.loads(await client.get(state_key))
        assert state["active"]["pending_webhooks_high"]["reported"] is True
        assert state["last_active_at"]["pending_webhooks_high"] == 30_000

        await slo_tasks._update_slo_alerts(alert, now=30_100)
        await slo_tasks._update_slo_alerts([], now=30_200)
        assert json.loads(await client.get(state_key))["active"] == {}

        # Recovery resets the active state; recurrence is held until cooldown.
        await slo_tasks._update_slo_alerts(alert, now=30_300)
        assert json.loads(await client.get(state_key))["active"][
            "pending_webhooks_high"
        ]["reported"] is False
        await slo_tasks._update_slo_alerts(alert, now=31_801)
        assert json.loads(await client.get(state_key))["active"]["pending_webhooks_high"]["reported"] is True
    finally:
        await client.delete(state_key, lock_key)
        await client.aclose()
        await second_client.aclose()


def test_slo_monitor_uses_shared_global_metrics_and_thresholds(monkeypatch) -> None:
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
