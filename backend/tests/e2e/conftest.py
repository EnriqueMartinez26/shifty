"""Fixtures de los flujos de pago de punta a punta contra el emulador de MP.

La app bajo prueba es la de integracion (SQLite en memoria, cliente ASGI,
misma sesion inyectada): se reusan sus fixtures. Lo que cambia es Mercado
Pago: en vez de un monkeypatch del cliente, el backend habla por HTTP real
con ``tests/e2e/mp_emulator.py`` levantado en un hilo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.circuit_breaker import AsyncCircuitBreaker
from core.config import settings
from tests.e2e.mp_emulator import EmulatorState, RunningEmulator, run_in_thread
from tests.integration import conftest as integracion
from tests.integration.test_mails_al_cliente import Buzon

# Las mismas fixtures de la app de integracion (una base SQLite por test).
test_engine = integracion.test_engine
test_session = integracion.test_session
client = integracion.client

WEBHOOK_SECRET = "whsec-e2e-emulador"
COLLECTOR_ID = "123456789"
# Umbral chico para que el test del breaker no tenga que fallar cinco veces,
# y recuperacion de 1 s para probar el half-open sin esperar 30.
BREAKER_THRESHOLD = 3
BREAKER_RECOVERY_SECONDS = 1

Json = dict[str, Any]


class Emu:
    """Cliente de control del emulador: todo por HTTP, como un operador."""

    def __init__(self, running: RunningEmulator, http: httpx.AsyncClient) -> None:
        self.url = running.url
        self.http = http

    async def state(self) -> Json:
        res = await self.http.get("/_emu/state")
        assert res.status_code == 200, res.text
        return cast(Json, res.json())

    async def calls(
        self, path: str | None = None, method: str | None = None
    ) -> list[Json]:
        return [
            call
            for call in (await self.state())["calls"]
            if (path is None or call["path"] == path)
            and (method is None or call["method"] == method)
        ]

    async def only_preference(self) -> Json:
        prefs = list((await self.state())["preferences"].values())
        assert len(prefs) == 1, prefs
        return cast(Json, prefs[0])

    async def pay(self, preference_id: str, **overrides: Any) -> httpx.Response:
        return await self.http.post(f"/_emu/pay/{preference_id}", json=overrides)

    async def set_status(self, payment_id: str, status: str) -> None:
        res = await self.http.post(
            f"/_emu/payment/{payment_id}/status", json={"status": status}
        )
        assert res.status_code == 200, res.text

    async def webhook(self, payment_id: str, **options: Any) -> Json:
        """Webhook firmado SIN entregar: la app corre en el cliente ASGI."""
        res = await self.http.post(
            "/_emu/send_webhook",
            json={"payment_id": payment_id, "deliver": False, **options},
        )
        assert res.status_code == 200, res.text
        return cast(Json, res.json())

    async def fault(self, **faults: Any) -> None:
        res = await self.http.post("/_emu/fault", json=faults)
        assert res.status_code == 200, res.text


@pytest.fixture
def buzon(monkeypatch: pytest.MonkeyPatch) -> Buzon:
    """Sink de correo en memoria: sin SMTP real y con los mails a la vista."""
    capturado = Buzon()
    monkeypatch.setattr(tasks, "_send_email", capturado)
    return capturado


@pytest_asyncio.fixture
async def mp(
    monkeypatch: pytest.MonkeyPatch, test_session: AsyncSession, buzon: Buzon
) -> AsyncIterator[Emu]:
    state = EmulatorState(collector_id=COLLECTOR_ID, webhook_secret=WEBHOOK_SECRET)

    def anotar_transaccion(call: Json) -> None:
        # Corre en el hilo del emulador mientras el backend espera la
        # respuesta: dice si la sesion de la app tenia una transaccion abierta
        # durante la llamada externa (regla 5).
        call["in_tx"] = test_session.in_transaction()

    state.on_call = anotar_transaccion
    with run_in_thread(state) as running:
        monkeypatch.setattr(settings, "MERCADOPAGO_API_BASE_URL", running.url)
        monkeypatch.setattr(
            payments_service,
            "_mercadopago_breaker",
            AsyncCircuitBreaker(
                name="mercadopago",
                failure_threshold=BREAKER_THRESHOLD,
                recovery_timeout_seconds=BREAKER_RECOVERY_SECONDS,
            ),
        )
        monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "emu-client")
        monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "emu-secret")
        monkeypatch.setattr(
            settings, "MERCADOPAGO_OAUTH_REDIRECT_URI", "https://api.test/callback"
        )
        async with httpx.AsyncClient(base_url=running.url, timeout=30.0) as http:
            yield Emu(running, http)
