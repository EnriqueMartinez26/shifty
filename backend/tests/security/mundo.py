"""Mundo compartido de la suite de autorizacion y aislamiento entre tiendas.

Dos tiendas con la MISMA forma de datos ("alfa" y "beta"): servicio,
profesional con agenda, turnos, bloqueo, promocion, cobro, fiado, aviso,
imagen, lista de espera y suscripcion. Todo lo de beta lleva "Beta" en el
nombre y telefonos/emails propios, para que una fuga se detecte buscando esos
marcadores en la respuesta de alfa.

Se arma UNA vez por modulo: la base es SQLite en memoria como la de
``tests/integration/conftest.py`` (misma URL, mismo registro de modelos),
pero con UNA sesion por request, igual que produccion y que
``tests/postgres/conftest.py``: con la sesion compartida de integracion un
error a mitad de un request deja la sesion inservible para los cientos de
requests que siguen.

SQLite no aplica RLS: lo que prueba esta suite es la capa de APLICACION
(filtros ``store_id`` y chequeos de rol), que CLAUDE.md §2 exige que se
sostenga sola.
"""

from __future__ import annotations

import itertools
import secrets

import ulid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.crypto import encrypt_secret
from core.database import get_db
from core.model_registry import load_all_models
from core.models import Base
from core.security import (
    create_access_token,
    hash_password,
    hash_password_reset_token,
    hash_token,
)
from main import app
from modules.auth.service import access_token_for_user, normalize_email
from modules.auth.session_model import AuthSession
from modules.billing.model import Plan, SaaSCoupon, StoreSubscription
from modules.notifications.model import Notification
from modules.payments.model import PaymentGatewayConfig
from modules.stores.model import Store, StoreMedia
from modules.users.model import User
from modules.waitlist.model import WaitlistEntry
from tests.integration.conftest import TEST_DATABASE_URL

load_all_models()

PASSWORD = "Password123!"
NUEVA_PASSWORD = "Otra-Clave-Larga-2026!"
WEBHOOK_SECRET = "whsec-suite-seguridad"
ACCESS_TOKEN_MP = "TEST-ACCESS-TOKEN-SEGURIDAD-123456"

ANON = "anon"
CLIENTE_OTP = "client-otp"
PROFESIONAL = "professional"
RECEPCIONISTA = "receptionist"
ADMIN_TIENDA = "store_admin"
SUPERADMIN = "super_admin"
ROLES: tuple[str, ...] = (
    ANON,
    CLIENTE_OTP,
    PROFESIONAL,
    RECEPCIONISTA,
    ADMIN_TIENDA,
    SUPERADMIN,
)
# Valor persistido en users.role para cada rol de personal.
ROL_PERSISTIDO = {
    PROFESIONAL: "staff",
    RECEPCIONISTA: "receptionist",
    ADMIN_TIENDA: "admin",
    SUPERADMIN: "admin",
}

# PNG de 1x1: pasa la validacion por magic bytes y el tope de pixeles.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@dataclass
class Llamada:
    """Un request listo para mandar, armado por la fabrica de una ruta."""

    method: str
    url: str
    json: Any = None
    params: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    files: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    # El token del actor viaja salvo que la fabrica lo apague (webhooks).
    con_token: bool = True

    def textos_enviados(self) -> str:
        """Todo lo que el request manda: lo que se devuelve de eso no es fuga."""
        return " ".join(
            str(parte)
            for parte in (self.url, self.json, self.params, self.data)
            if parte is not None
        )


@dataclass
class Tienda:
    clave: str
    nombre: str
    id: str = ""
    slug: str = ""
    admin_id: str = ""
    profesional_id: str = ""
    recepcionista_id: str = ""
    servicio: str = ""
    servicio_nombre: str = ""
    staff: str = ""
    staff_nombre: str = ""
    turno: str = ""
    turno_publico: str = ""
    turno_sin_otp: str = ""
    bloqueo: str = ""
    promocion: str = ""
    codigo_promocion: str = ""
    pago: str = ""
    cliente: str = ""
    movimiento: str = ""
    notificacion: str = ""
    media: str = ""
    espera: str = ""
    suscripcion: str = ""
    tel_verificado: str = ""
    email_verificado: str = ""
    nombre_verificado: str = ""
    tel_sin_otp: str = ""
    nombre_sin_otp: str = ""
    marcadores: set[str] = field(default_factory=set)
    _slots: itertools.count[int] = field(default_factory=itertools.count)
    # Fijo al armar: si la corrida cruza la medianoche UTC, un dia base
    # recalculado correria la grilla y dos turnos caerian en el mismo slot.
    _dia_base: date = field(
        default_factory=lambda: (datetime.now(timezone.utc) + timedelta(days=3)).date()
    )

    def dia_base(self) -> date:
        return self._dia_base


