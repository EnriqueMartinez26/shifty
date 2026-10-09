"""Saldo restante por turno (opcion A, D-20261008-01).

Caso de uso: un turno con precio congelado de $3.200 tiene acreditada una sena
de $960 (``approved`` o ``manual_confirmed``). El cliente paga el resto
($2.240) en el local y el personal lo registra desde Cobros. Antes no habia
como: "Confirmar pago" es un no-op sobre un cobro acreditado y la tarjeta
quedaba en "Pagado $960 · Resta $2.240" para siempre.

Reglas que fija este archivo:

- Un solo resto por turno. El importe lo carga el personal; si no viaja, es el
  saldo; tiene que ser mayor a cero y no superar el saldo.
- Saldo = precio congelado - cobro acreditado - resto ya registrado,
  calculado en SQL, nunca tomado del cliente. Sin cobro acreditado no hay
  saldo: sigue el flujo de "Confirmar pago" (409 ``NO_ACCREDITED_PAYMENT``).
- Un ausente no debe nada (saldo 0). Un turno soltado (cancelado o vencido)
  no registra resto: 409 como la confirmacion manual.
- La devolucion de un resto es manual (fuera del sistema): el admin lo marca
  revertido, sin borrar la fila.
- Permisos de la confirmacion manual para registrar; solo admin para revertir.
- La busqueda de Cobros trae ``remaining_amount`` y ``remainder_payment``
  para quien opera cobros y ``None`` para la recepcion.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.security import hash_password
from modules.appointments.model import AppointmentStatus
from modules.payments.model import PaymentStatus
from modules.services.model import Service
from modules.users.model import User, UserRole
from tests.integration.test_busqueda_y_resumen_contrato_aditivo import (
    _de_turnos,
    _Registro,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda

PRECIO = Decimal("3200")
SENA = Decimal("960")
RESTO = Decimal("2240")


class _Caso:
    def __init__(
        self, token: str, store_id: str, semilla: _Semilla, servicio: Service
    ) -> None:
        self.token = token
        self.store_id = store_id
        self.semilla = semilla
        self.servicio = servicio
        self._n = 0

    async def turno(
        self,
        estado: AppointmentStatus = AppointmentStatus.CONFIRMED,
        *,
        precio: Decimal | None = PRECIO,
        pago: tuple[Decimal, PaymentStatus] | None = (SENA, PaymentStatus.APPROVED),
    ) -> str:
        self._n += 1
        cliente = self.semilla.cliente(f"Cli{self._n}", "Resto")
        await self.semilla.session.commit()
        return await self.semilla.turno(
            f"resto-{self._n}",
            date(2026, 10, 8),
            time(8 + self._n, 0),
            self.servicio,
            cliente,
            estado,
            precio=precio,
            pago=pago,
        )


async def _caso(client: AsyncClient, session: AsyncSession, slug: str) -> _Caso:
    token, store, staff, servicio = await _tienda(client, session, slug)
    return _Caso(token, store.id, _Semilla(session, store, staff), servicio)


async def _registrar(
    client: AsyncClient,
    token: str,
    turno: str,
    clave: str,
    **cuerpo: object,
) -> Response:
    return await client.post(
        f"/payments/{turno}/remaining-payment",
        headers=auth_headers(token),
        json={"idempotency_key": clave, **cuerpo},
    )


async def _usuario(
    client: AsyncClient, session: AsyncSession, store_id: str, rol: UserRole, email: str
) -> str:
    session.add(
        User(
            email=email,
            hashed_password=hash_password("Password123!"),
            first_name="Otro",
            last_name="Rol",
            role=rol,
            store_id=store_id,
        )
    )
    await session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _filas_vivas(session: AsyncSession, turno: str) -> list[Decimal]:
    filas = await session.execute(
        text(
            "select amount from appointment_balance_payments "
            "where appointment_id = :t and reverted_at is null"
        ),
        {"t": turno},
    )
    return [Decimal(str(f[0])) for f in filas.all()]


async def _busqueda(client: AsyncClient, token: str) -> dict[str, dict[str, object]]:
    res = await client.get(
        "/appointments/search",
        params={"page": 1, "page_size": 50},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    return {r["public_id"]: r for r in res.json()["results"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "acreditado", [PaymentStatus.APPROVED, PaymentStatus.MANUAL_CONFIRMED]
)
async def test_sin_importe_registra_el_saldo_y_lo_deja_en_cero(
    client: AsyncClient, test_session: AsyncSession, acreditado: PaymentStatus
) -> None:
    """$960 de sena sobre $3.200: el resto por defecto es $2.240."""
    c = await _caso(client, test_session, f"resto-saldo-{acreditado.value}")
    turno = await c.turno(pago=(SENA, acreditado))

    res = await _registrar(
        client, c.token, turno, "resto-clave-0001", method="efectivo"
    )

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert Decimal(cuerpo["amount"]) == RESTO
    assert cuerpo["method"] == "efectivo"
    assert cuerpo["reverted_at"] is None
    assert Decimal(cuerpo["remaining_amount"]) == 0
    assert await _filas_vivas(test_session, turno) == [RESTO]

    fila = (await _busqueda(client, c.token))[turno]
    assert Decimal(str(fila["remaining_amount"])) == 0
    resto = fila["remainder_payment"]
    assert isinstance(resto, dict)
    assert Decimal(str(resto["amount"])) == RESTO
    assert resto["method"] == "efectivo"
    assert resto["created_at"]


@pytest.mark.asyncio
async def test_la_busqueda_trae_el_saldo_antes_de_registrar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-busqueda")
    con_sena = await c.turno()
    sin_cobro = await c.turno(pago=None)
    ausente = await c.turno(AppointmentStatus.ABSENT)

    filas = await _busqueda(client, c.token)

    assert Decimal(str(filas[con_sena]["remaining_amount"])) == RESTO
    assert filas[con_sena]["remainder_payment"] is None
    # Sin cobro acreditado no hay saldo: sigue "Confirmar pago".
    assert Decimal(str(filas[sin_cobro]["remaining_amount"])) == 0
    # Un ausente no debe el resto de un servicio que no recibio.
    assert Decimal(str(filas[ausente]["remaining_amount"])) == 0


@pytest.mark.asyncio
async def test_un_importe_menor_deja_el_resto_y_no_se_registra_dos_veces(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-parcial")
    turno = await c.turno(AppointmentStatus.COMPLETED)

    res = await _registrar(client, c.token, turno, "resto-clave-0002", amount="2000")
    assert res.status_code == 201, res.text
    assert Decimal(res.json()["remaining_amount"]) == Decimal("240")
    assert res.json()["method"] is None

    otra = await _registrar(client, c.token, turno, "resto-clave-0003", amount="240")
    assert otra.status_code == 409, otra.text
    assert otra.json()["error_code"] == "REMAINING_PAYMENT_ALREADY_RECORDED"
    assert await _filas_vivas(test_session, turno) == [Decimal("2000")]


@pytest.mark.asyncio
async def test_un_importe_mayor_al_saldo_es_409_y_no_escribe(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-excede")
    turno = await c.turno()

    res = await _registrar(client, c.token, turno, "resto-clave-0004", amount="2240.01")

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "REMAINING_PAYMENT_EXCEEDS_BALANCE"
    assert await _filas_vivas(test_session, turno) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pago", "codigo"),
    [
        (None, "NO_ACCREDITED_PAYMENT"),
        ((SENA, PaymentStatus.PENDING), "NO_ACCREDITED_PAYMENT"),
        ((SENA, PaymentStatus.REFUNDED), "NO_ACCREDITED_PAYMENT"),
        ((PRECIO, PaymentStatus.APPROVED), "NO_REMAINING_BALANCE"),
    ],
)
async def test_sin_saldo_acreditado_es_409(
    client: AsyncClient,
    test_session: AsyncSession,
    pago: tuple[Decimal, PaymentStatus] | None,
    codigo: str,
) -> None:
    estado = pago[1].value if pago else "sin-cobro"
    c = await _caso(client, test_session, f"resto-sin-saldo-{estado}")
    turno = await c.turno(pago=pago)

    res = await _registrar(client, c.token, turno, "resto-clave-0005")

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == codigo
    assert await _filas_vivas(test_session, turno) == []


@pytest.mark.asyncio
async def test_un_turno_sin_precio_congelado_no_tiene_saldo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-sin-precio")
    turno = await c.turno(precio=None)

    res = await _registrar(client, c.token, turno, "resto-clave-0006")

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "NO_REMAINING_BALANCE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("estado", "codigo"),
    [
        (AppointmentStatus.ABSENT, "NO_REMAINING_BALANCE"),
        (AppointmentStatus.CANCELLED, "APPOINTMENT_NOT_PAYABLE"),
        (AppointmentStatus.EXPIRED, "APPOINTMENT_HOLD_EXPIRED"),
    ],
)
async def test_ausente_y_soltados_no_registran_resto(
    client: AsyncClient,
    test_session: AsyncSession,
    estado: AppointmentStatus,
    codigo: str,
) -> None:
    c = await _caso(client, test_session, f"resto-{estado.value}")
    turno = await c.turno(estado)

    res = await _registrar(client, c.token, turno, "resto-clave-0007")

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == codigo
    assert await _filas_vivas(test_session, turno) == []


@pytest.mark.asyncio
async def test_la_misma_clave_devuelve_la_misma_respuesta_sin_otra_fila(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Un doble toque (o un reintento de red) no registra dos restos ni
    responde 409: la misma clave devuelve el resultado del primero."""
    c = await _caso(client, test_session, "resto-idempotencia")
    turno = await c.turno()

    primera = await _registrar(client, c.token, turno, "resto-clave-0008")
    segunda = await _registrar(client, c.token, turno, "resto-clave-0008")

    assert primera.status_code == 201, primera.text
    assert segunda.status_code == 201, segunda.text
    assert segunda.json()["public_id"] == primera.json()["public_id"]
    assert await _filas_vivas(test_session, turno) == [RESTO]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cuerpo",
    [
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "10000000.01"},
        {"method": "cheque"},
        {"idempotency_key": "corta"},
    ],
)
async def test_entrada_invalida_es_422(
    client: AsyncClient, test_session: AsyncSession, cuerpo: dict[str, str]
) -> None:
    c = await _caso(client, test_session, "resto-422")
    turno = await c.turno()

    res = await client.post(
        f"/payments/{turno}/remaining-payment",
        headers=auth_headers(c.token),
        json={"idempotency_key": "resto-clave-0009", **cuerpo},
    )

    assert res.status_code == 422, res.text
    assert await _filas_vivas(test_session, turno) == []


