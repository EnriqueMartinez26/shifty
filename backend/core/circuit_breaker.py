from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class CircuitBreakerOpenError(RuntimeError):
    def __init__(self, name: str, retry_after_seconds: float) -> None:
        self.name = name
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(
            f"Circuit breaker '{name}' abierto. Reintentar en {self.retry_after_seconds:.1f}s"
        )


class AsyncCircuitBreaker:
    """
    Circuit breaker in-memory por proceso.

    Protege dependencias externas para evitar cascadas de timeout cuando el
    proveedor ya esta caido. No reemplaza una solucion distribuida, pero baja
    mucho la presion sobre el proceso actual.
    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int,
        recovery_timeout_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock or time.monotonic

        self._state = "closed"
        self._consecutive_failures = 0
        self._retry_at = 0.0
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    async def call(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        should_record_failure: Callable[[Exception], bool] | None = None,
    ) -> Any:
        probe_call = await self._before_call()

        try:
            result = await operation()
        except Exception as exc:
            record_failure = (
                should_record_failure(exc) if should_record_failure else True
            )
            if record_failure:
                await self._mark_failure(probe_call)
            else:
                await self._mark_success(probe_call)
            raise

        await self._mark_success(probe_call)
        return result

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "consecutive_failures": self._consecutive_failures,
                "retry_at": self._retry_at,
                "probe_in_flight": self._probe_in_flight,
            }

    async def _before_call(self) -> bool:
        async with self._lock:
            now = self._clock()

            if self._state == "open":
                if now < self._retry_at:
                    raise CircuitBreakerOpenError(self.name, self._retry_at - now)
                self._state = "half_open"

            if self._state == "half_open":
                if self._probe_in_flight:
                    raise CircuitBreakerOpenError(
                        self.name, max(0.0, self._retry_at - now)
                    )
                self._probe_in_flight = True
                return True

            return False

    async def _mark_success(self, probe_call: bool) -> None:
        async with self._lock:
            self._state = "closed"
            self._consecutive_failures = 0
            if probe_call:
                self._probe_in_flight = False

    async def _mark_failure(self, probe_call: bool) -> None:
        async with self._lock:
            if probe_call or self._state == "half_open":
                self._open_circuit()
                self._probe_in_flight = False
                return

            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open_circuit()

    def _open_circuit(self) -> None:
        self._state = "open"
        self._retry_at = self._clock() + self.recovery_timeout_seconds
        self._consecutive_failures = self.failure_threshold
