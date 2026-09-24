"""Entrada hostil sacada de la tabla de rutas: cotas numericas y texto libre.

- Regla 9: todo parametro numerico lleva ``ge`` Y ``le``. Aca se prueba que
  la cota funciona: el tope + 1, un numero que desborda cualquier entero de
  la base y el minimo - 1 responden 422, nunca 500.
- Regla 19: ``reject_control_chars`` en el texto que se publica. Cada campo
  de texto de cada body JSON se manda con un bidi override y un zero-width
  sobre un request por lo demas valido: 422. Los campos que no se publican
  van en ``NO_ES_TEXTO_PUBLICADO`` con su motivo.
- NUL en CUALQUIER campo de texto que llegue a la base: Postgres no lo acepta
  en un parametro de texto y el error sale como 500.

Los campos salen de los schemas de las rutas de la app, no de una lista a
mano: un endpoint nuevo entra solo.
"""

from __future__ import annotations

import types
from collections.abc import Iterator
from typing import Any, Union, get_args, get_origin

import pytest
from _pytest.mark.structures import ParameterSet
from pydantic import BaseModel

from tests.security.mundo import (
    ADMIN_TIENDA,
    ANON,
    CLIENTE_OTP,
    PROFESIONAL,
    RECEPCIONISTA,
    SUPERADMIN,
    Mundo,
)
from tests.security.rutas import (
    POR_CLAVE,
    TABLA,
    Ruta,
    cotas_numericas,
    ruta_de_la_app,
)
from tests.security.verificacion import (
    exigir,
    pagos_sin_red,
    problemas_del_error,
    revisar_respuesta,
    xfail_de,
)

# Mismo loop que el fixture ``mundo`` (de modulo); solo en los tests async.
en_el_loop_del_mundo = pytest.mark.asyncio(loop_scope="module")

BIDI = chr(0x202E)
ZERO_WIDTH = chr(0x200B)
# Invisibles de la regla 19: spoofing visual tipo Trojan Source.
INVISIBLES = f"Texto{BIDI}con{ZERO_WIDTH}invisibles"
# NUL: Postgres no lo acepta en un parametro de texto (SQLSTATE 22021,
# CharacterNotInRepertoireError) y ``main.py::dbapi_error_handler`` lo deja
# subir como 500. SQLite lo guarda sin chistar: en esta suite un 2xx o un
# 403/404 con NUL es un 500 en produccion.
NUL = "Texto" + chr(0) + "con-nul"

_SECRETO = "no se publica: es una credencial"
_OPACO = "no se publica: identificador opaco que solo usa el servidor"
_PANEL = "no se publica: solo lo ve el personal de la tienda en el panel"
_SOPORTE = "no se publica: lo carga el soporte global y lo ve el dueno en su panel"
_TELEFONO = "no se publica: dato de contacto del usuario, no texto del portal"