@dataclass
class Actor:
    rol: str
    tienda: Tienda
    user_id: str | None = None
    email: str | None = None
    token: str | None = None
    telefono: str | None = None

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}


def slot_utc(dia: date, indice: int) -> datetime:
    """Turno de 30 minutos entre las 10:00 y las 16:30 UTC (07 a 13:30 local)."""
    minutos = 10 * 60 + 30 * indice
    return datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc) + timedelta(
        minutes=minutos
    )


class Mundo:
    """Fabrica de datos y actores sobre la app real con una base propia."""

    SLOTS_POR_DIA = 14

    def __init__(
        self, client: AsyncClient, sesiones: async_sessionmaker[AsyncSession]
    ) -> None:
        self.client = client
        self.sesiones = sesiones
        self._n = itertools.count(1)
        self.alfa = Tienda(clave="alfa", nombre="Alfa")
        self.beta = Tienda(clave="beta", nombre="Beta")
        self.plan_id = ""

    # -- utilidades ---------------------------------------------------------

    def unico(self, prefijo: str) -> str:
        return f"{prefijo}-{next(self._n):06d}"

    def telefono_nuevo(self) -> str:
        return f"+54911{next(self._n) + 30_000_000:08d}"

    def slot(self, tienda: Tienda) -> datetime:
        """Horario libre y unico dentro de la tienda (turnos y bloqueos)."""
        indice = next(tienda._slots)
        dia = tienda.dia_base() + timedelta(days=indice // self.SLOTS_POR_DIA)
        return slot_utc(dia, indice % self.SLOTS_POR_DIA)

    def otra(self, tienda: Tienda) -> Tienda:
        return self.beta if tienda is self.alfa else self.alfa

    # -- usuarios, sesiones y tokens ----------------------------------------

    async def usuario(
        self,
        tienda: Tienda,
        rol: str,
        *,
        global_admin: bool = False,
        email: str | None = None,
        telefono: str | None = None,
        nombre: str = "Persona",
    ) -> tuple[str, str]:
        correo = normalize_email(
            email or f"{self.unico('u')}@seguridad-{tienda.clave}.com"
        )
        async with self.sesiones() as s:
            user = User(
                email=correo,
                hashed_password=hash_password(PASSWORD),
                first_name=nombre,
                last_name=tienda.nombre,
                full_name=f"{nombre} {tienda.nombre}",
                role=rol,
                store_id=tienda.id,
                is_global_admin=global_admin,
                phone=telefono,
            )
            s.add(user)
            await s.flush()
            user_id = str(user.id)
            await s.commit()
        return user_id, correo

    async def sesion(self, user_id: str) -> tuple[str, str]:
        """(id de sesion, access token) de una sesion nueva del usuario."""
        async with self.sesiones() as s:
            user = await s.get(User, user_id)
            assert user is not None
            sesion = AuthSession(
                user_id=user.id,
                store_id=user.store_id,
                refresh_token_hash=hash_token(secrets.token_urlsafe(32)),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
            s.add(sesion)
            await s.flush()
            token = access_token_for_user(user, sesion.id)
            sesion_id = str(sesion.id)
            await s.commit()
        return sesion_id, token

    async def token(self, user_id: str) -> str:
        return (await self.sesion(user_id))[1]

    async def actor(self, rol: str, tienda: Tienda) -> Actor:
        """Actor FRESCO: una cuenta nueva por test, con una sesion nueva.

        Rutas como cambiar la clave, revocar sesiones o el boton de panico
        dejan inservible la cuenta que las usa; con una cuenta por test el
        orden de los tests no importa.
        """
        if rol == ANON:
            return Actor(rol, tienda, telefono=self.telefono_nuevo())
        if rol == CLIENTE_OTP:
            return Actor(rol, tienda, telefono=tienda.tel_verificado)
        user_id, email = await self.usuario(
            tienda, ROL_PERSISTIDO[rol], global_admin=rol == SUPERADMIN
        )
        return Actor(
            rol,
            tienda,
            user_id=user_id,
            email=email,
            token=await self.token(user_id),
            telefono=self.telefono_nuevo(),
        )

    async def admin(self, tienda: Tienda) -> dict[str, str]:
        """Headers del admin de la tienda con una sesion nueva (sobrevive a
        cualquier revocacion hecha por un test anterior)."""
        return {"Authorization": f"Bearer {await self.token(tienda.admin_id)}"}

    def token_forjado(self, user_id: str) -> str:
        """Token bien firmado atado a una sesion que no existe."""
        return create_access_token(data={"sub": user_id, "sid": "SESION-INEXISTENTE"})

    # -- requests -----------------------------------------------------------

    async def llamar(self, actor: Actor | None, llamada: Llamada) -> Response:
        headers = dict(llamada.headers)
        if actor is not None and llamada.con_token:
            headers.update(actor.headers())
        self.client.cookies.clear()
        for nombre, valor in llamada.cookies.items():
            self.client.cookies.set(nombre, valor)
        try:
            return await self.client.request(
                llamada.method,
                llamada.url,
                json=llamada.json,
                params=llamada.params,
                data=llamada.data,
                files=llamada.files,
                headers=headers,
            )
        finally:
            self.client.cookies.clear()

    async def ok(
        self, method: str, url: str, tienda: Tienda, esperado: int, **kwargs: Any
    ) -> Any:
        """Request de preparacion como admin de la tienda; falla si no sale."""
        res = await self.client.request(
            method, url, headers=await self.admin(tienda), **kwargs
        )
        assert res.status_code == esperado, f"{method} {url}: {res.text}"
        return res.json() if res.content else None

    # -- recursos frescos ---------------------------------------------------

    async def servicio(self, tienda: Tienda, nombre: str | None = None) -> str:
        body = await self.ok(
            "POST",
            "/services/",
            tienda,
            201,
            json={
                "name": nombre or self.unico("Servicio"),
                "duration_minutes": 30,
                "price": 10000,
            },
        )
        return cast(str, body["public_id"])

    async def staff(self, tienda: Tienda, nombre: str | None = None) -> str:
        body = await self.ok(
            "POST",
            "/staff/",
            tienda,
            201,
            json={
                "display_name": nombre or self.unico("Profesional"),
                "first_name": "Pro",
                "last_name": tienda.nombre,
                "email": f"{self.unico('pro')}@seguridad-{tienda.clave}.com",
                "service_ids": [tienda.servicio],
            },
        )
        return cast(str, body["public_id"])

    async def horario(self, tienda: Tienda, staff: str, dia_semana: int) -> str:
        body = await self.ok(
            "POST",
            f"/staff/{staff}/schedules",
            tienda,
            200,
            json={
                "day_of_week": dia_semana,
                "start_time": "06:00:00",
                "end_time": "18:00:00",
            },
        )
        return cast(str, body.get("public_id") or body.get("id"))

    async def turno(self, tienda: Tienda) -> str:
        body = await self.ok(
            "POST",
            "/appointments/",
            tienda,
            201,
            json={
                "service_id": tienda.servicio,
                "staff_id": tienda.staff,
                "starts_at": self.slot(tienda).isoformat(),
                "idempotency_key": self.unico("clave-turno"),
            },
        )
        return cast(str, body["public_id"])

    async def reserva_publica(
        self,
        tienda: Tienda,
        *,
        telefono: str,
        nombre: str,
        email: str | None = None,
    ) -> str:
        res = await self.client.post(
            "/public/appointments",
            json={
                "store_public_id": tienda.id,
                "service_id": tienda.servicio,
                "staff_id": tienda.staff,
                "starts_at": self.slot(tienda).isoformat(),
                "client_name": nombre,
                "client_phone": telefono,
                "accepts_terms": True,
                "client_email": email,
                "idempotency_key": self.unico("clave-publica"),
            },
        )
        assert res.status_code == 201, res.text
        return cast(str, res.json()["public_id"])

    async def turno_de(self, tienda: Tienda, actor: Actor) -> str:
        """Turno publico del telefono del actor (verificado o no)."""
        if actor.telefono == tienda.tel_verificado:
            return await self.reserva_publica(
                tienda,
                telefono=tienda.tel_verificado,
                nombre=tienda.nombre_verificado,
                email=tienda.email_verificado,
            )
        return await self.reserva_publica(
            tienda,
            telefono=actor.telefono or self.telefono_nuevo(),
            nombre=f"Cliente {tienda.nombre}",
        )

    async def bloqueo(self, tienda: Tienda) -> str:
        inicio = self.slot(tienda)
        body = await self.ok(
            "POST",
            "/appointment-blocks/",
            tienda,
            201,
            json={
                "staff_id": tienda.staff,
                "starts_at": inicio.isoformat(),
                "ends_at": (inicio + timedelta(minutes=30)).isoformat(),
                "reason": f"Motivo privado {tienda.nombre}",
            },
        )
        return cast(str, body["public_id"])

    async def promocion(self, tienda: Tienda, codigo: str | None = None) -> str:
        body = await self.ok(
            "POST",
            "/promotions/",
            tienda,
            201,
            json={
                "code": codigo or self.unico("PROMO").replace("-", ""),
                "title": f"Promo {tienda.nombre}",
                "value": 10,
            },
        )
        return cast(str, body["public_id"])

    async def pago(self, tienda: Tienda) -> str:
        turno = await self.turno(tienda)
        body = await self.ok(
            "POST",
            f"/payments/{turno}/manual-confirm",
            tienda,
            200,
            json={"amount": "100.00"},
        )
        return cast(str, body["public_id"])

    async def movimiento(self, tienda: Tienda) -> str:
        body = await self.ok(
            "POST",
            f"/ledger/customers/{tienda.cliente}/movements",
            tienda,
            200,
            json={"movement_type": "charge", "amount": "50.00"},
        )
        return cast(str, body.get("public_id") or body.get("id"))

    async def notificacion(self, tienda: Tienda) -> str:
        async with self.sesiones() as s:
            aviso = Notification(
                store_id=tienda.id,
                type="appointment.pending_confirmation",
                title=f"Aviso {tienda.nombre}",
                body=f"Detalle privado {tienda.nombre}",
            )
            s.add(aviso)
            await s.flush()
            aviso_id = str(aviso.id)
            await s.commit()
        return aviso_id

    async def media(self, tienda: Tienda) -> str:
        async with self.sesiones() as s:
            media = StoreMedia(
                store_id=tienda.id,
                kind="cover",
                content_type="image/png",
                byte_size=len(PNG_1X1),
                data=PNG_1X1,
            )
            s.add(media)
            await s.flush()
            media_id = str(media.id)
            await s.commit()
        return media_id

    async def espera(
        self, tienda: Tienda, telefono: str | None = None, nombre: str | None = None
    ) -> tuple[str, datetime]:
        """Entrada abierta de lista de espera y el horario que cubre.

        Con un telefono fijo (el del cliente verificado) se cierran antes sus
        entradas abiertas: el tope es de 3 por telefono y los tests que
        rechazan la baja las dejan abiertas.
        """
        if telefono:
            async with self.sesiones() as s:
                await s.execute(
                    update(WaitlistEntry)
                    .where(
                        WaitlistEntry.store_id == tienda.id,
                        WaitlistEntry.client_phone.in_(
                            [telefono, telefono.lstrip("+")]
                        ),
                    )
                    .values(status="cancelled")
                )
                await s.commit()
        inicio = self.slot(tienda)
        res = await self.client.post(
            "/public/waitlist",
            json={
                "store_public_id": tienda.id,
                "service_id": tienda.servicio,
                "staff_id": tienda.staff,
                "window_starts_at": inicio.isoformat(),
                "window_ends_at": (inicio + timedelta(minutes=60)).isoformat(),
                "client_name": nombre or f"Espera {tienda.nombre}",
                "client_phone": telefono or self.telefono_nuevo(),
            },
        )
        assert res.status_code == 201, res.text
        return cast(str, res.json()["public_id"]), inicio

    async def conectar_pasarela(self, tienda: Tienda) -> None:
        """Vuelve a conectar Mercado Pago: la matriz tambien lo desconecta."""
        await self.ok(
            "PUT",
            "/payments/gateway-config",
            tienda,
            200,
            json={
                "access_token": ACCESS_TOKEN_MP,
                "public_key": f"PUBLIC-KEY-{tienda.clave}",
                "webhook_secret": WEBHOOK_SECRET,
            },
        )

    async def usuario_objetivo(self, tienda: Tienda) -> str:
        """Cuenta de personal para editar, dar de baja o revocar."""
        user_id, _ = await self.usuario(tienda, "staff")
        return user_id

    async def token_de_reseteo(self, user_id: str) -> str:
        crudo = secrets.token_urlsafe(32)
        async with self.sesiones() as s:
            await s.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    password_reset_token_hash=hash_password_reset_token(crudo),
                    password_reset_expires_at=datetime.now(timezone.utc)
                    + timedelta(minutes=20),
                )
            )
            await s.commit()
        return crudo

    async def otp_verificado(self, tienda: Tienda, telefono: str, email: str) -> None:
        pedido = await self.client.post(
            "/public/otp/request",
            json={"store_public_id": tienda.id, "phone": telefono, "email": email},
        )
        assert pedido.status_code == 200, pedido.text
        codigo = pedido.json()["debug_code"]
        verificado = await self.client.post(
            "/public/otp/verify",
            json={"store_public_id": tienda.id, "phone": telefono, "code": codigo},
        )
        assert verificado.status_code == 200, verificado.text

    async def tienda_suelta(self) -> str:
        """Tienda sin datos, para operaciones de superadmin que la modifican."""
        async with self.sesiones() as s:
            nuevo_id = str(ulid.ULID())
            store = Store(
                id=nuevo_id,
                public_id=nuevo_id,
                name=self.unico("Tienda Suelta"),
                slug=self.unico("suelta"),
                theme_config={"business_type": "general"},
            )
            s.add(store)
            await s.flush()
            store_id = str(store.id)
            await s.commit()
        return store_id

    async def suspender(self, tienda: Tienda, suspendida: bool) -> None:
        """Suspende o reactiva la suscripcion ACTIVA de la tienda.

        No la del armado: el alta de suscripcion del superadmin (que la matriz
        ejercita) puede haber reemplazado a esa.
        """
        async with self.sesiones() as s:
            await s.execute(
                update(StoreSubscription)
                .where(
                    StoreSubscription.store_id == tienda.id,
                    StoreSubscription.is_active.is_(True),
                )
                .values(status="suspended" if suspendida else "active")
            )
            await s.commit()

    async def plan(self) -> str:
        async with self.sesiones() as s:
            plan = Plan(name=self.unico("Plan"), price=Decimal("500"))
            s.add(plan)
            await s.flush()
            plan_id = str(plan.id)
            await s.commit()
        return plan_id

    async def cupon(self) -> tuple[str, str]:
        """(id, codigo) de un cupon de suscripcion nuevo."""
        codigo = self.unico("CUPON").replace("-", "")
        async with self.sesiones() as s:
            cupon = SaaSCoupon(code=codigo, coupon_type="percent", value=Decimal("10"))
            s.add(cupon)
            await s.flush()
            cupon_id = str(cupon.id)
            await s.commit()
        return cupon_id, codigo

    async def suscribir(self, store_id: str) -> None:
        async with self.sesiones() as s:
            s.add(
                StoreSubscription(
                    store_id=store_id,
                    plan_id=self.plan_id,
                    plan_name="Plan Seguridad",
                    status="active",
                    base_amount=Decimal("1000"),
                    total_amount=Decimal("1000"),
                    currency="ARS",
                    current_period_start=datetime.now(timezone.utc) - timedelta(days=1),
                    current_period_end=datetime.now(timezone.utc) + timedelta(days=60),
                )
            )
            await s.commit()

    # -- armado -------------------------------------------------------------

    async def _tienda_base(self, tienda: Tienda) -> None:
        async with self.sesiones() as s:
            nuevo_id = str(ulid.ULID())
            store = Store(
                id=nuevo_id,
                public_id=nuevo_id,
                name=f"Tienda {tienda.nombre}",
                slug=f"seguridad-{tienda.clave}",
                theme_config={"business_type": "general"},
                feature_flags={"payments": True, "ledger": True},
                deposit_policy=(
                    "La sena se descuenta del total y se devuelve con 24hs de aviso."
                ),
            )
            s.add(store)
            await s.flush()
            tienda.id = str(store.id)
            tienda.slug = store.slug
            s.add(
                PaymentGatewayConfig(
                    store_id=store.id,
                    provider="mercadopago",
                    encrypted_access_token=encrypt_secret(ACCESS_TOKEN_MP),
                    public_key=f"PUBLIC-KEY-{tienda.clave}",
                    webhook_secret=WEBHOOK_SECRET,
                    connection_mode="manual",
                )
            )
            suscripcion = StoreSubscription(
                store_id=store.id,
                plan_id=self.plan_id,
                plan_name="Plan Seguridad",
                status="active",
                base_amount=Decimal("1000"),
                total_amount=Decimal("1000"),
                currency="ARS",
                current_period_start=datetime.now(timezone.utc) - timedelta(days=1),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=60),
            )
            s.add(suscripcion)
            await s.flush()
            tienda.suscripcion = str(suscripcion.id)
            await s.commit()

        tienda.admin_id, _ = await self.usuario(
            tienda,
            "admin",
            email=f"admin@seguridad-{tienda.clave}.com",
            nombre=f"Duena{tienda.nombre}",
        )
        tienda.profesional_id, _ = await self.usuario(
            tienda, "staff", nombre=f"Pro{tienda.nombre}"
        )
        tienda.recepcionista_id, _ = await self.usuario(
            tienda, "receptionist", nombre=f"Recepcion{tienda.nombre}"
        )

    async def _datos(self, tienda: Tienda, tel_base: int) -> None:
        tienda.servicio_nombre = f"Servicio {tienda.nombre} Exclusivo"
        tienda.servicio = await self.servicio(tienda, tienda.servicio_nombre)
        tienda.staff_nombre = f"Profesional {tienda.nombre} Exclusivo"
        tienda.staff = await self.staff(tienda, tienda.staff_nombre)
        for dia_semana in range(7):
            await self.horario(tienda, tienda.staff, dia_semana)

        tienda.tel_verificado = f"+5491170{tel_base:06d}"
        tienda.email_verificado = f"cliente@seguridad-{tienda.clave}.com"
        tienda.nombre_verificado = f"Cliente Verificado {tienda.nombre}"
        tienda.turno_publico = await self.reserva_publica(
            tienda,
            telefono=tienda.tel_verificado,
            nombre=tienda.nombre_verificado,
            email=tienda.email_verificado,
        )
        await self.otp_verificado(
            tienda, tienda.tel_verificado, tienda.email_verificado
        )
        tienda.tel_sin_otp = f"+5491170{tel_base + 1:06d}"
        tienda.nombre_sin_otp = f"Cliente Sin OTP {tienda.nombre}"
        tienda.turno_sin_otp = await self.reserva_publica(
            tienda, telefono=tienda.tel_sin_otp, nombre=tienda.nombre_sin_otp
        )

        tienda.turno = await self.turno(tienda)
        tienda.bloqueo = await self.bloqueo(tienda)
        tienda.codigo_promocion = f"{tienda.clave.upper()}10"
        tienda.promocion = await self.promocion(tienda, tienda.codigo_promocion)
        tienda.pago = await self.pago(tienda)

        busqueda = await self.ok(
            "GET",
            "/appointments/search",
            tienda,
            200,
            params={"page": 1, "page_size": 100},
        )
        tienda.cliente = next(
            fila["client_id"]
            for fila in busqueda["results"]
            if fila["public_id"] == tienda.turno_publico
        )
        tienda.movimiento = await self.movimiento(tienda)
        tienda.notificacion = await self.notificacion(tienda)
        tienda.media = await self.media(tienda)
        tienda.espera, _ = await self.espera(
            tienda,
            telefono=f"+5491170{tel_base + 2:06d}",
            nombre=f"Espera {tienda.nombre} Exclusiva",
        )

    def _marcadores(self, tienda: Tienda) -> None:
        """Lo que NUNCA puede aparecer en una respuesta dada a la otra tienda."""
        digitos = [t.lstrip("+") for t in (tienda.tel_verificado, tienda.tel_sin_otp)]
        tienda.marcadores = {
            tienda.id,
            tienda.slug,
            f"Tienda {tienda.nombre}",
            tienda.servicio,
            tienda.servicio_nombre,
            tienda.staff,
            tienda.staff_nombre,
            tienda.turno,
            tienda.turno_publico,
            tienda.turno_sin_otp,
            tienda.bloqueo,
            f"Motivo privado {tienda.nombre}",
            tienda.promocion,
            tienda.codigo_promocion,
            tienda.pago,
            tienda.cliente,
            tienda.movimiento,
            tienda.notificacion,
            f"Detalle privado {tienda.nombre}",
            tienda.media,
            tienda.espera,
            f"Espera {tienda.nombre} Exclusiva",
            tienda.suscripcion,
            tienda.admin_id,
            tienda.profesional_id,
            tienda.recepcionista_id,
            tienda.email_verificado,
            f"admin@seguridad-{tienda.clave}.com",
            f"seguridad-{tienda.clave}.com",
            tienda.nombre_verificado,
            tienda.nombre_sin_otp,
            *digitos,
        }

    async def armar(self) -> None:
        async with self.sesiones() as s:
            plan = Plan(name="Plan Seguridad", price=Decimal("1000"))
            s.add(plan)
            await s.flush()
            self.plan_id = str(plan.id)
            await s.commit()
        for tienda, tel_base in ((self.alfa, 100), (self.beta, 200)):
            await self._tienda_base(tienda)
            await self._datos(tienda, tel_base)
            self._marcadores(tienda)


