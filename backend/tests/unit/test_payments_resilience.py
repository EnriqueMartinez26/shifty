import pytest

from core.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError
import modules.payments.service as payments_service


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current


@pytest.mark.asyncio
async def test_mercadopago_circuit_breaker_opens_for_transient_failures(
    monkeypatch,
) -> None:
    breaker = AsyncCircuitBreaker(
        name="mercadopago-test",
        failure_threshold=2,
        recovery_timeout_seconds=30,
        clock=FakeClock(),
    )
    monkeypatch.setattr(payments_service, "_mercadopago_breaker", breaker)

    async def transient_failure(*args, **kwargs):
        raise payments_service.MercadoPagoAPIError(
            "timeout",
            status_code=504,
            transient=True,
        )

    monkeypatch.setattr(
        payments_service, "_perform_mercadopago_request", transient_failure
    )

    with pytest.raises(payments_service.MercadoPagoAPIError):
        await payments_service._mercadopago_api_request(
            "token",
            method="GET",
            path="/v1/payments/test",
        )

    with pytest.raises(payments_service.MercadoPagoAPIError):
        await payments_service._mercadopago_api_request(
            "token",
            method="GET",
            path="/v1/payments/test",
        )

    snapshot = await breaker.snapshot()
    assert snapshot["state"] == "open"

    with pytest.raises(CircuitBreakerOpenError):
        await payments_service._mercadopago_api_request(
            "token",
            method="GET",
            path="/v1/payments/test",
        )


@pytest.mark.asyncio
async def test_mercadopago_circuit_breaker_ignores_non_transient_failures(
    monkeypatch,
) -> None:
    breaker = AsyncCircuitBreaker(
        name="mercadopago-test",
        failure_threshold=1,
        recovery_timeout_seconds=30,
        clock=FakeClock(),
    )
    monkeypatch.setattr(payments_service, "_mercadopago_breaker", breaker)

    async def auth_failure(*args, **kwargs):
        raise payments_service.MercadoPagoAPIError(
            "bad token",
            status_code=401,
            transient=False,
        )

    monkeypatch.setattr(payments_service, "_perform_mercadopago_request", auth_failure)

    with pytest.raises(payments_service.MercadoPagoAPIError):
        await payments_service._mercadopago_api_request(
            "token",
            method="GET",
            path="/v1/payments/test",
        )

    snapshot = await breaker.snapshot()
    assert snapshot["state"] == "closed"
    assert snapshot["consecutive_failures"] == 0