# (verbo, ruta, campo) -> por que ese campo queda fuera de la regla 19.
NO_ES_TEXTO_PUBLICADO: dict[tuple[str, str, str], str] = {
    ("POST", "/auth/login", "password"): _SECRETO,
    ("PUT", "/auth/change-password", "current_password"): _SECRETO,
    ("PUT", "/payments/gateway-config", "access_token"): _SECRETO,
    ("PUT", "/payments/gateway-config", "public_key"): _SECRETO,
    ("PUT", "/payments/gateway-config", "webhook_secret"): _SECRETO,
    ("POST", "/appointments/", "idempotency_key"): _OPACO,
    ("PATCH", "/appointments/{public_id}/reschedule", "idempotency_key"): _OPACO,
    ("POST", "/public/appointments", "idempotency_key"): _OPACO,
    (
        "PATCH",
        "/public/client/appointments/{public_id}/reschedule",
        "idempotency_key",
    ): _OPACO,
    ("POST", "/auth/reset-password", "token"): _SECRETO,
    ("POST", "/appointment-blocks/", "staff_id"): _OPACO,
    ("POST", "/appointment-blocks/batch", "staff_id"): _OPACO,
    ("POST", "/appointment-blocks/preview", "staff_id"): _OPACO,
    ("PATCH", "/public/client/appointments/{public_id}/cancel", "phone"): _OPACO,
    ("PATCH", "/public/client/appointments/{public_id}/reschedule", "phone"): _OPACO,
    ("POST", "/ledger/customers/{client_id}/movements", "notes"): _PANEL,
    ("POST", "/payments/{appointment_id}/manual-confirm", "notes"): _PANEL,
    ("POST", "/payments/{payment_id}/refund", "reason"): _PANEL,
    ("POST", "/promotions/", "description"): _PANEL,
    ("PATCH", "/promotions/{promotion_public_id}", "description"): _PANEL,
    ("POST", "/users/", "phone"): _TELEFONO,
    ("PATCH", "/users/{public_id}", "phone"): _TELEFONO,
    ("POST", "/superadmin/stores/{store_public_id}/admins", "first_name"): _SOPORTE,
    ("POST", "/superadmin/stores/{store_public_id}/admins", "last_name"): _SOPORTE,
    ("POST", "/superadmin/stores/{store_public_id}/admins", "phone"): _TELEFONO,
    ("PATCH", "/superadmin/users/{user_public_id}", "first_name"): _SOPORTE,
    ("PATCH", "/superadmin/users/{user_public_id}", "last_name"): _SOPORTE,
    ("PATCH", "/superadmin/users/{user_public_id}", "phone"): _TELEFONO,
    ("POST", "/superadmin/plans", "name"): _SOPORTE,
    ("POST", "/superadmin/plans", "description"): _SOPORTE,
    ("POST", "/superadmin/plans", "billing_interval"): _SOPORTE,
    ("PATCH", "/superadmin/plans/{plan_public_id}", "name"): _SOPORTE,
    ("PATCH", "/superadmin/plans/{plan_public_id}", "description"): _SOPORTE,
    ("PATCH", "/superadmin/plans/{plan_public_id}", "billing_interval"): _SOPORTE,
    ("POST", "/superadmin/coupons", "code"): _SOPORTE,
    ("POST", "/superadmin/coupons", "description"): _SOPORTE,
    ("PATCH", "/superadmin/coupons/{coupon_public_id}", "code"): _SOPORTE,
    ("PATCH", "/superadmin/coupons/{coupon_public_id}", "description"): _SOPORTE,
}

# (verbo, ruta, campo) que NUNCA llegan a un parametro SQL: el NUL no puede
# romper Postgres y el rechazo que corresponde es el de la regla de negocio.
NO_LLEGA_A_LA_BASE: dict[tuple[str, str, str], str] = {
    ("POST", "/auth/login", "password"): "se compara contra el hash con bcrypt",
    ("PUT", "/auth/change-password", "current_password"): "idem, bcrypt",
    ("PUT", "/payments/gateway-config", "access_token"): "se guarda cifrado",
}

# Bodies que la fabrica no manda como JSON: el logout toma el refresh de la
# cookie y la imagen va como multipart.
SIN_BODY_JSON = {("POST", "/auth/logout"), ("POST", "/stores/me/media")}

_PROMO_PUBLICADA = (
    "SEG-02 (media): el titulo de una promocion acepta bidi y zero-width y se "
    "publica tal cual en /public/promotions/preview (title). Regla 19: falta "
    "reject_control_chars en modules/promotions/schemas.py (PromotionBase y "
    "PromotionUpdate)."
)
DEFECTOS_INVISIBLES: dict[tuple[str, str, str], str] = {
    ("POST", "/promotions/", "title"): _PROMO_PUBLICADA,
    ("PATCH", "/promotions/{promotion_public_id}", "title"): _PROMO_PUBLICADA,
}

