"""El emulador de MP solo entrega webhooks a origenes configurados.

``/_emu/send_webhook`` con ``deliver`` hace un POST a una URL que viene del
pedido (``target_url``) o de la preferencia (``notification_url``). Sin una
lista de origenes, cualquiera que alcanzara ``/_emu`` (el README advierte que
con ``--host 0.0.0.0`` queda expuesto a la LAN) podia usarlo para pegarle a
cualquier host (CodeQL py/partial-ssrf, 2026-09-26).
"""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.mp_emulator import (
    DEFAULT_WEBHOOK_ORIGINS,
    EmulatorState,
    run_in_thread,
    webhook_delivery_base,
)

pytestmark = pytest.mark.integration

TOKEN = "APP_USR-EMU-TEST"


@pytest.mark.parametrize(
    ("target", "esperado"),
    [
        (
            "http://localhost/api/payments/webhooks/mercadopago?store_id=abc-123",
            "http://localhost/api/payments/webhooks/mercadopago?store_id=abc-123",
        ),
        ("http://LOCALHOST/api", "http://localhost/api"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        # Otro host, otro puerto u otro esquema: no es el origen permitido.
        ("http://evil.example/api", None),
        ("http://localhost.evil.example/api", None),
        ("http://localhost:8080/api", None),
        ("https://localhost/api", None),
        # Credenciales, fragmento o caracteres fuera de la ruta y la query.
        ("http://user@localhost/api", None),
        ("http://localhost/api#x", None),
        ("http://localhost/a b", None),
        ("http://localhost/a\\b", None),
        ("http://localhost:99999/api", None),
    ],
)
def test_solo_entrega_a_un_origen_permitido(target: str, esperado: str | None) -> None:
    assert webhook_delivery_base(target, DEFAULT_WEBHOOK_ORIGINS) == esperado


@pytest.mark.asyncio
async def test_send_webhook_rechaza_un_destino_fuera_de_la_lista() -> None:
    with run_in_thread(EmulatorState(webhook_secret="whsec")) as running:
        # Origen exacto del emulador (con su puerto): se entrega a si mismo.
        running.state.webhook_origins = (running.url,)
        async with httpx.AsyncClient(base_url=running.url, timeout=10.0) as http:
            pref = await http.post(
                "/checkout/preferences",
                json={"items": [{"unit_price": 10, "quantity": 1}]},
                headers={"authorization": f"Bearer {TOKEN}"},
            )
            assert pref.status_code == 201, pref.text
            pago = await http.post(f"/_emu/pay/{pref.json()['id']}", json={})
            assert pago.status_code == 201, pago.text
            payment_id = str(pago.json()["id"])
            llamadas_antes = len(running.state.calls)

            ajeno = await http.post(
                "/_emu/send_webhook",
                json={"payment_id": payment_id, "target_url": "http://evil.example/x"},
            )
            assert ajeno.status_code == 400, ajeno.text
            assert ajeno.json()["error"] == "target_not_allowed"

            propio = await http.post(
                "/_emu/send_webhook",
                json={
                    "payment_id": payment_id,
                    "target_url": f"{running.url}/checkout/preferences?store_id=s1",
                },
            )
            assert propio.status_code == 200, propio.text
            # Sin Bearer la API emulada responde 401, pero el POST llego.
            assert propio.json()["delivered"]["status_code"] == 401

    recibidas = running.state.calls[llamadas_antes:]
    assert [(c["method"], c["path"]) for c in recibidas] == [
        ("POST", "/checkout/preferences")
    ], "el destino rechazado no recibio nada; el permitido, un POST"
    assert recibidas[0]["query"] == f"store_id=s1&data.id={payment_id}&type=payment"