class _TuberiaFalsa:
    def __init__(self, redis: "RedisFalso") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def incr(self, key: str) -> "_TuberiaFalsa":
        self._ops.append(("incr", (key,)))
        return self

    def expire(self, key: str, seconds: int) -> "_TuberiaFalsa":
        self._ops.append(("expire", (key, seconds)))
        return self

    def getex(self, key: str, ex: int | None = None) -> "_TuberiaFalsa":
        self._ops.append(("getex", (key, ex)))
        return self

    async def execute(self) -> list[Any]:
        resultados: list[Any] = []
        for nombre, args in self._ops:
            resultados.append(await getattr(self._redis, nombre)(*args))
        self._ops.clear()
        return resultados


class RedisFalso:
    """Redis en memoria con lo que usan la app y los limitadores.

    El doble de ``tests/conftest.py`` no tiene ``pipeline``, que es lo que usan
    el rate limit, el bloqueo de login y el presupuesto de OTP.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def getex(self, key: str, ex: int | None = None) -> str | None:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: object,
        nx: bool | None = None,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def setex(self, key: str, seconds: int, value: object) -> bool:
        self.store[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    async def incr(self, key: str) -> int:
        valor = int(self.store.get(key, 0)) + 1
        self.store[key] = str(valor)
        return valor

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    def pipeline(self, transaction: bool = True) -> _TuberiaFalsa:
        return _TuberiaFalsa(self)


def fugas(respuesta: Response, marcadores: set[str], enviado: str) -> list[str]:
    """Marcadores ajenos presentes en la respuesta y ausentes del request."""
    cuerpo = respuesta.text
    return sorted(m for m in marcadores if m and m in cuerpo and m not in enviado)


@asynccontextmanager
async def app_con_base_propia() -> AsyncIterator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession]]
]:
    """La app real sobre una SQLite en memoria nueva, una sesion por request.

    ``raise_app_exceptions=False``: un 500 tiene que llegar como respuesta
    para poder afirmar sobre el; con el default de httpx la excepcion sube al
    test y esconde el cuerpo que ve el cliente.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sesiones = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as session:
            yield session

    previo = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"x-raw-response": "true"},
        ) as client:
            yield client, sesiones
    finally:
        if previo is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previo
        await engine.dispose()