_NUL_A_POSTGRES = (
    "SEG-03 (alta): un NUL (U+0000) en este campo llega a un parametro SQL. "
    "Postgres lo rechaza con SQLSTATE 22021 (CharacterNotInRepertoireError; "
    "verificado con SELECT $1::text contra el Postgres local) y "
    "main.py::dbapi_error_handler lo deja subir como 500. SQLite lo acepta, "
    "por eso la suite de integracion no lo ve. Falta rechazar NUL en la "
    "validacion de entrada de todos los campos de texto, no solo en los que "
    "usan reject_control_chars."
)
DEFECTOS_NUL: dict[tuple[str, str, str], str] = {
    clave: _NUL_A_POSTGRES
    for clave in (
        ("POST", "/appointments/", "idempotency_key"),
        ("PATCH", "/appointments/{public_id}/reschedule", "idempotency_key"),
        ("POST", "/public/appointments", "idempotency_key"),
        (
            "PATCH",
            "/public/client/appointments/{public_id}/reschedule",
            "idempotency_key",
        ),
        ("POST", "/appointment-blocks/", "staff_id"),
        ("POST", "/appointment-blocks/batch", "staff_id"),
        ("POST", "/appointment-blocks/preview", "staff_id"),
        ("PATCH", "/public/client/appointments/{public_id}/cancel", "phone"),
        ("PATCH", "/public/client/appointments/{public_id}/reschedule", "phone"),
        ("POST", "/ledger/customers/{client_id}/movements", "notes"),
        ("POST", "/payments/{appointment_id}/manual-confirm", "notes"),
        ("POST", "/payments/{payment_id}/refund", "reason"),
        ("POST", "/promotions/", "title"),
        ("POST", "/promotions/", "description"),
        ("PATCH", "/promotions/{promotion_public_id}", "title"),
        ("PATCH", "/promotions/{promotion_public_id}", "description"),
        ("POST", "/users/", "phone"),
        ("PATCH", "/users/{public_id}", "phone"),
        ("PUT", "/payments/gateway-config", "public_key"),
        ("PUT", "/payments/gateway-config", "webhook_secret"),
        ("POST", "/superadmin/stores/{store_public_id}/admins", "first_name"),
        ("POST", "/superadmin/stores/{store_public_id}/admins", "last_name"),
        ("POST", "/superadmin/stores/{store_public_id}/admins", "phone"),
        ("PATCH", "/superadmin/users/{user_public_id}", "first_name"),
        ("PATCH", "/superadmin/users/{user_public_id}", "last_name"),
        ("PATCH", "/superadmin/users/{user_public_id}", "phone"),
        ("POST", "/superadmin/plans", "name"),
        ("POST", "/superadmin/plans", "description"),
        ("POST", "/superadmin/plans", "billing_interval"),
        ("PATCH", "/superadmin/plans/{plan_public_id}", "name"),
        ("PATCH", "/superadmin/plans/{plan_public_id}", "description"),
        ("PATCH", "/superadmin/plans/{plan_public_id}", "billing_interval"),
        ("POST", "/superadmin/coupons", "code"),
        ("POST", "/superadmin/coupons", "description"),
        ("PATCH", "/superadmin/coupons/{coupon_public_id}", "code"),
        ("PATCH", "/superadmin/coupons/{coupon_public_id}", "description"),
    )
}


@pytest.fixture(scope="module", autouse=True)
def _pagos() -> Iterator[None]:
    with pagos_sin_red():
        yield


def _rol_para(ruta: Ruta) -> str:
    for rol in (
        ADMIN_TIENDA,
        SUPERADMIN,
        PROFESIONAL,
        RECEPCIONISTA,
        ANON,
        CLIENTE_OTP,
    ):
        if rol in ruta.permitidos:
            return rol
    raise AssertionError(f"{ruta} no tiene roles permitidos")


# -- cotas numericas ----------------------------------------------------------


def _casos_de_cotas() -> Iterator[ParameterSet]:
    for method, path, nombre, minimo, maximo in cotas_numericas():
        ruta = POR_CLAVE[(method, path)]
        valores: list[tuple[str, int | float]] = [("desborde", 10**30)]
        if maximo is not None:
            valores.append(("tope+1", maximo + 1))
        if minimo is not None:
            valores.append(("minimo-1", minimo - 1))
        for etiqueta, valor in valores:
            yield pytest.param(ruta, nombre, valor, id=f"{ruta} ?{nombre} {etiqueta}")


@en_el_loop_del_mundo
@pytest.mark.parametrize(("ruta", "parametro", "valor"), list(_casos_de_cotas()))
async def test_un_parametro_fuera_de_cota_es_422(
    mundo: Mundo, ruta: Ruta, parametro: str, valor: int | float
) -> None:
    actor = await mundo.actor(_rol_para(ruta), mundo.alfa)
    llamada = await ruta.fabrica(mundo, actor, mundo.alfa)
    llamada.params = {**(llamada.params or {}), parametro: valor}
    res = await mundo.llamar(actor, llamada)

    assert res.status_code == 422, (
        f"{ruta} ?{parametro}={valor} respondio {res.status_code}: {res.text[:300]}"
    )
    revisar_respuesta(res, llamada, mundo.beta.marcadores)


