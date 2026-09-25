"""Detalles de la conciliacion con links retirados.

Revision de e5579b6..3b977a9 (2026-09-25, #4):

- (d) Un cobro pendiente que ya tiene ``external_payment_id`` (por ejemplo,
  un rechazo sobre el link vigente) se consultaba SOLO por ese id: si ese
  pago no estaba aprobado, nunca se buscaban sus links retirados. Ahora
  tambien, dentro del tope ``RETIRED_LINK_SEARCH_MAX``.
- (e) ``retired_link_references`` filtra por ``store_id`` como toda consulta
  de un repositorio (regla de defensa en profundidad y camino al indice bajo
  RLS), y devuelve como mucho el tope de links por cobro.
- (f) ``reconciled`` cuenta solo los cobros cuyo estado cambio: un pago
  remoto que sigue ``pending`` es un no-op y antes sumaba.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.jobs as jobs
from core.config import settings
from modules.payments.links import RETIRED_LINK_SEARCH_MAX, retired_link_references
from modules.payments.model import Payment, PaymentLinkHistory, PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _cobro
from tests.integration.test_link_regenerado_referencia_propia import (
    _pago_de_mp,
    _regenerado,
)


@pytest.mark.asyncio
async def test_un_cobro_con_id_de_mp_no_aprobado_tambien_busca_sus_links_retirados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cobro = Payment(
        id="cobro-d",
        store_id="tienda-d",
        appointment_id="turno-d",
        amount=Decimal("100"),
        link_ref="vigente",
        provider="mercadopago",
        external_payment_id="mp-rechazado",
    )
    aprobado = {"id": "mp-viejo", "status": "approved"}
    busquedas: list[str] = []

    async def por_id(_db: Any, *, payment_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"id": payment_id, "status": "rejected"}

    async def buscar(
        _db: Any, *, external_reference: str, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        busquedas.append(external_reference)
        return [aprobado] if external_reference == "turno-d:retirado-0" else []

    monkeypatch.setattr(jobs, "fetch_mercadopago_payment", por_id)
    monkeypatch.setattr(jobs, "search_mercadopago_payments", buscar)

    remoto = await jobs._fetch_remote_payment(
        None,  # type: ignore[arg-type]
        cobro,
        {},
        None,
        ["turno-d:retirado-0", "turno-d:retirado-1", "turno-d:retirado-2"],
    )

    assert remoto == aprobado
    # La vigente ya se consulto por id: solo los retirados, dentro del tope.
    assert busquedas == ["turno-d:retirado-0"]


@pytest.mark.asyncio
async def test_sin_aprobado_en_los_retirados_gana_el_pago_del_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cobro = Payment(
        id="cobro-d2",
        store_id="tienda-d",
        appointment_id="turno-d2",
        amount=Decimal("100"),
        link_ref="vigente",
        provider="mercadopago",
        external_payment_id="mp-rechazado",
    )
    busquedas: list[str] = []

    async def por_id(_db: Any, *, payment_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"id": payment_id, "status": "rejected"}

    async def buscar(
        _db: Any, *, external_reference: str, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        busquedas.append(external_reference)
        return []

    monkeypatch.setattr(jobs, "fetch_mercadopago_payment", por_id)
    monkeypatch.setattr(jobs, "search_mercadopago_payments", buscar)

    remoto = await jobs._fetch_remote_payment(
        None,  # type: ignore[arg-type]
        cobro,
        {},
        None,
        [f"turno-d2:retirado-{i}" for i in range(5)],
    )

    assert remoto == {"id": "mp-rechazado", "status": "rejected"}
    assert len(busquedas) == RETIRED_LINK_SEARCH_MAX


@pytest.mark.asyncio
async def test_las_referencias_retiradas_filtran_por_tienda_y_respetan_el_tope(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "retiradas-por-tienda"
    )
    cobro = await _cobro(test_session, turno)
    fila = (
        await test_session.execute(
            select(PaymentLinkHistory).where(PaymentLinkHistory.payment_id == cobro.id)
        )
    ).scalar_one()
    # Una fila con el mismo cobro y OTRA tienda (bajo RLS no se veria; el
    # filtro explicito es la defensa en profundidad), mas links viejos de la
    # misma tienda para probar el tope.
    for n, (tienda, ref) in enumerate(
        [
            ("OTRA-TIENDA", "ajeno"),
            (cobro.store_id, "viejo-1"),
            (cobro.store_id, "viejo-2"),
        ]
    ):
        test_session.add(
            PaymentLinkHistory(
                store_id=tienda,
                payment_id=cobro.id,
                link_ref=ref,
                preference_id=f"pref-{ref}",
                amount=cobro.amount,
                currency=cobro.currency,
                retired_at=fila.retired_at
                - timedelta(minutes=1 if tienda == "OTRA-TIENDA" else 5 * (n + 1)),
            )
        )
    await test_session.commit()

    referencias = await retired_link_references(test_session, [cobro])

    assert referencias == {cobro.id: [mp.referencias[vieja], f"{turno}:viejo-1"]}, (
        referencias
    )


@pytest.mark.asyncio
async def test_un_pago_remoto_sin_cambio_de_estado_no_cuenta_como_conciliado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    turno, _mp, _vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "concilia-no-op"
    )
    cobro = await _cobro(test_session, turno)
    remoto = _pago_de_mp(
        cobro, referencia=cobro.current_external_reference, externo="mp-pendiente"
    )["data"]
    remoto["status"] = "pending"

    async def mp(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return dict(remoto)

    monkeypatch.setattr(jobs, "_fetch_remote_payment", mp)

    resultado = await jobs.reconcile_pending_payments(test_session)

    assert resultado["inspected"] == 1, resultado
    assert resultado["reconciled"] == 0, resultado
    assert (await _cobro(test_session, turno)).status == PaymentStatus.PENDING.value
