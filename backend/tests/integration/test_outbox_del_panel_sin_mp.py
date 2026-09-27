"""El boton "procesar outbox" del panel no sale a Mercado Pago.

2026-09-20, AUD2-B2-07: ``process_outbox_batch`` absorbio el paso de
vencimiento de preferencias (B1-04), que hace hasta
``PREFERENCE_EXPIRE_MAX_CLAIMS`` llamadas a Mercado Pago con un peor caso
declarado de 60 s cada una. Ese mismo ``process_outbox_batch`` es el cuerpo
del endpoint del panel ``POST /payments/outbox/process``: un clic dejaba el
request colgado varios minutos sosteniendo una conexion del pool, se pasaba
del timeout de nginx y le devolvia HTML/504 al front. El ``limit`` del
endpoint no gobierna ese paso, asi que no habia forma de acotarlo.

Sintoma reproducido abajo: el endpoint hacia el ``PUT /checkout/preferences``
dentro del request. El vencimiento no se pierde: lo hace el beat, que corre
cada minuto sobre el mismo evento del outbox.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.payments.jobs import process_outbox_batch
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_release_sin_mp_bajo_lock import (
    _MercadoPago,
    _evento,
    _turno_con_cobro,
)


@pytest.mark.asyncio
async def test_el_endpoint_del_panel_no_llama_a_mercado_pago(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "outbox-panel")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    assert mp.vencimientos == []

    respuesta = await client.post(
        "/payments/outbox/process", headers=auth_headers(token)
    )

    assert respuesta.status_code == 200, respuesta.text
    assert mp.vencimientos == [], (
        "el request del panel salio a Mercado Pago: hasta 8 llamadas de 60 s "
        "sosteniendo una conexion del pool y pasandose del timeout de nginx"
    )
    # El vencimiento queda para el beat, que corre cada minuto.
    evento = await _evento(test_session)
    assert evento.processed_at is None and evento.error is None
    # El resto del lote si se proceso en el request: el boton sigue sirviendo.
    assert respuesta.json()["processed"] >= 1, respuesta.json()


@pytest.mark.asyncio
async def test_el_beat_sigue_venciendo_el_link_que_el_panel_dejo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda: sacar el paso del request no puede dejar el link vivo para siempre."""
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "outbox-beat")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    respuesta = await client.post(
        "/payments/outbox/process", headers=auth_headers(token)
    )
    assert respuesta.status_code == 200, respuesta.text

    # Misma corrida que hace la tarea de Celery, sin store_id.
    resultado = await process_outbox_batch(test_session)

    assert mp.vencimientos == [False], "el PUT a MP corrio con una transaccion abierta"
    assert resultado["failed"] == 0, resultado
    evento = await _evento(test_session)
    assert evento.processed_at is not None and evento.error is None