# -- caracteres de control en el texto ----------------------------------------


def _es_texto(anotacion: Any) -> bool:
    if anotacion is str:
        return True
    if get_origin(anotacion) in (Union, types.UnionType):
        return any(_es_texto(arg) for arg in get_args(anotacion))
    return False


def _campos_de_texto(ruta: Ruta) -> list[str]:
    cuerpo = ruta_de_la_app(ruta.clave).body_field
    if cuerpo is None:
        return []
    modelo = cuerpo.field_info.annotation
    if get_origin(modelo) in (Union, types.UnionType):
        modelo = next((arg for arg in get_args(modelo) if isinstance(arg, type)), None)
    if not (isinstance(modelo, type) and issubclass(modelo, BaseModel)):
        return []
    return [
        nombre
        for nombre, campo in modelo.model_fields.items()
        if _es_texto(campo.annotation)
    ]


def _casos_de_texto(
    excluidos: dict[tuple[str, str, str], str],
    defectos: dict[tuple[str, str, str], str],
) -> Iterator[ParameterSet]:
    for ruta in TABLA:
        if ruta.clave in SIN_BODY_JSON:
            continue
        for campo in _campos_de_texto(ruta):
            clave = (ruta.method, ruta.path, campo)
            if clave in excluidos:
                continue
            yield pytest.param(
                ruta, campo, id=f"{ruta} .{campo}", marks=xfail_de(defectos.get(clave))
            )


async def _mandar_en(mundo: Mundo, ruta: Ruta, campo: str, valor: str) -> None:
    actor = await mundo.actor(_rol_para(ruta), mundo.alfa)
    llamada = await ruta.fabrica(mundo, actor, mundo.alfa)
    assert isinstance(llamada.json, dict), f"{ruta}: la fabrica no manda un body JSON"
    llamada.json = {**llamada.json, campo: valor}
    res = await mundo.llamar(actor, llamada)

    exigir(
        res.status_code == 422,
        f"{ruta} acepto {valor!r} en '{campo}': {res.status_code} {res.text[:300]}",
    )
    assert not problemas_del_error(res), res.text[:300]
    assert BIDI not in res.text and chr(0) not in res.text


@en_el_loop_del_mundo
@pytest.mark.parametrize(
    ("ruta", "campo"),
    list(_casos_de_texto(NO_ES_TEXTO_PUBLICADO, DEFECTOS_INVISIBLES)),
)
async def test_el_texto_publicado_rechaza_invisibles(
    mundo: Mundo, ruta: Ruta, campo: str
) -> None:
    """Regla 19: bidi y zero-width en texto que se publica -> 422."""
    await _mandar_en(mundo, ruta, campo, INVISIBLES)


@en_el_loop_del_mundo
@pytest.mark.parametrize(
    ("ruta", "campo"), list(_casos_de_texto(NO_LLEGA_A_LA_BASE, DEFECTOS_NUL))
)
async def test_ningun_campo_de_texto_deja_pasar_un_nul(
    mundo: Mundo, ruta: Ruta, campo: str
) -> None:
    """Un NUL que llega a Postgres es un 500 (22021): se rechaza con 422."""
    await _mandar_en(mundo, ruta, campo, NUL)


def test_hay_campos_de_texto_para_probar() -> None:
    """Si la introspeccion de bodies se rompe, los casos desaparecen en
    silencio: este test lo impide."""
    assert len(list(_casos_de_texto({}, {}))) > 40


def test_las_excepciones_de_texto_siguen_vigentes() -> None:
    """Una excepcion o un defecto sobre un campo que ya no existe se borra."""
    vivos = {
        (ruta.method, ruta.path, campo)
        for ruta in TABLA
        for campo in _campos_de_texto(ruta)
    }
    for tabla in (
        NO_ES_TEXTO_PUBLICADO,
        NO_LLEGA_A_LA_BASE,
        DEFECTOS_INVISIBLES,
        DEFECTOS_NUL,
    ):
        muertos = set(tabla) - vivos
        assert not muertos, f"claves sin campo: {sorted(muertos)}"
