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

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from core.config import settings
from modules.payments.links import RETIRED_LINK_SEARCH_MAX, retired_link_references
from modules.payments.model import Payment, PaymentLinkHistory, PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _cobro
from tests.integration.test_conciliacion_links_retirados_acotada import (
    _tres_retenciones_vencidas,
)
from tests.integration.test_expiracion_mp_fuera_del_lock import (
    _mercadopago_que_registra,
)
from tests.integration.test_link_regenerado_referencia_propia import (
    _pago_de_mp,
    _regenerado,
)
from tests.integration.test_mails_al_cliente import Buzon


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
    # Tope de 3 consultas: el id, la referencia vigente y un retirado
    # (revision de 3b977a9..6c84d46, #5).
    assert busquedas == ["turno-d:vigente", "turno-d:retirado-0"]


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
    # El id, la vigente y UN retirado: la misma cota de 3 que sin id.
    assert busquedas == ["turno-d2:vigente", "turno-d2:retirado-0"]
    assert len(busquedas) == RETIRED_LINK_SEARCH_MAX


@pytest.mark.asyncio
async def test_un_rechazo_reintentado_y_aprobado_en_el_link_vigente_se_encuentra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision de 3b977a9..6c84d46 (#5). El cliente pago con una tarjeta
    rechazada (``external_payment_id`` = ese rechazo) y reintento en el MISMO
    link con otra que se aprobo; el webhook del aprobado se perdio. Consultar
    solo por el id devolvia el rechazo: el cobro aprobado no se conciliaba.
    Ahora la rama del id tambien busca la referencia del link vigente."""
    cobro = Payment(
        id="cobro-d3",
        store_id="tienda-d",
        appointment_id="turno-d3",
        amount=Decimal("100"),
        link_ref="vigente",
        provider="mercadopago",
        external_payment_id="mp-rechazado",
    )
    aprobado = {"id": "mp-reintento", "status": "approved"}

    async def por_id(_db: Any, *, payment_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"id": payment_id, "status": "rejected"}

    async def buscar(
        _db: Any, *, external_reference: str, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        return [aprobado] if external_reference == "turno-d3:vigente" else []

    monkeypatch.setattr(jobs, "fetch_mercadopago_payment", por_id)
    monkeypatch.setattr(jobs, "search_mercadopago_payments", buscar)

    remoto = await jobs._fetch_remote_payment(
        None,  # type: ignore[arg-type]
        cobro,
        {},
        None,
        (),
    )

    assert remoto == aprobado


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


@pytest.mark.asyncio
async def test_la_conciliacion_no_se_queda_con_los_mismos_pendientes_del_frente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de 3b977a9..6c84d46 (#4). La conciliacion ordenaba por
    ``created_at`` con ``limit``: los cobros que siguen ``pending`` en MP
    ocupaban siempre el frente y, con MP lento, la cola nunca se consultaba.
    Ahora cada cobro consultado anota ``reconciled_at`` y el orden es
    ``reconciled_at NULLS FIRST, created_at``: la corrida siguiente toma la
    cola."""
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_que_registra(monkeypatch, [], remoto=None)
    turnos = await _tres_retenciones_vencidas(client, test_session)
    cobros = [
        (
            await test_session.execute(
                select(Payment.id).where(Payment.appointment_id == turno)
            )
        ).scalar_one()
        for turno in turnos
    ]
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for n, cobro_id in enumerate(cobros):
        await test_session.execute(
            update(Payment)
            .where(Payment.id == cobro_id)
            .values(created_at=base + timedelta(minutes=n))
        )
    await test_session.commit()
    consultados: list[str] = []

    async def mp_que_sigue_pendiente(
        _db: Any, payment: Payment, *_args: Any, **_kwargs: Any
    ) -> None:
        consultados.append(payment.id)
        return None

    monkeypatch.setattr(jobs, "_fetch_remote_payment", mp_que_sigue_pendiente)

    await jobs.reconcile_pending_payments(test_session, limit=2)
    primera = list(consultados)
    consultados.clear()
    await jobs.reconcile_pending_payments(test_session, limit=2)

    assert primera == cobros[:2]
    # La cola (el tercero) entra en la corrida siguiente, primero.
    assert consultados[0] == cobros[2], consultados
    test_session.expire_all()
    marcas = (
        await test_session.execute(
            select(Payment.id, Payment.reconciled_at).where(Payment.id.in_(cobros))
        )
    ).all()
    assert all(marca is not None for _id, marca in marcas), marcas


async def _tres_cobros_viejos(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_que_registra(monkeypatch, [], remoto=None)
    turnos = await _tres_retenciones_vencidas(client, session)
    cobros = [
        (
            await session.execute(
                select(Payment.id).where(Payment.appointment_id == turno)
            )
        ).scalar_one()
        for turno in turnos
    ]
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for n, cobro_id in enumerate(cobros):
        await session.execute(
            update(Payment)
            .where(Payment.id == cobro_id)
            .values(created_at=base + timedelta(minutes=n))
        )
    await session.commit()
    return cobros


async def _marcas(session: AsyncSession, cobros: list[str]) -> dict[str, Any]:
    session.expire_all()
    filas = await session.execute(
        select(Payment.id, Payment.reconciled_at).where(Payment.id.in_(cobros))
    )
    return {cobro_id: marca for cobro_id, marca in filas.all()}


@pytest.mark.asyncio
async def test_un_cobro_salteado_por_el_lock_del_turno_no_va_al_fondo_de_la_cola(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de 6c84d46..79a64e4 (#1). ``reconciled_at`` se anotaba en
    todo lo que la fase A consulto. Un cobro que MP ya dio por aprobado pero
    cuya aplicacion se salteo porque un webhook o un "liberar" tenia el turno
    iba al fondo de la cola. Ahora solo se marca lo que la fase B proceso."""
    cobros = await _tres_cobros_viejos(client, test_session, monkeypatch)
    salteado = cobros[0]

    async def mp(_db: Any, payment: Payment, *_args: Any, **_kwargs: Any) -> Any:
        if payment.id == salteado:
            return {"id": "mp-aprobado", "status": "approved"}
        return None

    async def turno(_db: Any, payment: Payment) -> bool:
        return payment.id != salteado

    monkeypatch.setattr(jobs, "_fetch_remote_payment", mp)
    monkeypatch.setattr(jobs, "_lock_appointment_or_skip", turno)

    await jobs.reconcile_pending_payments(test_session)

    marcas = await _marcas(test_session, cobros)
    assert marcas[salteado] is None, marcas
    assert all(marcas[c] is not None for c in cobros[1:]), marcas


@pytest.mark.asyncio
async def test_si_la_marca_falla_se_loguea_y_lo_conciliado_queda(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de 6c84d46..79a64e4 (#1): el camino de falla de
    ``_marcar_conciliados``. La marca corre despues del commit de la fase B:
    si falla se loguea y lo ya conciliado no se pierde."""
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.sql.dml import Update
    from structlog.testing import capture_logs

    turno, _mp, _vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "marca-falla"
    )
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    cobro = await _cobro(test_session, turno)
    remoto = _pago_de_mp(
        cobro, referencia=cobro.current_external_reference, externo="mp-ok"
    )["data"]

    async def mp(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return dict(remoto)

    monkeypatch.setattr(jobs, "_fetch_remote_payment", mp)
    ejecutar = test_session.execute

    async def execute_que_falla_en_la_marca(statement: Any, *a: Any, **k: Any) -> Any:
        if isinstance(statement, Update) and "reconciled_at" in str(statement):
            raise OperationalError(str(statement), {}, Exception("lock_timeout"))
        return await ejecutar(statement, *a, **k)

    monkeypatch.setattr(test_session, "execute", execute_que_falla_en_la_marca)

    with capture_logs() as logs:
        resultado = await jobs.reconcile_pending_payments(test_session)

    assert resultado["reconciled"] == 1, resultado
    fallos = [e for e in logs if e["event"] == "reconciliation_mark_failed"]
    assert len(fallos) == 1, logs
    monkeypatch.setattr(test_session, "execute", ejecutar)
    cobro = await _cobro(test_session, turno)
    cobro_id = cobro.id
    assert cobro.status == PaymentStatus.APPROVED.value
    assert (await _marcas(test_session, [cobro_id]))[cobro_id] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("con_id", [True, False])
async def test_con_tope_cero_no_se_busca_ningun_link_retirado(
    monkeypatch: pytest.MonkeyPatch, con_id: bool
) -> None:
    """Revision de 6c84d46..79a64e4 (#3). Con ``RETIRED_LINK_SEARCH_MAX = 0``
    la rama del id restaba uno y cortaba ``retiradas[:-1]``: buscaba casi
    todos los links retirados, sin tope. Ahora el tope se acota en 0."""
    monkeypatch.setattr(jobs, "RETIRED_LINK_SEARCH_MAX", 0)
    cobro = Payment(
        id="cobro-cero",
        store_id="tienda-d",
        appointment_id="turno-cero",
        amount=Decimal("100"),
        link_ref="vigente",
        provider="mercadopago",
        external_payment_id="mp-rechazado" if con_id else None,
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

    await jobs._fetch_remote_payment(
        None,  # type: ignore[arg-type]
        cobro,
        {},
        None,
        [f"turno-cero:retirado-{i}" for i in range(5)],
    )

    assert busquedas == ["turno-cero:vigente"], busquedas
