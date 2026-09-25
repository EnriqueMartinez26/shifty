"""Tabla de rutas de la API: quien puede llamar cada una y como se acota.

Es la fuente de verdad de la suite de seguridad. Cada fila dice, para una
ruta (verbo + plantilla EXACTA de FastAPI):

- ``permitidos``: los roles que pasan. El resto tiene que rebotar con 401
  (sin credencial) o 403 (con credencial y sin permiso), nunca 404 ni 5xx.
- ``alcance``: como se acota a la tienda (ver ``Alcance``).
- ``fabrica``: arma un request MINIMO y valido. Recibe el actor (quien llama,
  con su tienda de contexto) y la tienda duena del recurso. En la matriz son
  la misma; en la pasada IDOR el actor es de alfa y el recurso de beta. Las
  mutaciones crean su propio recurso fresco, asi el orden de los tests no
  importa.
- ``ok``: los codigos que cuentan como "paso" para un rol permitido.

Una ruta nueva sin fila hace fallar ``test_inventario_de_rutas.py``: la fila
se agrega aca, con su matriz verificada contra el codigo (dependencias del
router y chequeos de rol del handler), no contra la documentacion.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import types
from typing import Any, Union, get_args, get_origin

from annotated_types import Ge, Gt, Le, Lt
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from main import app
from modules.auth.dependencies import get_current_user
from modules.auth.router import REFRESH_COOKIE
from tests.security.mundo import (
    ACCESS_TOKEN_MP,
    ADMIN_TIENDA,
    ANON,
    CLIENTE_OTP,
    NUEVA_PASSWORD,
    PASSWORD,
    PNG_1X1,
    PROFESIONAL,
    RECEPCIONISTA,
    ROLES,
    SUPERADMIN,
    WEBHOOK_SECRET,
    Actor,
    Llamada,
    Mundo,
    Tienda,
)


class Alcance(StrEnum):
    # Recurso de una tienda nombrado por id (path, query o body): con el id de
    # otra tienda tiene que responder 404/403 sin contar nada de ella.
    RECURSO = "store-scoped resource by id"
    # Opera sobre "mi tienda" sin nombrar recursos (listados, configuracion):
    # nunca puede devolver filas de otra.
    PROPIA = "own-store only"
    # Portal publico: la tienda viaja como store_public_id y los recursos
    # tienen que ser de ESA tienda.
    PUBLICA_TIENDA = "public by store_public_id"
    SUPERADMIN = "superadmin-only"
    # La propia cuenta del que llama (sesiones, clave, /me).
    CUENTA = "own account"
    # Publica sin datos de una tienda en juego, o publica por diseno aunque
    # nombre un recurso (la imagen del logo, el webhook firmado).
    PUBLICA = "public by design"


TODOS = frozenset(ROLES)
PERSONAL = frozenset({PROFESIONAL, RECEPCIONISTA, ADMIN_TIENDA, SUPERADMIN})
ADMINS = frozenset({ADMIN_TIENDA, SUPERADMIN})
# Chequeos que comparan el rol PERSISTIDO (``admin``/``staff``) o el flag
# global: la recepcionista queda afuera (docs/ROLE_MATRIX.md, "Diferencias").
OPERATIVOS = frozenset({PROFESIONAL, ADMIN_TIENDA, SUPERADMIN})
LECTORES_DE_REPORTES = OPERATIVOS  # core/roles.py::REPORT_VIEWERS
SOLO_SUPER = frozenset({SUPERADMIN})
SOLO_OTP = frozenset({CLIENTE_OTP})

OK = frozenset({200, 201, 204})
# Error de validacion de negocio sobre un recurso ajeno o inexistente.
IDOR_POR_ID = frozenset({403, 404})
IDOR_EN_BODY = frozenset({400, 403, 404, 409, 422})

Fabrica = Callable[[Mundo, Actor, Tienda], Awaitable[Llamada]]


@dataclass(frozen=True)
class Ruta:
    method: str
    path: str
    permitidos: frozenset[str]
    alcance: Alcance
    fabrica: Fabrica
    ok: frozenset[int] = OK
    # Codigos aceptados cuando el actor de alfa nombra un recurso de beta.
    # None: la pasada IDOR solo exige que no haya fuga ni 5xx.
    idor: frozenset[int] | None = None

    @property
    def clave(self) -> tuple[str, str]:
        return (self.method, self.path)

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


def _dia(t: Tienda, dias: int = 0) -> str:
    return (t.dia_base() + timedelta(days=dias)).isoformat()


def firma_webhook(
    data_id: str,
    request_id: str,
    *,
    secret: str = WEBHOOK_SECRET,
    ts: int | None = None,
) -> dict[str, str]:
    marca = str(ts if ts is not None else int(datetime.now(timezone.utc).timestamp()))
    manifiesto = f"id:{data_id};request-id:{request_id};ts:{marca};"
    firma = hmac.new(
        secret.encode("utf-8"), manifiesto.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {"x-request-id": request_id, "x-signature": f"ts={marca},v1={firma}"}


def _duenio(a: Actor, t: Tienda) -> str:
    """Telefono duenio del recurso publico: el del actor en la matriz; en la
    pasada IDOR, el cliente verificado de la OTRA tienda."""
    if a.rol == CLIENTE_OTP:
        return t.tel_verificado
    return a.telefono or ""


async def _turno_publico_de(m: Mundo, t: Tienda, telefono: str) -> str:
    if telefono == t.tel_verificado:
        return await m.reserva_publica(
            t,
            telefono=telefono,
            nombre=t.nombre_verificado,
            email=t.email_verificado,
        )
    return await m.reserva_publica(t, telefono=telefono, nombre="Cliente Anonimo")


async def _turno_pendiente(m: Mundo, t: Tienda) -> str:
    return await m.reserva_publica(
        t, telefono=m.telefono_nuevo(), nombre="Cliente Pendiente"
    )


# -- auth ---------------------------------------------------------------------


async def _login(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    _, email = await m.usuario(t, "staff")
    return Llamada("POST", "/auth/login", json={"email": email, "password": PASSWORD})


async def _cookie_de_refresh(m: Mundo, t: Tienda) -> str:
    _, email = await m.usuario(t, "staff")
    res = await m.client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert res.status_code == 200, res.text
    valor = res.cookies.get(REFRESH_COOKIE)
    m.client.cookies.clear()
    assert valor, "el login no devolvio la cookie de refresh"
    return valor


async def _refresh(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/auth/refresh",
        cookies={REFRESH_COOKIE: await _cookie_de_refresh(m, t)},
    )


async def _logout(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST", "/auth/logout", cookies={REFRESH_COOKIE: await _cookie_de_refresh(m, t)}
    )


async def _mis_sesiones(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/auth/sessions")


async def _cerrar_sesion(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    duenio = a.user_id if a.user_id and a.tienda is t else None
    duenio = duenio or await m.usuario_objetivo(t)
    sesion_id, _ = await m.sesion(duenio)
    return Llamada("DELETE", f"/auth/sessions/{sesion_id}")


async def _revocar_tienda(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("POST", "/auth/sessions/revoke-store")


async def _revocar_usuario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    objetivo = await m.usuario_objetivo(t)
    return Llamada("POST", f"/auth/sessions/revoke-user/{objetivo}")


async def _revocar_todo(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("POST", "/auth/sessions/revoke-all")


async def _olvide(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    _, email = await m.usuario(t, "staff")
    return Llamada("POST", "/auth/forgot-password", json={"email": email})


async def _resetear(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    objetivo = await m.usuario_objetivo(t)
    token = await m.token_de_reseteo(objetivo)
    return Llamada(
        "POST",
        "/auth/reset-password",
        json={"token": token, "new_password": NUEVA_PASSWORD},
    )


async def _cambiar_clave(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PUT",
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NUEVA_PASSWORD},
    )


async def _yo(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/me")


async def _raiz(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/")


# -- catalogo y personal ------------------------------------------------------


async def _crear_servicio(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/services/",
        json={"name": m.unico("Servicio"), "duration_minutes": 30, "price": 1000},
    )


async def _listar_servicios(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/services/")


async def _ver_servicio(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/services/{t.servicio}")


async def _editar_servicio(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/services/{await m.servicio(t)}",
        json={"description": "Descripcion nueva"},
    )


async def _borrar_servicio(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("DELETE", f"/services/{await m.servicio(t)}")


async def _subir_imagen_servicio(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        f"/services/{await m.servicio(t)}/image",
        files={"file": ("servicio.png", PNG_1X1, "image/png")},
    )


async def _borrar_imagen_servicio(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("DELETE", f"/services/{await m.servicio(t)}/image")


async def _listar_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/staff/")


async def _crear_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/staff/",
        json={
            "display_name": m.unico("Profesional"),
            "first_name": "Nuevo",
            "last_name": "Profesional",
            "email": f"{m.unico('alta')}@seguridad-nuevo.com",
            "service_ids": [t.servicio],
        },
    )


async def _ver_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/staff/{t.staff}")


async def _crear_horario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        f"/staff/{await m.staff(t)}/schedules",
        json={"day_of_week": 1, "start_time": "08:00:00", "end_time": "12:00:00"},
    )


async def _editar_horario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    staff = await m.staff(t)
    horario = await m.horario(t, staff, 2)
    return Llamada(
        "PATCH",
        f"/staff/{staff}/schedules/{horario}",
        json={"end_time": "17:00:00"},
    )


async def _borrar_horario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    staff = await m.staff(t)
    horario = await m.horario(t, staff, 3)
    return Llamada("DELETE", f"/staff/{staff}/schedules/{horario}")


async def _servicios_de_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("PATCH", f"/staff/{await m.staff(t)}/services", json=[t.servicio])


async def _editar_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/staff/{await m.staff(t)}",
        json={"display_name": m.unico("Renombrado")},
    )


async def _reemplazar_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PUT",
        f"/staff/{await m.staff(t)}",
        json={"display_name": m.unico("Reemplazado")},
    )


async def _borrar_staff(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("DELETE", f"/staff/{await m.staff(t)}")


# -- agenda -------------------------------------------------------------------


async def _agenda(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/appointments/", params={"date": _dia(t)})


async def _disponibilidad_panel(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        "/appointments/availability",
        params={"service_id": t.servicio, "date": _dia(t, 1)},
    )


async def _crear_turno(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/appointments/",
        json={
            "service_id": t.servicio,
            "staff_id": t.staff,
            "starts_at": m.slot(t).isoformat(),
            "idempotency_key": m.unico("clave-alta"),
        },
    )


async def _turno_confirmado(m: Mundo, t: Tienda) -> str:
    turno = await _turno_pendiente(m, t)
    await m.ok("PATCH", f"/appointments/{turno}/confirm", t, 200)
    return turno


def _transicion(accion: str, *, desde_confirmado: bool = False) -> Fabrica:
    async def fabrica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
        turno = await (
            _turno_confirmado(m, t) if desde_confirmado else _turno_pendiente(m, t)
        )
        return Llamada("PATCH", f"/appointments/{turno}/{accion}")

    return fabrica


async def _reprogramar(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/appointments/{await _turno_pendiente(m, t)}/reschedule",
        json={
            "new_starts_at": m.slot(t).isoformat(),
            "idempotency_key": m.unico("clave-reprogramar"),
        },
    )


async def _notas(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/appointments/{t.turno}/notes-staff",
        json={"notes_staff": "Nota interna"},
    )


async def _buscar_turnos(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/appointments/search", params={"page": 1, "page_size": 100})


async def _tablero(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/dashboard/summary")


# -- usuarios y reportes ------------------------------------------------------


async def _crear_usuario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/users/",
        json={
            "email": f"{m.unico('alta')}@seguridad-nuevo.com",
            "password": NUEVA_PASSWORD,
            "role": "staff",
            "first_name": "Nueva",
        },
    )


async def _listar_usuarios(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/users/")


async def _ver_usuario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/users/{await m.usuario_objetivo(t)}")


async def _editar_usuario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/users/{await m.usuario_objetivo(t)}",
        json={"first_name": "Editada"},
    )


async def _borrar_usuario(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("DELETE", f"/users/{await m.usuario_objetivo(t)}")


def _sin_cuerpo(method: str, url: str) -> Fabrica:
    async def fabrica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
        return Llamada(method, url)

    return fabrica


def _get(url: str) -> Fabrica:
    return _sin_cuerpo("GET", url)


def _post(url: str) -> Fabrica:
    return _sin_cuerpo("POST", url)


async def _exportar(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("POST", "/reports/export", json={"format": "csv"})


# -- tienda -------------------------------------------------------------------


async def _editar_tienda(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("PATCH", "/stores/me", json={"description": "Descripcion"})


async def _flags(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PUT", "/stores/me/feature-flags", json={"payments": True, "ledger": True}
    )


async def _subir_imagen(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/stores/me/media",
        data={"kind": "logo"},
        files={"file": ("logo.png", PNG_1X1, "image/png")},
    )


async def _ver_imagen(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/stores/media/{await m.media(t)}")


async def _ver_imagen_head(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("HEAD", f"/stores/media/{await m.media(t)}")


# -- bloqueos -----------------------------------------------------------------


def _rango(m: Mundo, t: Tienda) -> dict[str, str]:
    inicio = m.slot(t)
    return {
        "starts_at": inicio.isoformat(),
        "ends_at": (inicio + timedelta(minutes=30)).isoformat(),
    }


async def _previa_bloqueo(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/appointment-blocks/preview",
        json={"staff_id": t.staff, **_rango(m, t)},
    )


async def _cierre_de_tienda(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("POST", "/appointment-blocks/store-wide", json=_rango(m, t))


async def _crear_bloqueo(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/appointment-blocks/",
        json={"staff_id": t.staff, "reason": "Capacitacion", **_rango(m, t)},
    )


async def _bloqueos_en_lote(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/appointment-blocks/batch",
        json={"staff_id": t.staff, "recurrence": "none", **_rango(m, t)},
    )


async def _editar_bloqueo(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/appointment-blocks/{await m.bloqueo(t)}",
        json={"reason": "Otro motivo"},
    )


async def _borrar_bloqueo(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("DELETE", f"/appointment-blocks/{await m.bloqueo(t)}")


# -- pagos --------------------------------------------------------------------


async def _configurar_pasarela(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PUT",
        "/payments/gateway-config",
        json={
            "access_token": ACCESS_TOKEN_MP,
            "public_key": "PUBLIC-KEY",
            "webhook_secret": WEBHOOK_SECRET,
        },
    )


async def _preferencia(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    await m.conectar_pasarela(t)
    return Llamada("POST", f"/payments/preferences/{await m.turno(t)}")


async def _confirmar_pago(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        f"/payments/{await m.turno(t)}/manual-confirm",
        json={"amount": "100.00"},
    )


async def _reembolsar(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        f"/payments/{await m.pago(t)}/refund",
        json={"amount": "100.00", "reason": "Devolucion", "manual": True},
    )


async def _webhook(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    await m.conectar_pasarela(t)
    evento = m.unico("evento")
    return Llamada(
        "POST",
        "/payments/webhooks/mercadopago",
        params={"store_id": t.id},
        json={"id": evento, "type": "payment", "data": {"id": evento}},
        headers=firma_webhook(evento, m.unico("pedido")),
    )


async def _refrescar_oauth(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    await m.conectar_pasarela(t)
    return Llamada("POST", "/payments/mercadopago/oauth/refresh")


async def _procesar_outbox(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("POST", "/payments/outbox/process", params={"limit": 10})


# -- avisos, promociones y fiado ----------------------------------------------


async def _leer_aviso(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("POST", f"/notifications/{await m.notificacion(t)}/read")


async def _crear_promocion(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/promotions/",
        json={
            "code": m.unico("NUEVA").replace("-", ""),
            "title": "Promo nueva",
            "value": 10,
        },
    )


async def _editar_promocion(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/promotions/{await m.promocion(t)}",
        json={"title": "Promo editada"},
    )


async def _borrar_promocion(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("DELETE", f"/promotions/{await m.promocion(t)}")


async def _cotizar_promocion(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        "/promotions/preview",
        params={"service_id": t.servicio, "code": t.codigo_promocion},
    )


async def _buscar_clientes_de_fiado(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    # "Cliente" es parte del nombre de los clientes de las DOS tiendas: la de
    # alfa solo puede traer los suyos (D3, 2026-09-25).
    return Llamada("GET", "/ledger/clients", params={"q": "Cliente"})


async def _cuenta_de_fiado(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/ledger/customers/{t.cliente}")


async def _cargar_fiado(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        f"/ledger/customers/{t.cliente}/movements",
        json={"movement_type": "charge", "amount": "10.00"},
    )


async def _revertir_fiado(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    movimiento = await m.movimiento(t)
    return Llamada(
        "POST", f"/ledger/customers/{t.cliente}/movements/{movimiento}/reverse"
    )


# -- superadmin ---------------------------------------------------------------


async def _alta_de_tienda(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/superadmin/stores",
        json={"name": m.unico("Tienda Nueva"), "slug": m.unico("nueva")},
    )


def _de_tienda(sufijo: str) -> Fabrica:
    async def fabrica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
        return Llamada("GET", f"/superadmin/stores/{t.id}{sufijo}")

    return fabrica


async def _editar_tienda_global(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    # Reenvia el nombre que ya tiene: la fila existe y no cambia nada.
    return Llamada(
        "PATCH", f"/superadmin/stores/{t.id}", json={"name": f"Tienda {t.nombre}"}
    )


async def _alta_de_admin(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        f"/superadmin/stores/{t.id}/admins",
        json={
            "email": f"{m.unico('duena')}@seguridad-nuevo.com",
            "password": NUEVA_PASSWORD,
            "first_name": "Duena",
            "last_name": "Nueva",
        },
    )


async def _editar_usuario_global(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/superadmin/users/{await m.usuario_objetivo(t)}",
        json={"first_name": "Soporte"},
    )


async def _flag_global(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/superadmin/users/{await m.usuario_objetivo(t)}/global-admin",
        json={"is_global_admin": False},
    )


async def _alta_de_plan(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST", "/superadmin/plans", json={"name": m.unico("Plan"), "price": "100"}
    )


async def _editar_plan(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "PATCH",
        f"/superadmin/plans/{await m.plan()}",
        json={"description": "Plan editado"},
    )


async def _alta_de_suscripcion(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    # Tienda suelta: dar de alta una suscripcion reemplaza la activa, y la de
    # las tiendas del mundo se usa en la pasada de suspension.
    return Llamada(
        "POST",
        f"/superadmin/stores/{await m.tienda_suelta()}/subscription",
        json={"plan_id": m.plan_id, "status": "active"},
    )


async def _alta_de_cupon(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/superadmin/coupons",
        json={
            "code": m.unico("CUPON").replace("-", ""),
            "coupon_type": "percent",
            "value": "10",
        },
    )


async def _ver_cupon(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    cupon, _ = await m.cupon()
    return Llamada("GET", f"/superadmin/coupons/{cupon}")


async def _editar_cupon(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    cupon, _ = await m.cupon()
    return Llamada(
        "PATCH", f"/superadmin/coupons/{cupon}", json={"description": "Editado"}
    )


async def _canjear_cupon(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    tienda = await m.tienda_suelta()
    await m.suscribir(tienda)
    _, codigo = await m.cupon()
    return Llamada(
        "POST",
        f"/superadmin/stores/{tienda}/coupons/redeem",
        json={"coupon_code": codigo},
    )


# -- portal publico -----------------------------------------------------------


async def _vitrina(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/public/stores/{t.slug}")


async def _referencia_de_tienda(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/public/stores/{t.slug}/ref")


async def _servicios_publicos(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", "/public/services", params={"store_public_id": a.tienda.id})


async def _staff_publico(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        "/public/staff",
        params={"store_public_id": a.tienda.id, "service_id": t.servicio},
    )


async def _disponibilidad_publica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        "/public/availability",
        params={
            "store_public_id": a.tienda.id,
            "service_id": t.servicio,
            "date": _dia(t, 1),
        },
    )


async def _sena_publica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        "/public/deposit/preview",
        params={
            "store_public_id": a.tienda.id,
            "service_id": t.servicio,
            "starts_at": m.slot(t).isoformat(),
        },
    )


async def _promo_publica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        "/public/promotions/preview",
        params={
            "store_public_id": a.tienda.id,
            "service_id": t.servicio,
            "code": t.codigo_promocion,
        },
    )


async def _pedir_otp(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/public/otp/request",
        json={
            "store_public_id": a.tienda.id,
            "phone": m.telefono_nuevo(),
            "email": f"{m.unico('otp')}@seguridad-nuevo.com",
        },
    )


async def _verificar_otp(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    telefono = m.telefono_nuevo()
    pedido = await m.client.post(
        "/public/otp/request",
        json={
            "store_public_id": t.id,
            "phone": telefono,
            "email": f"{m.unico('otp')}@seguridad-nuevo.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    return Llamada(
        "POST",
        "/public/otp/verify",
        json={
            "store_public_id": a.tienda.id,
            "phone": telefono,
            "code": pedido.json()["debug_code"],
        },
    )


async def _reserva_publica(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/public/appointments",
        json={
            "store_public_id": a.tienda.id,
            "service_id": t.servicio,
            "staff_id": t.staff,
            "starts_at": m.slot(t).isoformat(),
            "client_name": "Cliente Portal",
            "client_phone": m.telefono_nuevo(),
            "accepts_terms": True,
            "idempotency_key": m.unico("clave-portal"),
        },
    )


async def _estado_de_pago(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "GET",
        f"/public/payments/{t.pago}/status",
        params={"store_public_id": a.tienda.id},
    )


async def _mis_turnos(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada("GET", f"/public/client/{a.tienda.id}/{_duenio(a, t)}/appointments")


async def _cancelar_mi_turno(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    turno = await _turno_publico_de(m, t, _duenio(a, t))
    return Llamada(
        "PATCH",
        f"/public/client/appointments/{turno}/cancel",
        json={"phone": a.telefono},
    )


async def _reprogramar_mi_turno(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    turno = await _turno_publico_de(m, t, _duenio(a, t))
    return Llamada(
        "PATCH",
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": a.telefono,
            "new_starts_at": m.slot(t).isoformat(),
            "idempotency_key": m.unico("clave-autogestion"),
        },
    )


async def _anotarse(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    inicio = m.slot(t)
    return Llamada(
        "POST",
        "/public/waitlist",
        json={
            "store_public_id": a.tienda.id,
            "service_id": t.servicio,
            "staff_id": t.staff,
            "window_starts_at": inicio.isoformat(),
            "window_ends_at": (inicio + timedelta(minutes=60)).isoformat(),
            "client_name": "Cliente Espera",
            "client_phone": m.telefono_nuevo(),
        },
    )


async def _mis_esperas(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    return Llamada(
        "POST",
        "/public/waitlist/mine",
        json={"store_public_id": a.tienda.id, "phone": a.telefono},
    )


async def _dejar_espera(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    entrada, _ = await m.espera(t, telefono=_duenio(a, t))
    return Llamada(
        "POST",
        f"/public/waitlist/{entrada}/leave",
        json={"store_public_id": a.tienda.id, "phone": a.telefono},
    )


# -- lista de espera del panel ------------------------------------------------


async def _baja_de_espera(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    entrada, _ = await m.espera(t)
    return Llamada("DELETE", f"/waitlist/{entrada}")


async def _reservar_desde_espera(m: Mundo, a: Actor, t: Tienda) -> Llamada:
    entrada, inicio = await m.espera(t)
    return Llamada(
        "POST",
        f"/waitlist/{entrada}/book",
        json={"starts_at": inicio.isoformat(), "staff_id": t.staff},
    )


R = Ruta
A = Alcance

TABLA: tuple[Ruta, ...] = (
    # auth
    R("POST", "/auth/login", TODOS, A.PUBLICA, _login),
    R("POST", "/auth/refresh", TODOS, A.PUBLICA, _refresh),
    R("POST", "/auth/logout", TODOS, A.PUBLICA, _logout),
    R("GET", "/auth/sessions", PERSONAL, A.CUENTA, _mis_sesiones),
    R(
        "DELETE",
        "/auth/sessions/{session_id}",
        PERSONAL,
        A.RECURSO,
        _cerrar_sesion,
        idor=IDOR_POR_ID,
    ),
    R("POST", "/auth/sessions/revoke-store", ADMINS, A.PROPIA, _revocar_tienda),
    R(
        "POST",
        "/auth/sessions/revoke-user/{user_public_id}",
        ADMINS,
        A.RECURSO,
        _revocar_usuario,
        idor=IDOR_POR_ID,
    ),
    R("POST", "/auth/sessions/revoke-all", SOLO_SUPER, A.SUPERADMIN, _revocar_todo),
    R("POST", "/auth/forgot-password", TODOS, A.PUBLICA, _olvide),
    R("POST", "/auth/reset-password", TODOS, A.PUBLICA, _resetear),
    R("PUT", "/auth/change-password", PERSONAL, A.CUENTA, _cambiar_clave),
    R("GET", "/", TODOS, A.PUBLICA, _raiz),
    R("GET", "/me", PERSONAL, A.CUENTA, _yo),
    # servicios
    R("POST", "/services/", ADMINS, A.PROPIA, _crear_servicio),
    R("GET", "/services/", PERSONAL, A.PROPIA, _listar_servicios),
    R(
        "GET",
        "/services/{public_id}",
        PERSONAL,
        A.RECURSO,
        _ver_servicio,
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/services/{public_id}",
        ADMINS,
        A.RECURSO,
        _editar_servicio,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/services/{public_id}",
        ADMINS,
        A.RECURSO,
        _borrar_servicio,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/services/{public_id}/image",
        ADMINS,
        A.RECURSO,
        _subir_imagen_servicio,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/services/{public_id}/image",
        ADMINS,
        A.RECURSO,
        _borrar_imagen_servicio,
        idor=IDOR_POR_ID,
    ),
    # personal
    R("GET", "/staff/", PERSONAL, A.PROPIA, _listar_staff),
    R("POST", "/staff/", ADMINS, A.RECURSO, _crear_staff, idor=IDOR_EN_BODY),
    R("GET", "/staff/{public_id}", PERSONAL, A.RECURSO, _ver_staff, idor=IDOR_POR_ID),
    R(
        "POST",
        "/staff/{public_id}/schedules",
        ADMINS,
        A.RECURSO,
        _crear_horario,
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/staff/{public_id}/schedules/{schedule_id}",
        ADMINS,
        A.RECURSO,
        _editar_horario,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/staff/{public_id}/schedules/{schedule_id}",
        ADMINS,
        A.RECURSO,
        _borrar_horario,
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/staff/{public_id}/services",
        ADMINS,
        A.RECURSO,
        _servicios_de_staff,
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/staff/{public_id}",
        ADMINS,
        A.RECURSO,
        _editar_staff,
        idor=IDOR_POR_ID,
    ),
    R(
        "PUT",
        "/staff/{public_id}",
        ADMINS,
        A.RECURSO,
        _reemplazar_staff,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/staff/{public_id}",
        ADMINS,
        A.RECURSO,
        _borrar_staff,
        idor=IDOR_POR_ID,
    ),
    # agenda
    R("GET", "/appointments/", PERSONAL, A.PROPIA, _agenda),
    R(
        "GET",
        "/appointments/availability",
        TODOS,
        A.RECURSO,
        _disponibilidad_panel,
        idor=frozenset({200, 404}),
    ),
    R("POST", "/appointments/", PERSONAL, A.RECURSO, _crear_turno, idor=IDOR_EN_BODY),
    R(
        "PATCH",
        "/appointments/{public_id}/cancel",
        PERSONAL,
        A.RECURSO,
        _transicion("cancel"),
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/appointments/{public_id}/release",
        ADMINS,
        A.RECURSO,
        _transicion("release"),
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/appointments/{public_id}/confirm",
        OPERATIVOS,
        A.RECURSO,
        _transicion("confirm"),
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/appointments/{public_id}/complete",
        OPERATIVOS,
        A.RECURSO,
        _transicion("complete", desde_confirmado=True),
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/appointments/{public_id}/absent",
        OPERATIVOS,
        A.RECURSO,
        _transicion("absent", desde_confirmado=True),
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/appointments/{public_id}/reschedule",
        PERSONAL,
        A.RECURSO,
        _reprogramar,
        idor=IDOR_POR_ID,
    ),
    R(
        "PATCH",
        "/appointments/{public_id}/notes-staff",
        OPERATIVOS,
        A.RECURSO,
        _notas,
        idor=IDOR_POR_ID,
    ),
    R("GET", "/appointments/search", PERSONAL, A.PROPIA, _buscar_turnos),
    R("GET", "/dashboard/summary", PERSONAL, A.PROPIA, _tablero),
    # usuarios
    R("POST", "/users/", ADMINS, A.PROPIA, _crear_usuario),
    R("GET", "/users/", ADMINS, A.PROPIA, _listar_usuarios),
    R("GET", "/users/{public_id}", ADMINS, A.RECURSO, _ver_usuario, idor=IDOR_POR_ID),
    R(
        "PATCH",
        "/users/{public_id}",
        ADMINS,
        A.RECURSO,
        _editar_usuario,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/users/{public_id}",
        ADMINS,
        A.RECURSO,
        _borrar_usuario,
        idor=IDOR_POR_ID,
    ),
    # reportes
    R(
        "GET",
        "/reports/summary",
        LECTORES_DE_REPORTES,
        A.PROPIA,
        _get("/reports/summary"),
    ),
    R(
        "GET",
        "/reports/professionals",
        LECTORES_DE_REPORTES,
        A.PROPIA,
        _get("/reports/professionals"),
    ),
    R("GET", "/reports/trend", LECTORES_DE_REPORTES, A.PROPIA, _get("/reports/trend")),
    R("POST", "/reports/export", ADMINS, A.PROPIA, _exportar),
    R("GET", "/reports/audit-logs", ADMINS, A.PROPIA, _get("/reports/audit-logs")),
    # tienda
    R("GET", "/stores/me", PERSONAL, A.PROPIA, _get("/stores/me")),
    R("PATCH", "/stores/me", ADMINS, A.PROPIA, _editar_tienda),
    R(
        "GET",
        "/stores/me/subscription",
        PERSONAL,
        A.PROPIA,
        _get("/stores/me/subscription"),
    ),
    R(
        "GET",
        "/stores/me/feature-flags",
        PERSONAL,
        A.PROPIA,
        _get("/stores/me/feature-flags"),
    ),
    R("PUT", "/stores/me/feature-flags", ADMINS, A.PROPIA, _flags),
    R("POST", "/stores/me/media", ADMINS, A.PROPIA, _subir_imagen),
    # Terminos B2B (L1, 2026-09-25): acepta SOLO el admin de la tienda (el
    # soporte global no acepta un contrato por ella); leer el estado, admins.
    R(
        "POST",
        "/stores/me/terms-acceptance",
        frozenset({ADMIN_TIENDA}),
        A.PROPIA,
        _post("/stores/me/terms-acceptance"),
    ),
    R(
        "GET",
        "/stores/me/terms-acceptance",
        ADMINS,
        A.PROPIA,
        _get("/stores/me/terms-acceptance"),
    ),
    # La imagen es publica por diseno: el portal muestra el logo sin login y
    # el id es un ULID que solo se conoce por la vitrina.
    R("GET", "/stores/media/{media_id}", TODOS, A.PUBLICA, _ver_imagen),
    R("HEAD", "/stores/media/{media_id}", TODOS, A.PUBLICA, _ver_imagen_head),
    # bloqueos
    # FF-14: la recepcion LEE los bloqueos (su agenda los muestra); crear,
    # editar y borrar siguen siendo de OPERATIVOS.
    R(
        "GET",
        "/appointment-blocks/",
        PERSONAL,
        A.PROPIA,
        _get("/appointment-blocks/"),
    ),
    R(
        "POST",
        "/appointment-blocks/preview",
        OPERATIVOS,
        A.RECURSO,
        _previa_bloqueo,
        idor=IDOR_EN_BODY,
    ),
    R(
        "POST",
        "/appointment-blocks/store-wide",
        OPERATIVOS,
        A.PROPIA,
        _cierre_de_tienda,
    ),
    R(
        "POST",
        "/appointment-blocks/",
        OPERATIVOS,
        A.RECURSO,
        _crear_bloqueo,
        idor=IDOR_EN_BODY,
    ),
    R(
        "POST",
        "/appointment-blocks/batch",
        OPERATIVOS,
        A.RECURSO,
        _bloqueos_en_lote,
        idor=IDOR_EN_BODY,
    ),
    R(
        "GET",
        "/appointment-blocks/templates",
        OPERATIVOS,
        A.PROPIA,
        _get("/appointment-blocks/templates"),
    ),
    R(
        "PATCH",
        "/appointment-blocks/{public_id}",
        OPERATIVOS,
        A.RECURSO,
        _editar_bloqueo,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/appointment-blocks/{public_id}",
        OPERATIVOS,
        A.RECURSO,
        _borrar_bloqueo,
        idor=IDOR_POR_ID,
    ),
    # pagos
    R(
        "GET",
        "/payments/gateway-config",
        OPERATIVOS,
        A.PROPIA,
        _get("/payments/gateway-config"),
    ),
    R("PUT", "/payments/gateway-config", ADMINS, A.PROPIA, _configurar_pasarela),
    R(
        "POST",
        "/payments/mercadopago/oauth/start",
        ADMINS,
        A.PROPIA,
        _post("/payments/mercadopago/oauth/start"),
    ),
    # Anonima por diseno: la autoriza el ``state`` firmado, no una sesion.
    R(
        "GET",
        "/payments/mercadopago/oauth/callback",
        TODOS,
        A.PUBLICA,
        _get("/payments/mercadopago/oauth/callback"),
        ok=frozenset({303}),
    ),
    R(
        "POST",
        "/payments/mercadopago/oauth/refresh",
        ADMINS,
        A.PROPIA,
        _refrescar_oauth,
    ),
    R(
        "DELETE",
        "/payments/mercadopago/oauth/connection",
        ADMINS,
        A.PROPIA,
        _sin_cuerpo("DELETE", "/payments/mercadopago/oauth/connection"),
    ),
    R(
        "POST",
        "/payments/preferences/{appointment_id}",
        OPERATIVOS,
        A.RECURSO,
        _preferencia,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/payments/{appointment_id}/manual-confirm",
        OPERATIVOS,
        A.RECURSO,
        _confirmar_pago,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/payments/{payment_id}/refund",
        ADMINS,
        A.RECURSO,
        _reembolsar,
        idor=IDOR_POR_ID,
    ),
    # Anonimo por diseno: lo autoriza la firma HMAC (test_caminos_de_abuso).
    R(
        "POST",
        "/payments/webhooks/mercadopago",
        TODOS,
        A.PUBLICA,
        _webhook,
    ),
    R(
        "GET",
        "/payments/outbox/stats",
        ADMINS,
        A.PROPIA,
        _get("/payments/outbox/stats"),
    ),
    R(
        "GET",
        "/payments/reconciliation/summary",
        ADMINS,
        A.PROPIA,
        _get("/payments/reconciliation/summary"),
    ),
    R("POST", "/payments/outbox/process", ADMINS, A.PROPIA, _procesar_outbox),
    # avisos
    R("GET", "/notifications", PERSONAL, A.PROPIA, _get("/notifications")),
    R(
        "POST",
        "/notifications/{notification_id}/read",
        PERSONAL,
        A.RECURSO,
        _leer_aviso,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/notifications/read-all",
        PERSONAL,
        A.PROPIA,
        _post("/notifications/read-all"),
    ),
    # promociones
    R("GET", "/promotions/", ADMINS, A.PROPIA, _get("/promotions/")),
    R("POST", "/promotions/", ADMINS, A.PROPIA, _crear_promocion),
    R(
        "PATCH",
        "/promotions/{promotion_public_id}",
        ADMINS,
        A.RECURSO,
        _editar_promocion,
        idor=IDOR_POR_ID,
    ),
    R(
        "DELETE",
        "/promotions/{promotion_public_id}",
        ADMINS,
        A.RECURSO,
        _borrar_promocion,
        idor=IDOR_POR_ID,
    ),
    R(
        "GET",
        "/promotions/preview",
        ADMINS,
        A.RECURSO,
        _cotizar_promocion,
        idor=IDOR_EN_BODY,
    ),
    # fiado
    R("GET", "/ledger/summary", OPERATIVOS, A.PROPIA, _get("/ledger/summary")),
    R("GET", "/ledger/clients", OPERATIVOS, A.PROPIA, _buscar_clientes_de_fiado),
    R(
        "GET",
        "/ledger/customers/{client_id}",
        OPERATIVOS,
        A.RECURSO,
        _cuenta_de_fiado,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/ledger/customers/{client_id}/movements",
        OPERATIVOS,
        A.RECURSO,
        _cargar_fiado,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/ledger/customers/{client_id}/movements/{movement_id}/reverse",
        OPERATIVOS,
        A.RECURSO,
        _revertir_fiado,
        idor=IDOR_POR_ID,
    ),
    # operacion
    R("GET", "/ops/health/live", TODOS, A.PUBLICA, _get("/ops/health/live")),
    # 503 es la respuesta correcta si Redis no esta: el chequeo dice la verdad.
    R(
        "GET",
        "/ops/health/ready",
        TODOS,
        A.PUBLICA,
        _get("/ops/health/ready"),
        ok=frozenset({200, 503}),
    ),
    R("GET", "/ops/slo", ADMINS, A.PROPIA, _get("/ops/slo")),
    # superadmin
    R(
        "GET",
        "/superadmin/stores",
        SOLO_SUPER,
        A.SUPERADMIN,
        _get("/superadmin/stores"),
    ),
    R("POST", "/superadmin/stores", SOLO_SUPER, A.SUPERADMIN, _alta_de_tienda),
    R(
        "GET",
        "/superadmin/stores/{store_public_id}",
        SOLO_SUPER,
        A.SUPERADMIN,
        _de_tienda(""),
    ),
    R(
        "GET",
        "/superadmin/stores/{store_public_id}/overview",
        SOLO_SUPER,
        A.SUPERADMIN,
        _de_tienda("/overview"),
    ),
    R(
        "GET",
        "/superadmin/stores/{store_public_id}/audit-logs",
        SOLO_SUPER,
        A.SUPERADMIN,
        _de_tienda("/audit-logs"),
    ),
    R(
        "PATCH",
        "/superadmin/stores/{store_public_id}",
        SOLO_SUPER,
        A.SUPERADMIN,
        _editar_tienda_global,
    ),
    R(
        "POST",
        "/superadmin/stores/{store_public_id}/admins",
        SOLO_SUPER,
        A.SUPERADMIN,
        _alta_de_admin,
    ),
    R(
        "GET",
        "/superadmin/stores/{store_public_id}/users",
        SOLO_SUPER,
        A.SUPERADMIN,
        _de_tienda("/users"),
    ),
    R(
        "PATCH",
        "/superadmin/users/{user_public_id}",
        SOLO_SUPER,
        A.SUPERADMIN,
        _editar_usuario_global,
    ),
    R(
        "PATCH",
        "/superadmin/users/{user_public_id}/global-admin",
        SOLO_SUPER,
        A.SUPERADMIN,
        _flag_global,
    ),
    R("GET", "/superadmin/plans", SOLO_SUPER, A.SUPERADMIN, _get("/superadmin/plans")),
    R("POST", "/superadmin/plans", SOLO_SUPER, A.SUPERADMIN, _alta_de_plan),
    R(
        "PATCH",
        "/superadmin/plans/{plan_public_id}",
        SOLO_SUPER,
        A.SUPERADMIN,
        _editar_plan,
    ),
    R(
        "GET",
        "/superadmin/stores/{store_public_id}/subscription",
        SOLO_SUPER,
        A.SUPERADMIN,
        _de_tienda("/subscription"),
    ),
    R(
        "POST",
        "/superadmin/stores/{store_public_id}/subscription",
        SOLO_SUPER,
        A.SUPERADMIN,
        _alta_de_suscripcion,
    ),
    R(
        "GET",
        "/superadmin/coupons",
        SOLO_SUPER,
        A.SUPERADMIN,
        _get("/superadmin/coupons"),
    ),
    R("POST", "/superadmin/coupons", SOLO_SUPER, A.SUPERADMIN, _alta_de_cupon),
    R(
        "GET",
        "/superadmin/coupons/{coupon_public_id}",
        SOLO_SUPER,
        A.SUPERADMIN,
        _ver_cupon,
    ),
    R(
        "PATCH",
        "/superadmin/coupons/{coupon_public_id}",
        SOLO_SUPER,
        A.SUPERADMIN,
        _editar_cupon,
    ),
    R(
        "POST",
        "/superadmin/stores/{store_public_id}/coupons/redeem",
        SOLO_SUPER,
        A.SUPERADMIN,
        _canjear_cupon,
    ),
    R(
        "GET",
        "/superadmin/stores/{store_public_id}/coupon-redemptions",
        SOLO_SUPER,
        A.SUPERADMIN,
        _de_tienda("/coupon-redemptions"),
    ),
    # portal publico
    R("GET", "/public/stores/{slug}", TODOS, A.PUBLICA, _vitrina),
    # Versiones vigentes de los textos legales: sin datos de ninguna tienda.
    R(
        "GET",
        "/public/legal/versions",
        TODOS,
        A.PUBLICA,
        _get("/public/legal/versions"),
    ),
    # FF-16: sigue resolviendo con la tienda suspendida ("Mis turnos").
    R("GET", "/public/stores/{slug}/ref", TODOS, A.PUBLICA, _referencia_de_tienda),
    R("GET", "/public/services", TODOS, A.PUBLICA_TIENDA, _servicios_publicos),
    R(
        "GET",
        "/public/staff",
        TODOS,
        A.PUBLICA_TIENDA,
        _staff_publico,
        idor=frozenset({400, 404, 422}),
    ),
    R(
        "GET",
        "/public/availability",
        TODOS,
        A.PUBLICA_TIENDA,
        _disponibilidad_publica,
        idor=frozenset({200, 404, 422}),
    ),
    R(
        "GET",
        "/public/deposit/preview",
        TODOS,
        A.PUBLICA_TIENDA,
        _sena_publica,
        idor=frozenset({400, 404, 422}),
    ),
    R(
        "GET",
        "/public/promotions/preview",
        TODOS,
        A.PUBLICA_TIENDA,
        _promo_publica,
        idor=frozenset({400, 404, 422}),
    ),
    R("POST", "/public/otp/request", TODOS, A.PUBLICA_TIENDA, _pedir_otp),
    R(
        "POST",
        "/public/otp/verify",
        TODOS,
        A.PUBLICA_TIENDA,
        _verificar_otp,
        idor=frozenset({400, 401, 403, 404, 422}),
    ),
    R(
        "POST",
        "/public/appointments",
        TODOS,
        A.PUBLICA_TIENDA,
        _reserva_publica,
        # Sin 422: la llamada manda el consentimiento (PV-09), asi que un 422
        # seria un cuerpo invalido y no la guarda de tienda cruzada.
        idor=frozenset({400, 404}),
    ),
    R(
        "GET",
        "/public/payments/{payment_public_id}/status",
        TODOS,
        A.PUBLICA_TIENDA,
        _estado_de_pago,
        idor=frozenset({404}),
    ),
    R(
        "GET",
        "/public/client/{store_public_id}/{phone}/appointments",
        SOLO_OTP,
        A.PUBLICA_TIENDA,
        _mis_turnos,
        idor=frozenset({403, 404}),
    ),
    R(
        "PATCH",
        "/public/client/appointments/{public_id}/cancel",
        SOLO_OTP,
        A.PUBLICA_TIENDA,
        _cancelar_mi_turno,
        idor=frozenset({403, 404}),
    ),
    R(
        "PATCH",
        "/public/client/appointments/{public_id}/reschedule",
        SOLO_OTP,
        A.PUBLICA_TIENDA,
        _reprogramar_mi_turno,
        idor=frozenset({403, 404}),
    ),
    R(
        "POST",
        "/public/waitlist",
        TODOS,
        A.PUBLICA_TIENDA,
        _anotarse,
        idor=frozenset({400, 404, 422}),
    ),
    R("POST", "/public/waitlist/mine", SOLO_OTP, A.PUBLICA_TIENDA, _mis_esperas),
    R(
        "POST",
        "/public/waitlist/{entry_id}/leave",
        SOLO_OTP,
        A.PUBLICA_TIENDA,
        _dejar_espera,
        idor=frozenset({403, 404}),
    ),
    # lista de espera del panel
    R("GET", "/waitlist/", PERSONAL, A.PROPIA, _get("/waitlist/")),
    R(
        "DELETE",
        "/waitlist/{entry_id}",
        ADMINS,
        A.RECURSO,
        _baja_de_espera,
        idor=IDOR_POR_ID,
    ),
    R(
        "POST",
        "/waitlist/{entry_id}/book",
        ADMINS,
        A.RECURSO,
        _reservar_desde_espera,
        idor=IDOR_POR_ID,
    ),
)

POR_CLAVE: dict[tuple[str, str], Ruta] = {ruta.clave: ruta for ruta in TABLA}

# Defectos reales que la suite encontro. Cada uno es un test en
# xfail(strict=True): cuando se arregle, el test pasa, el xfail estricto
# falla y la fila se borra de aca. (verbo, ruta, rol) -> motivo.
DEFECTOS_MATRIZ: dict[tuple[str, str, str], str] = {}
# (verbo, ruta, rol del actor) -> motivo, para la pasada entre tiendas.
DEFECTOS_IDOR: dict[tuple[str, str, str], str] = {}


# -- introspeccion de la tabla de rutas de FastAPI ------------------------------


def rutas_de_la_app() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def claves_de(route: APIRoute) -> list[tuple[str, str]]:
    return [(method, route.path) for method in sorted(route.methods)]


def _llamadas(dependant: Dependant) -> set[Callable[..., Any]]:
    encontradas: set[Callable[..., Any]] = set()
    pendientes = list(dependant.dependencies)
    while pendientes:
        actual = pendientes.pop()
        if actual.call is not None:
            encontradas.add(actual.call)
        pendientes.extend(actual.dependencies)
    return encontradas


def depende_de(route: APIRoute, dependencia: Callable[..., Any]) -> bool:
    return dependencia in _llamadas(route.dependant)


def requiere_token(route: APIRoute) -> bool:
    """La ruta exige sesion: sin token el rechazo correcto es 401, no 403."""
    return depende_de(route, get_current_user)


def ruta_de_la_app(clave: tuple[str, str]) -> APIRoute:
    for route in rutas_de_la_app():
        if clave in claves_de(route):
            return route
    raise KeyError(clave)


def _es_numerico(anotacion: Any) -> bool:
    if anotacion in (int, float):
        return True
    origen = get_origin(anotacion)
    if origen in (Union, types.UnionType):
        return any(_es_numerico(arg) for arg in get_args(anotacion))
    return False


def _parametros(route: APIRoute) -> list[Any]:
    campos = list(route.dependant.query_params) + list(route.dependant.path_params)
    pendientes = list(route.dependant.dependencies)
    while pendientes:
        dep = pendientes.pop()
        campos.extend(dep.query_params)
        campos.extend(dep.path_params)
        pendientes.extend(dep.dependencies)
    return campos


def cotas_numericas() -> list[
    tuple[str, str, str, int | float | None, int | float | None]
]:
    """(verbo, ruta, parametro, minimo, maximo) de cada parametro numerico."""
    filas = []
    for route in rutas_de_la_app():
        for campo in _parametros(route):
            info = campo.field_info
            if not _es_numerico(info.annotation):
                continue
            minimo: int | float | None = None
            maximo: int | float | None = None
            for regla in info.metadata:
                if isinstance(regla, Ge):
                    minimo = regla.ge  # type: ignore[assignment]
                elif isinstance(regla, Gt):
                    minimo = regla.gt  # type: ignore[assignment]
                elif isinstance(regla, Le):
                    maximo = regla.le  # type: ignore[assignment]
                elif isinstance(regla, Lt):
                    maximo = regla.lt  # type: ignore[assignment]
            for method, path in claves_de(route):
                filas.append((method, path, campo.name, minimo, maximo))
    return filas
