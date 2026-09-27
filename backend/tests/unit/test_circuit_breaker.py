import pytest

from core.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failure_threshold_and_fast_fails() -> None:
    clock = FakeClock()
    breaker = AsyncCircuitBreaker(
        name="demo-upstream",
        failure_threshold=2,
        recovery_timeout_seconds=30,
        clock=clock,
    )

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    first_snapshot = await breaker.snapshot()
    assert first_snapshot["state"] == "closed"
    assert first_snapshot["consecutive_failures"] == 1

    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    second_snapshot = await breaker.snapshot()
    assert second_snapshot["state"] == "open"
    assert second_snapshot["consecutive_failures"] == 2

    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(fail)


@pytest.mark.asyncio
async def test_circuit_breaker_recovers_after_cooldown_and_successful_probe() -> None:
    clock = FakeClock()
    breaker = AsyncCircuitBreaker(
        name="demo-upstream",
        failure_threshold=1,
        recovery_timeout_seconds=15,
        clock=clock,
    )

    async def fail() -> None:
        raise RuntimeError("boom")

    async def succeed() -> str:
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    clock.advance(16)
    result = await breaker.call(succeed)

    assert result == "ok"
    snapshot = await breaker.snapshot()
    assert snapshot["state"] == "closed"
    assert snapshot["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_el_soft_time_limit_no_cuenta_como_falla_del_proveedor() -> None:
    """Revision de perf/f2b (2026-09-24): SoftTimeLimitExceeded es Exception y
    el breaker lo contaba como falla de Mercado Pago. Tampoco es un exito: una
    sonda cortada en half_open suelta la sonda sin cerrar ni abrir."""
    from celery.exceptions import SoftTimeLimitExceeded

    clock = FakeClock()
    breaker = AsyncCircuitBreaker(
        name="corte", failure_threshold=1, recovery_timeout_seconds=30, clock=clock
    )

    async def cortada() -> None:
        raise SoftTimeLimitExceeded()

    with pytest.raises(SoftTimeLimitExceeded):
        await breaker.call(cortada)
    cerrado = await breaker.snapshot()
    assert (cerrado["state"], cerrado["consecutive_failures"]) == ("closed", 0)

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    clock.advance(31)
    with pytest.raises(SoftTimeLimitExceeded):
        await breaker.call(cortada)
    sonda = await breaker.snapshot()
    assert sonda["state"] == "half_open"
    assert sonda["probe_in_flight"] is False