@pytest.mark.asyncio
async def test_la_recepcion_no_registra_ni_ve_el_saldo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-recepcion")
    turno = await c.turno()
    await _registrar(client, c.token, turno, "resto-clave-0010", amount="1000")
    recepcion = await _usuario(
        client,
        test_session,
        c.store_id,
        UserRole.RECEPTIONIST,
        "recepcion-resto@test.com",
    )

    res = await _registrar(client, recepcion, turno, "resto-clave-0011", amount="1")
    assert res.status_code == 403, res.text

    fila = (await _busqueda(client, recepcion))[turno]
    assert fila["remaining_amount"] is None
    assert fila["remainder_payment"] is None


@pytest.mark.asyncio
async def test_el_admin_revierte_el_resto_sin_borrarlo_y_vuelve_el_saldo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-revertir")
    turno = await c.turno()
    registrado = await _registrar(
        client, c.token, turno, "resto-clave-0012", method="transferencia"
    )
    assert registrado.status_code == 201, registrado.text

    res = await client.post(
        f"/payments/{turno}/remaining-payment/revert", headers=auth_headers(c.token)
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["public_id"] == registrado.json()["public_id"]
    assert cuerpo["reverted_at"] is not None
    assert Decimal(cuerpo["remaining_amount"]) == RESTO
    assert await _filas_vivas(test_session, turno) == []
    # La fila queda (auditoria): solo se marca.
    total = await test_session.execute(
        text(
            "select count(*), max(reverted_by) from appointment_balance_payments "
            "where appointment_id = :t"
        ),
        {"t": turno},
    )
    cantidad, revertido_por = total.one()
    assert cantidad == 1
    assert revertido_por is not None

    fila = (await _busqueda(client, c.token))[turno]
    assert Decimal(str(fila["remaining_amount"])) == RESTO
    assert fila["remainder_payment"] is None

    # Revertido, se puede volver a registrar el resto correcto.
    otra = await _registrar(client, c.token, turno, "resto-clave-0013", amount="2240")
    assert otra.status_code == 201, otra.text
    assert await _filas_vivas(test_session, turno) == [RESTO]


@pytest.mark.asyncio
async def test_revertir_sin_resto_vivo_es_409(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-revertir-nada")
    turno = await c.turno()

    res = await client.post(
        f"/payments/{turno}/remaining-payment/revert", headers=auth_headers(c.token)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "NO_REMAINING_PAYMENT"


@pytest.mark.asyncio
async def test_solo_el_admin_revierte(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-revertir-staff")
    turno = await c.turno()
    await _registrar(client, c.token, turno, "resto-clave-0014")
    profesional = await _usuario(
        client, test_session, c.store_id, UserRole.STAFF, "pro-resto@test.com"
    )

    res = await client.post(
        f"/payments/{turno}/remaining-payment/revert",
        headers=auth_headers(profesional),
    )

    assert res.status_code == 403, res.text
    assert await _filas_vivas(test_session, turno) == [RESTO]


@pytest.mark.asyncio
async def test_el_resto_entra_en_la_misma_consulta_de_la_busqueda(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """Regla 12: el saldo y el resto no suman sentencias; el join al resto
    lleva ``store_id`` (CLAUDE.md §2)."""
    c = await _caso(client, test_session, "resto-una-consulta")
    turno = await c.turno()
    await _registrar(client, c.token, turno, "resto-clave-0015", amount="1000")

    with _Registro(test_engine) as sentencias:
        await _busqueda(client, c.token)

    turnos = _de_turnos(sentencias)
    assert len(turnos) == 2, turnos
    assert not [s for s in sentencias if "from appointment_balance_payments" in s]
    (pagina,) = [s for s in turnos if "count(" not in s]
    assert "left outer join appointment_balance_payments" in pagina, pagina
    assert "appointment_balance_payments.store_id" in pagina, pagina


async def _id_del_cobro(session: AsyncSession, turno: str) -> str:
    fila = await session.execute(
        text("select id from payments where appointment_id = :t"), {"t": turno}
    )
    return str(fila.scalar_one())


@pytest.mark.asyncio
async def test_devolver_la_sena_avisa_el_resto_vivo_sin_revertirlo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Revision de la PR #137 (W1, 2026-10-08): devolver la sena dejaba el
    resto vivo, contando como ingreso, sin que nadie se enterara. El reembolso
    no lo revierte (la devolucion del resto es otra decision) pero lo dice."""
    c = await _caso(client, test_session, "resto-reembolso")
    turno = await c.turno()
    await _registrar(client, c.token, turno, "resto-clave-0016")

    res = await client.post(
        f"/payments/{await _id_del_cobro(test_session, turno)}/refund",
        headers=auth_headers(c.token),
        json={"manual": True, "reason": "Devolucion de la sena"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "refunded"
    assert Decimal(res.json()["live_remainder_amount"]) == RESTO
    assert await _filas_vivas(test_session, turno) == [RESTO]


@pytest.mark.asyncio
async def test_devolver_sin_resto_no_avisa_nada(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    c = await _caso(client, test_session, "resto-reembolso-sin")
    turno = await c.turno()

    res = await client.post(
        f"/payments/{await _id_del_cobro(test_session, turno)}/refund",
        headers=auth_headers(c.token),
        json={"manual": True},
    )

    assert res.status_code == 200, res.text
    assert res.json()["live_remainder_amount"] is None


@pytest.mark.asyncio
async def test_registrar_y_revertir_dejan_auditoria(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Revision de la PR #137 (S3): plata registrada a mano deja rastro de
    quien la cargo y quien la revirtio, como los cambios de la agenda."""
    c = await _caso(client, test_session, "resto-auditoria")
    turno = await c.turno()
    registrado = await _registrar(
        client, c.token, turno, "resto-clave-0017", method="efectivo"
    )
    resto_id = registrado.json()["public_id"]
    revertido = await client.post(
        f"/payments/{turno}/remaining-payment/revert", headers=auth_headers(c.token)
    )
    assert revertido.status_code == 200, revertido.text

    filas = await test_session.execute(
        text(
            "select action, store_id, actor_id, payload_after from audit_logs "
            "where resource_type = 'AppointmentBalancePayment' "
            "and resource_id = :r order by created_at"
        ),
        {"r": resto_id},
    )
    acciones = filas.all()
    assert [a[0] for a in acciones] == ["create", "update"]
    assert all(a[1] == c.store_id and a[2] is not None for a in acciones)
    assert "2240" in str(acciones[0][3]) and turno in str(acciones[0][3])
    assert "reverted_at" in str(acciones[1][3])
