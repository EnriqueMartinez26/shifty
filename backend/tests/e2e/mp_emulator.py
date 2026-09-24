"""Emulador de Mercado Pago para pruebas de punta a punta (sin credenciales).

Emula SOLO lo que Shifty usa de la API (``modules/payments/service.py``):
preferencias de Checkout Pro, consulta y busqueda de pagos, reembolsos y el
token OAuth. Suma endpoints de control bajo ``/_emu`` para simular lo que en
la vida real hace el cliente o Mercado Pago: pagar un link, cambiar el estado
de un pago, mandar un webhook firmado e inyectar fallas.

Cada ``create_app()`` tiene su propio ``EmulatorState``: nada se comparte
entre instancias. ``app`` existe solo para ``uvicorn tests.e2e.mp_emulator:app``
(ver README.md de esta carpeta).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import itertools
import os
import random
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

Json = dict[str, Any]


@dataclass
class Faults:
    """Fallas inyectables; valen para la API emulada, nunca para ``/_emu``."""

    latency_ms: int = 0
    error_rate: float = 0.0
    error_status: int = 500
    unauthorized_once: bool = False
    down: bool = False


@dataclass
class EmulatorState:
    collector_id: str = "123456789"
    webhook_secret: str | None = None
    preferences: dict[str, Json] = field(default_factory=dict)
    payments: dict[str, Json] = field(default_factory=dict)
    refunds: list[Json] = field(default_factory=list)
    calls: list[Json] = field(default_factory=list)
    revoked_tokens: set[str] = field(default_factory=set)
    used_refresh_tokens: set[str] = field(default_factory=set)
    faults: Faults = field(default_factory=Faults)
    # Se llama en el hilo del emulador con cada request a la API emulada,
    # mientras el llamador espera la respuesta (p. ej. para mirar su sesion).
    on_call: Callable[[Json], None] | None = None
    rng: random.Random = field(default_factory=lambda: random.Random(0))
    ids: Iterator[int] = field(default_factory=lambda: itertools.count(1_000_000_001))

    def reset(self) -> None:
        fresh = EmulatorState(
            collector_id=self.collector_id, webhook_secret=self.webhook_secret
        )
        self.__dict__.update(fresh.__dict__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now().isoformat(timespec="milliseconds")


def _error(status: int, error: str, message: str) -> JSONResponse:
    # Misma forma que los errores de la API real.
    return JSONResponse(
        {"message": message, "error": error, "status": status, "cause": []},
        status_code=status,
    )


def _public(item: Json) -> Json:
    """Sin los campos internos del emulador (prefijo ``_``)."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def preference_expired(pref: Json) -> bool:
    limite = pref.get("expiration_date_to")
    if not pref.get("expires") or not isinstance(limite, str):
        return False
    vence = datetime.fromisoformat(limite)
    if vence.tzinfo is None:
        # MP interpreta sin offset como hora local de la cuenta; aca, UTC.
        vence = vence.replace(tzinfo=timezone.utc)
    return vence <= _now()


def sign_webhook(
    *, secret: str, data_id: str, request_id: str, ts: int
) -> dict[str, str]:
    """Headers de firma de un webhook, con el manifest que documenta MP."""
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={v1}", "x-request-id": request_id}


class PayRequest(BaseModel):
    amount: float | None = None
    collector_id: str | None = None
    currency_id: str | None = None
    status: str = "approved"
    status_detail: str | None = None
    force: bool = False


class StatusRequest(BaseModel):
    status: str
    status_detail: str | None = None


class WebhookRequest(BaseModel):
    payment_id: str
    target_url: str | None = None
    secret: str | None = None
    event_id: str | None = None
    request_id: str | None = None
    action: str = "payment.updated"
    ts: int | None = None
    ts_offset_seconds: int = 0
    tamper: bool = False
    deliver: bool = True


class FaultRequest(BaseModel):
    latency_ms: int | None = None
    error_rate: float | None = None
    error_status: int | None = None
    unauthorized_once: bool | None = None
    down: bool | None = None


