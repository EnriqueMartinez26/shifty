import pytest
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, cast

from core.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError
from core.config import settings
from core.crypto import decrypt_secret, encrypt_secret
import modules.payments.service as payments_service
from modules.payments.model import PaymentGatewayConfig


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current


@pytest.mark.asyncio
async def test_mercadopago_circuit_breaker_opens_for_transient_failures(
    monkeypatch: MonkeyPatch,
) -> None:
    breaker = AsyncCircuitBreaker(
        name="mercadopago-test",
        failure_threshold=2,
        recovery_timeout_seconds=30,
        clock=FakeClock(),
    )
    monkeypatch.setattr(payments_service, "_mercadopago_breaker", breaker)

    async def transient_failure(*args: Any, **kwargs: Any) -> object:
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
    monkeypatch: MonkeyPatch,
) -> None:
    breaker = AsyncCircuitBreaker(
        name="mercadopago-test",
        failure_threshold=1,
        recovery_timeout_seconds=30,
        clock=FakeClock(),
    )
    monkeypatch.setattr(payments_service, "_mercadopago_breaker", breaker)

    async def auth_failure(*args: Any, **kwargs: Any) -> object:
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


@pytest.mark.asyncio
async def test_store_request_refreshes_oauth_token_after_401(
    monkeypatch: MonkeyPatch,
) -> None:
    config = PaymentGatewayConfig(
        store_id="store-1",
        provider="mercadopago",
        encrypted_access_token=encrypt_secret("expired-token") or "expired-token",
        encrypted_refresh_token=encrypt_secret("refresh-token") or "refresh-token",
        connection_mode="oauth",
    )

    async def fake_get_gateway_config(
        db: AsyncSession, store_id: str
    ) -> PaymentGatewayConfig:
        assert store_id == "store-1"
        return config

    async def fake_api_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, str]:
        if access_token == "expired-token":
            raise payments_service.MercadoPagoAPIError(
                "expired",
                status_code=401,
                transient=False,
            )
        return {"status": "ok", "path": path}

    async def fake_refresh(
        db: AsyncSession,
        *,
        config: PaymentGatewayConfig,
        persist: object = None,  # hook de persistencia del job (S-02)
    ) -> PaymentGatewayConfig:
        config.encrypted_access_token = encrypt_secret("fresh-token") or "fresh-token"
        config.encrypted_refresh_token = (
            encrypt_secret("fresh-refresh-token") or "fresh-refresh-token"
        )
        return config

    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings,
        "MERCADOPAGO_OAUTH_REDIRECT_URI",
        "https://api.test/callback",
    )
    monkeypatch.setattr(
        payments_service, "_get_gateway_config", fake_get_gateway_config
    )
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_api_request)
    monkeypatch.setattr(
        payments_service, "refresh_mercadopago_oauth_connection", fake_refresh
    )

    result = await payments_service._mercadopago_api_request_for_store(
        cast(AsyncSession, object()),
        store_id="store-1",
        method="GET",
        path="/v1/payments/123",
    )

    assert result == {"status": "ok", "path": "/v1/payments/123"}
    assert decrypt_secret(config.encrypted_access_token) == "fresh-token"


@pytest.mark.asyncio
async def test_el_lock_del_job_invalida_la_conexion_si_no_puede_soltarlo() -> None:
    """S-02: si pg_advisory_unlock falla, la conexion no vuelve al pool con el
    lock de sesion tomado: se invalida y Postgres suelta el lock al cerrarla."""
    from modules.payments.jobs import JOB_LOCK_NAMESPACE, _release_job_lock

    class ConexionQueFalla:
        def __init__(self) -> None:
            self.invalidada = False

        async def execute(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("unlock fallo")

        async def invalidate(self) -> None:
            self.invalidada = True

    conexion = ConexionQueFalla()
    await _release_job_lock(
        cast(Any, conexion),
        {"namespace": JOB_LOCK_NAMESPACE, "clave": "job:prueba"},
    )
    assert conexion.invalidada


def test_el_lock_del_job_usa_la_forma_de_dos_int4() -> None:
    """S-02: (namespace, id) no comparte espacio con los locks de un bigint
    (pg_advisory_xact_lock(hashtext('ledger:...')) del fiado)."""
    import inspect

    from modules.payments import jobs

    fuente = inspect.getsource(jobs._exclusive_job) + inspect.getsource(
        jobs._release_job_lock
    )
    assert "pg_try_advisory_lock(:namespace, hashtext(:clave))" in fuente
    assert "pg_advisory_unlock(:namespace, hashtext(:clave))" in fuente
    assert -(2**31) <= jobs.JOB_LOCK_NAMESPACE < 2**31
