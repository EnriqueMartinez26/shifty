"""Rafaga: dos entregas a la vez del MISMO contracargo de otro pago de MP.

Re-revision de la PR #113 (S2). Una sena registrada a mano a la que MP le
avisa el contracargo del pago de su link (``_avisar_reverso_de_otro_pago``).
MP reentrega el evento con otro ``event_id`` y las dos entregas llegan juntas.
La deduplicacion por ``reverso:<id>:<estado>`` lee el outbox DESPUES de que el
webhook lockea turno -> pago (regla 7): las dos entregas se serializan sobre
la fila del turno y la segunda ve la fila que commiteo la primera. Lo que se
fija: cero 5xx, las dos procesadas, UN aviso en el outbox y UN reporte a
Sentry, y el cobro sigue ``manual_confirmed``. SQLite no lo puede probar.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.processing as processing
import modules.payments.service as payments_service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)
from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.test_pg_cancelar_con_cobro_vivo import (
    _cobros,
    _eventos,
    _MercadoPago,
)

pytestmark = pytest.mark.postgres

ENTREGAS = 2
EVENTO = "payment.reversal_of_other_payment"


async def _sena_registrada_a_mano(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> tuple[str, str]:
    """Turno del panel con link de MP y el cobro confirmado a mano.
    Devuelve la tienda y el turno."""
    slug = "reversa-pg-rafaga"
    store, admin = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(admin),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Reversa",
            "client_phone": "+5491156200001",
            "idempotency_key": f"{slug}-alta",
        },
    )
    assert alta.status_code == 201, alta.text
    turno = str(alta.json()["public_id"])
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(admin)
    )
    assert link.status_code == 200, link.text
    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(admin), json={}
    )
    assert confirmado.status_code == 200, confirmado.text
    return store, turno


@pytest.mark.asyncio
async def test_dos_entregas_del_mismo_contracargo_avisan_una_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    reportes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        processing,
        "report_exception",
        lambda exc, **contexto: reportes.append(contexto),
    )
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    store, turno = await _sena_registrada_a_mano(client, app_sessions)
    cobro = (await _cobros(owner_engine))[turno]
    assert cobro["pago"] == "manual_confirmed", cobro
    (_preferencia, referencia) = mp.creadas[-1]
    mp.remotos["mp-cb"] = {
        "id": "mp-cb",
        "status": "charged_back",
        "external_reference": referencia,
        "metadata": {"appointment_id": turno, "payment_id": cobro["pago_id"]},
        "transaction_amount": cobro["importe"],
        "currency_id": "ARS",
    }

    respuestas: list[Response] = await asyncio.gather(
        *(
            client.post(
                f"/payments/webhooks/mercadopago?store_id={store}",
                json={"id": f"evt-cb-{n}", "type": "payment", "data": {"id": "mp-cb"}},
                headers=webhook_signature_headers(
                    secret="secret-demo",
                    data_id="mp-cb",
                    request_id=f"req-cb-{n}",
                    ts="0",
                ),
            )
            for n in range(ENTREGAS)
        )
    )

    assert all(r.status_code == 200 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas
    ]
    aplicados = [r.json().get("data", r.json())["applied"] for r in respuestas]
    assert aplicados == [True] * ENTREGAS, aplicados
    avisos = [p for e, p in await _eventos(owner_engine) if e == EVENTO]
    assert [p["aviso"] for p in avisos] == ["reverso:mp-cb:charged_back"], avisos
    assert len(reportes) == 1, reportes
    final = (await _cobros(owner_engine))[turno]
    assert final["pago"] == "manual_confirmed", final
