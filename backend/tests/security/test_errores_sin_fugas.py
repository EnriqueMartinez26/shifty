"""Cuerpos de error: siempre el sobre canonico, nunca una traza ni un dato ajeno.

Regla 20 de CLAUDE.md: errores neutros hacia afuera. Cada respuesta de la
matriz y de la pasada entre tiendas ya pasa por
``verificacion.revisar_respuesta``; aca se fuerzan los errores que esas
pasadas no generan: rutas y metodos inexistentes, JSON roto, content-type
prohibido, cuerpo gigante, tokens basura o revocados, y excepciones internas
(un 500 con SQL en el mensaje, un IntegrityError con el valor que choco, un
error de Postgres) para comprobar que ninguna llega al cliente.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from httpx import Response
from sqlalchemy.exc import DBAPIError, IntegrityError

from modules.services.repository import ServiceRepository
from tests.security.mundo import ADMIN_TIENDA, Mundo, fugas
from tests.security.verificacion import (
    Defecto,
    exigir,
    pagos_sin_red,
    problemas_del_error,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

EMAIL_INTERNO = "filtrado@seguridad-interna.com"
SQL_INTERNO = f"SELECT hashed_password FROM users WHERE email = '{EMAIL_INTERNO}'"

Generador = Callable[[Mundo], Awaitable[Response]]


@pytest.fixture(scope="module", autouse=True)
def _pagos() -> Iterator[None]:
    with pagos_sin_red():
        yield


async def _ruta_inexistente(m: Mundo) -> Response:
    return await m.client.get("/no-existe/nada")


async def _metodo_no_permitido(m: Mundo) -> Response:
    return await m.client.put("/services/", headers=await m.admin(m.alfa), json={})


async def _json_roto(m: Mundo) -> Response:
    return await m.client.post(
        "/services/",
        headers={**await m.admin(m.alfa), "content-type": "application/json"},
        content=b'{"name": "sin cerrar',
    )


async def _tipo_equivocado(m: Mundo) -> Response:
    return await m.client.post("/services/", headers=await m.admin(m.alfa), json=[1, 2])


async def _content_type_prohibido(m: Mundo) -> Response:
    return await m.client.post(
        "/services/",
        headers={**await m.admin(m.alfa), "content-type": "text/plain"},
        content=b"name=x",
    )


async def _cuerpo_gigante(m: Mundo) -> Response:
    return await m.client.post(
        "/services/",
        headers=await m.admin(m.alfa),
        json={"name": "Grande", "description": "x" * 40_000},
    )


async def _token_basura(m: Mundo) -> Response:
    return await m.client.get("/me", headers={"Authorization": "Bearer basura.basura"})


async def _token_de_sesion_inexistente(m: Mundo) -> Response:
    token = m.token_forjado(m.alfa.admin_id)
    return await m.client.get("/me", headers={"Authorization": f"Bearer {token}"})


async def _token_de_sesion_revocada(m: Mundo) -> Response:
    headers = await m.admin(m.alfa)
    salida = await m.client.post(
        "/auth/sessions/revoke-user/" + m.alfa.admin_id, headers=headers
    )
    assert salida.status_code == 200, salida.text
    return await m.client.get("/me", headers=headers)


async def _token_en_cookie(m: Mundo) -> Response:
    """La cookie ``access_token`` ya no es credencial (anti-CSRF)."""
    token = await m.token(m.alfa.admin_id)
    m.client.cookies.set("access_token", token)
    try:
        return await m.client.get("/me")
    finally:
        m.client.cookies.clear()


async def _fecha_invalida(m: Mundo) -> Response:
    return await m.client.get(
        "/appointments/", headers=await m.admin(m.alfa), params={"date": "ayer"}
    )


async def _id_con_forma_invalida(m: Mundo) -> Response:
    return await m.client.get("/services/" + "x" * 80, headers=await m.admin(m.alfa))


GENERADORES: dict[str, tuple[Generador, set[int]]] = {
    "ruta_inexistente": (_ruta_inexistente, {404}),
    "metodo_no_permitido": (_metodo_no_permitido, {405}),
    "json_roto": (_json_roto, {400, 422}),
    "tipo_equivocado": (_tipo_equivocado, {422}),
    "content_type_prohibido": (_content_type_prohibido, {415}),
    "cuerpo_gigante": (_cuerpo_gigante, {413}),
    "token_basura": (_token_basura, {401}),
    "token_de_sesion_inexistente": (_token_de_sesion_inexistente, {401}),
    "token_de_sesion_revocada": (_token_de_sesion_revocada, {401}),
    "token_en_cookie": (_token_en_cookie, {401}),
    "fecha_invalida": (_fecha_invalida, {422}),
    "id_con_forma_invalida": (_id_con_forma_invalida, {404, 422}),
}


@pytest.mark.parametrize("caso", sorted(GENERADORES))
async def test_cada_error_sale_en_el_sobre_canonico(mundo: Mundo, caso: str) -> None:
    generador, esperados = GENERADORES[caso]
    res = await generador(mundo)
    assert res.status_code in esperados, f"{caso}: {res.status_code} {res.text[:300]}"
    problemas = problemas_del_error(res)
    exigir(not problemas, f"{caso}: {problemas} {res.text[:300]}")
    filtrado = fugas(res, mundo.beta.marcadores, "")
    exigir(not filtrado, f"{caso} devolvio datos de beta: {filtrado}")


class _OrigenPostgres(Exception):
    sqlstate = "22021"


def _explota_con(excepcion: BaseException) -> Callable[..., Awaitable[Any]]:
    async def falla(*args: Any, **kwargs: Any) -> Any:
        raise excepcion

    return falla


EXCEPCIONES_INTERNAS: dict[str, tuple[BaseException, int]] = {
    "runtime_con_sql": (RuntimeError(SQL_INTERNO), 500),
    "integrity_con_el_valor": (
        IntegrityError(
            f"INSERT INTO users (email) VALUES ('{EMAIL_INTERNO}')",
            {"email": EMAIL_INTERNO},
            Exception(
                "duplicate key value violates unique constraint uq_users_email_lower"
            ),
        ),
        409,
    ),
    "dbapi_de_postgres": (
        DBAPIError(SQL_INTERNO, {"email": EMAIL_INTERNO}, _OrigenPostgres("0x00")),
        500,
    ),
    "key_error": (KeyError("hashed_password"), 500),
}


@pytest.mark.parametrize("caso", sorted(EXCEPCIONES_INTERNAS))
async def test_una_excepcion_interna_no_llega_al_cliente(
    mundo: Mundo, monkeypatch: pytest.MonkeyPatch, caso: str
) -> None:
    excepcion, esperado = EXCEPCIONES_INTERNAS[caso]
    monkeypatch.setattr(ServiceRepository, "get_all", _explota_con(excepcion))
    res = await mundo.client.get("/services/", headers=await mundo.admin(mundo.alfa))

    assert res.status_code == esperado, res.text
    problemas = problemas_del_error(res)
    exigir(not problemas, f"{caso}: {problemas} {res.text[:300]}")
    for interno in (EMAIL_INTERNO, "hashed_password", "users", "0x00", "duplicate"):
        exigir(interno not in res.text, f"{caso} filtro {interno!r}: {res.text[:300]}")


@pytest.mark.xfail(
    strict=True,
    raises=Defecto,
    reason=(
        "SEG-04 (baja): pedir el link de pago de un turno con la cuenta de "
        "Mercado Pago desconectada responde 502 PAYMENT_LINK_CREATION_FAILED "
        "y el mensaje arrastra el texto de la excepcion interna "
        "(modules/payments/router.py::create_payment_preference, f'...: {exc}'). "
        "Es una precondicion de la tienda, no una falla del proveedor: deberia "
        "ser un 409/422 con mensaje fijo. Un 5xx esperable ensucia las alertas "
        "y el texto crudo del RuntimeError puede traer el detalle de MP."
    ),
)
async def test_cobrar_sin_pasarela_conectada_es_un_error_de_la_tienda(
    mundo: Mundo,
) -> None:
    actor = await mundo.actor(ADMIN_TIENDA, mundo.alfa)
    desconexion = await mundo.client.delete(
        "/payments/mercadopago/oauth/connection", headers=actor.headers()
    )
    assert desconexion.status_code == 200, desconexion.text
    try:
        turno = await mundo.turno(mundo.alfa)
        res = await mundo.client.post(
            f"/payments/preferences/{turno}", headers=actor.headers()
        )
    finally:
        await mundo.conectar_pasarela(mundo.alfa)

    assert not problemas_del_error(res), res.text
    exigir(
        res.status_code in {409, 422},
        f"sin pasarela respondio {res.status_code}: {res.text[:300]}",
    )