def create_app(state: EmulatorState | None = None) -> FastAPI:
    st = state or EmulatorState()
    app = FastAPI(title="Mercado Pago emulator", docs_url=None, redoc_url=None)
    app.state.emu = st

    async def gate(
        request: Request, body: Json | None = None, *, auth: bool = True
    ) -> JSONResponse | None:
        """Registra la llamada y aplica fallas y autenticacion."""
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
        call: Json = {
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "token": token,
            "json": body,
            "at": _stamp(),
        }
        st.calls.append(call)
        if st.on_call is not None:
            st.on_call(call)
        f = st.faults
        if f.latency_ms:
            await asyncio.sleep(f.latency_ms / 1000)
        if f.down:
            return _error(503, "service_unavailable", "emulator down")
        if f.error_rate and st.rng.random() < f.error_rate:
            return _error(f.error_status, "internal_error", "emulated failure")
        if not auth:
            return None
        if not token or token in st.revoked_tokens:
            return _error(401, "unauthorized", "invalid access token")
        if f.unauthorized_once:
            # El token queda invalido: el reintento tiene que traer otro.
            f.unauthorized_once = False
            st.revoked_tokens.add(token)
            return _error(401, "unauthorized", "expired access token")
        return None

    async def json_body(request: Request) -> Json:
        try:
            data = await request.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # --- API emulada -------------------------------------------------------

    @app.post("/checkout/preferences")
    async def create_preference(request: Request) -> JSONResponse:
        body = await json_body(request)
        if denied := await gate(request, body):
            return denied
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return _error(400, "invalid_items", "items must not be empty")
        pref_id = f"{st.collector_id}-{secrets.token_hex(12)}"
        pref: Json = {
            **body,
            "id": pref_id,
            "collector_id": int(st.collector_id),
            "date_created": _stamp(),
            "init_point": (
                f"https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id={pref_id}"
            ),
            "sandbox_init_point": (
                "https://sandbox.mercadopago.com.ar/checkout/v1/redirect"
                f"?pref_id={pref_id}"
            ),
        }
        st.preferences[pref_id] = pref
        return JSONResponse(pref, status_code=201)

    @app.put("/checkout/preferences/{pref_id}")
    async def update_preference(pref_id: str, request: Request) -> JSONResponse:
        body = await json_body(request)
        if denied := await gate(request, body):
            return denied
        if pref_id not in st.preferences:
            return _error(404, "not_found", "preference not found")
        st.preferences[pref_id].update(body)
        return JSONResponse(st.preferences[pref_id])

    # /search va antes de /{payment_id}: si no, "search" matchea como id.
    @app.get("/v1/payments/search")
    async def search_payments(request: Request) -> JSONResponse:
        if denied := await gate(request):
            return denied
        ref = request.query_params.get("external_reference")
        found = [
            _public(p)
            for p in st.payments.values()
            if ref is None or p.get("external_reference") == ref
        ]
        found.sort(
            key=lambda p: str(p["date_created"]),
            reverse=request.query_params.get("criteria", "desc") == "desc",
        )
        paging = {"total": len(found), "limit": 30, "offset": 0}
        return JSONResponse({"paging": paging, "results": found})

    @app.get("/v1/payments/{payment_id}")
    async def get_payment(payment_id: str, request: Request) -> JSONResponse:
        if denied := await gate(request):
            return denied
        if payment_id not in st.payments:
            return _error(404, "not_found", "Payment not found")
        return JSONResponse(_public(st.payments[payment_id]))

    @app.post("/v1/payments/{payment_id}/refunds")
    async def refund_payment(payment_id: str, request: Request) -> JSONResponse:
        body = await json_body(request)
        if denied := await gate(request, body):
            return denied
        payment = st.payments.get(payment_id)
        if payment is None:
            return _error(404, "not_found", "Payment not found")
        total = Decimal(str(payment["transaction_amount"]))
        amount = Decimal(str(body.get("amount") or total))
        refund = {
            "id": next(st.ids),
            "payment_id": int(payment_id),
            "amount": float(amount),
            "status": "approved",
            "date_created": _stamp(),
        }
        st.refunds.append(refund)
        if amount >= total:
            payment["status"], payment["status_detail"] = "refunded", "refunded"
        return JSONResponse(refund, status_code=201)

    @app.post("/oauth/token")
    async def oauth_token(request: Request) -> JSONResponse:
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        shown = {k: v for k, v in form.items() if k != "client_secret"}
        if denied := await gate(request, shown, auth=False):
            return denied
        if not form.get("client_id") or not form.get("client_secret"):
            return _error(400, "invalid_client", "missing client credentials")
        grant = form.get("grant_type")
        if grant == "refresh_token":
            refresh = form.get("refresh_token", "")
            if not refresh or refresh in st.used_refresh_tokens:
                return _error(400, "invalid_grant", "invalid refresh_token")
            # MP rota el refresh token: el usado deja de servir.
            st.used_refresh_tokens.add(refresh)
        elif grant != "authorization_code" or not form.get("code"):
            return _error(400, "invalid_grant", "unsupported grant")
        n = next(st.ids)
        return JSONResponse(
            {
                "access_token": f"APP_USR-EMU-{n}-{st.collector_id}",
                "token_type": "Bearer",
                "expires_in": 15552000,
                "scope": "offline_access read write",
                "user_id": int(st.collector_id),
                "refresh_token": f"TG-EMU-{n}-{st.collector_id}",
                "public_key": f"APP_USR-PUB-EMU-{n}",
                "live_mode": False,
            }
        )

    # --- Control del emulador ---------------------------------------------

    @app.post("/_emu/pay/{pref_id}")
    async def emu_pay(pref_id: str, data: PayRequest) -> JSONResponse:
        """El cliente paga el link: crea el pago como lo haria Checkout Pro."""
        pref = st.preferences.get(pref_id)
        if pref is None:
            return _error(404, "not_found", "preference not found")
        if preference_expired(pref) and not data.force:
            return _error(409, "preference_expired", "checkout expired")
        items = pref.get("items") or []
        total = sum(Decimal(str(i["unit_price"])) * i["quantity"] for i in items)
        amount = data.amount if data.amount is not None else float(total)
        now = _stamp()
        payment_id = next(st.ids)
        payment: Json = {
            "id": payment_id,
            "status": data.status,
            "status_detail": data.status_detail or "accredited",
            "external_reference": pref.get("external_reference"),
            "transaction_amount": amount,
            "currency_id": data.currency_id or (items[0].get("currency_id") or "ARS"),
            "collector_id": int(data.collector_id or st.collector_id),
            "metadata": pref.get("metadata") or {},
            "payer": pref.get("payer") or {},
            "date_created": now,
            "date_approved": now if data.status == "approved" else None,
            "live_mode": False,
            "_preference_id": pref_id,
            "_notification_url": pref.get("notification_url"),
        }
        st.payments[str(payment_id)] = payment
        return JSONResponse(payment, status_code=201)

    @app.post("/_emu/payment/{payment_id}/status")
    async def emu_status(payment_id: str, data: StatusRequest) -> JSONResponse:
        payment = st.payments.get(payment_id)
        if payment is None:
            return _error(404, "not_found", "Payment not found")
        payment["status"] = data.status
        payment["status_detail"] = data.status_detail or data.status
        return JSONResponse(payment)

    @app.post("/_emu/send_webhook")
    async def emu_send_webhook(data: WebhookRequest) -> JSONResponse:
        """Arma (y si ``deliver``, manda) el webhook firmado de un pago."""
        payment = st.payments.get(data.payment_id)
        secret = data.secret or st.webhook_secret
        if payment is None or not secret:
            return _error(400, "bad_request", "unknown payment or missing secret")
        target = data.target_url or payment.get("_notification_url")
        if not isinstance(target, str) or not target:
            return _error(400, "bad_request", "no notification_url")
        query = urlencode({"data.id": data.payment_id, "type": "payment"})
        url = f"{target}{'&' if '?' in target else '?'}{query}"
        ts = (data.ts or int(time.time())) + data.ts_offset_seconds
        request_id = data.request_id or secrets.token_hex(16)
        headers = sign_webhook(
            secret=secret, data_id=data.payment_id, request_id=request_id, ts=ts
        )
        if data.tamper:
            headers["x-signature"] = headers["x-signature"][:-4] + "0000"
        body: Json = {
            "id": data.event_id or str(next(st.ids)),
            "action": data.action,
            "api_version": "v1",
            "type": "payment",
            "data": {"id": data.payment_id},
            "date_created": _stamp(),
            "live_mode": False,
            "user_id": st.collector_id,
        }
        delivered: Json | None = None
        if data.deliver:
            try:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    res = await http.post(url, json=body, headers=headers)
                delivered = {"status_code": res.status_code, "body": res.text[:2000]}
            except httpx.HTTPError as exc:
                delivered = {"status_code": None, "error": type(exc).__name__}
        return JSONResponse(
            {"url": url, "headers": headers, "body": body, "delivered": delivered}
        )

    @app.post("/_emu/fault")
    async def emu_fault(data: FaultRequest) -> JSONResponse:
        for key, value in data.model_dump(exclude_none=True).items():
            setattr(st.faults, key, value)
        return JSONResponse(asdict(st.faults))

    @app.get("/_emu/state")
    async def emu_state() -> JSONResponse:
        keys = ("preferences", "payments", "refunds", "calls")
        snapshot: Json = {key: getattr(st, key) for key in keys}
        snapshot["faults"] = asdict(st.faults)
        snapshot["revoked_tokens"] = sorted(st.revoked_tokens)
        return JSONResponse(snapshot)

    @app.post("/_emu/reset")
    async def emu_reset() -> JSONResponse:
        st.reset()
        return JSONResponse({"reset": True})

    return app


@dataclass
class RunningEmulator:
    url: str
    state: EmulatorState


@contextmanager
def run_in_thread(state: EmulatorState | None = None) -> Iterator[RunningEmulator]:
    """Levanta el emulador en un socket real (puerto libre) en otro hilo.

    Socket real y no ``ASGITransport``: asi el backend usa su propio cliente
    httpx, con sus timeouts, igual que contra Mercado Pago.
    """
    st = state or EmulatorState()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(st)
    config = uvicorn.Config(app, log_level="warning", ws="none", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, args=([sock],), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("el emulador de Mercado Pago no arranco")
        time.sleep(0.02)
    try:
        yield RunningEmulator(url=f"http://127.0.0.1:{port}", state=st)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


# Para `uvicorn tests.e2e.mp_emulator:app`: el secreto de los webhooks sale
# del entorno (el mismo webhook_secret que tiene la tienda en su gateway).
app = create_app(EmulatorState(webhook_secret=os.getenv("MP_EMU_WEBHOOK_SECRET")))
