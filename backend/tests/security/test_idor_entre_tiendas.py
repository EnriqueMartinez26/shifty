"""IDOR entre tiendas: un actor de alfa nombrando recursos de beta.

Alfa y beta tienen la misma forma de datos (servicio, profesional, turnos,
bloqueo, promocion, cobro, fiado, aviso, imagen, lista de espera y
suscripcion). Para cada fila de la tabla se arma el request con el actor de
ALFA y los recursos de BETA:

- recurso por id (path, query o body): 404/403 segun la fila. Un 2xx es que
  la app opero sobre la tienda ajena.
- listados y configuracion propia: los de alfa no traen filas de beta.
- portal publico con la tienda de alfa y un recurso de beta (servicio de
  beta bajo alfa, pago de beta bajo alfa, turno de beta con el telefono
  verificado de alfa): 404/422/403, nunca los datos de beta.
- soporte global leyendo beta con el admin de alfa: 403.

En TODOS los casos el cuerpo no puede contener identificadores ni datos de
beta que el request no haya mandado (ids, nombres, telefonos, emails,
codigos). Tambien se corre con el superadmin sentado en alfa: su panel ve su
propia tienda (``core/roles.py::store_scope_for``) y el filtro ``store_id`` es
lo unico que lo separa de las demas, porque RLS lo deja pasar.

SQLite no aplica RLS: esto prueba los filtros ``store_id`` de la aplicacion,
que CLAUDE.md §2 exige como capa propia.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _pytest.mark.structures import ParameterSet

from tests.security.mundo import (
    ADMIN_TIENDA,
    ANON,
    CLIENTE_OTP,
    PROFESIONAL,
    SUPERADMIN,
    Llamada,
    Mundo,
)
from tests.security.rutas import (
    DEFECTOS_IDOR,
    IDOR_POR_ID,
    SOLO_OTP,
    TABLA,
    Alcance,
    Ruta,
)
from tests.security.verificacion import (
    exigir,
    pagos_sin_red,
    revisar_respuesta,
    xfail_de,
)

# Mismo loop que el fixture ``mundo`` (de modulo); solo en los tests async.
en_el_loop_del_mundo = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module", autouse=True)
def _pagos() -> Iterator[None]:
    with pagos_sin_red():
        yield


def _actores(ruta: Ruta) -> list[str]:
    if ruta.alcance is Alcance.PUBLICA:
        return []
    if ruta.alcance is Alcance.PUBLICA_TIENDA:
        return [CLIENTE_OTP if ruta.permitidos == SOLO_OTP else ANON]
    if ruta.alcance is Alcance.SUPERADMIN:
        return [ADMIN_TIENDA]
    return [rol for rol in (ADMIN_TIENDA, SUPERADMIN) if rol in ruta.permitidos]


def _casos() -> Iterator[ParameterSet]:
    for ruta in TABLA:
        for rol in _actores(ruta):
            motivo = DEFECTOS_IDOR.get((ruta.method, ruta.path, rol))
            yield pytest.param(ruta, rol, id=f"{ruta} [{rol}]", marks=xfail_de(motivo))


@en_el_loop_del_mundo
@pytest.mark.parametrize(("ruta", "rol"), list(_casos()))
async def test_alfa_no_alcanza_ni_ve_a_beta(mundo: Mundo, ruta: Ruta, rol: str) -> None:
    alfa, beta = mundo.alfa, mundo.beta
    actor = await mundo.actor(rol, alfa)
    llamada = await ruta.fabrica(mundo, actor, beta)
    res = await mundo.llamar(actor, llamada)

    revisar_respuesta(res, llamada, beta.marcadores)
    exigir(res.status_code < 500, f"{ruta}: {res.status_code} {res.text[:300]}")
    if ruta.alcance is Alcance.SUPERADMIN:
        exigir(res.status_code == 403, f"{ruta}: {res.status_code} {res.text[:300]}")
    elif ruta.idor is not None:
        exigir(
            res.status_code in ruta.idor,
            f"{ruta} con {rol} de alfa sobre un recurso de beta respondio "
            f"{res.status_code} (esperado {sorted(ruta.idor)}): {res.text[:400]}",
        )


def test_cada_recurso_por_id_tiene_su_caso_entre_tiendas() -> None:
    """Una fila de recurso por id sin codigos IDOR no se estaria probando."""
    sin_caso = [
        str(ruta)
        for ruta in TABLA
        if ruta.alcance is Alcance.RECURSO and (ruta.idor is None or not _actores(ruta))
    ]
    assert not sin_caso, "filas RECURSO sin codigos idor:\n" + "\n".join(sin_caso)


@en_el_loop_del_mundo
@pytest.mark.parametrize(
    ("url", "clave"),
    [
        ("/services/", "public_id"),
        ("/staff/", "public_id"),
        ("/promotions/", "public_id"),
        ("/appointment-blocks/", "public_id"),
        ("/waitlist/", "public_id"),
        ("/users/", "public_id"),
        ("/ledger/clients", "public_id"),
    ],
)
async def test_los_listados_de_alfa_traen_solo_filas_de_alfa(
    mundo: Mundo, url: str, clave: str
) -> None:
    """Ademas de no traer nada de beta, el listado de alfa no esta vacio: un
    listado vacio pasaria el chequeo de fugas sin probar el filtro."""
    headers = await mundo.admin(mundo.alfa)
    res = await mundo.client.get(url, headers=headers)
    assert res.status_code == 200, res.text
    filas = res.json()
    assert isinstance(filas, list) and filas, f"{url} vino vacio para alfa"
    ids = {fila[clave] for fila in filas}
    assert not ids & mundo.beta.marcadores, f"{url} trae filas de beta"


@en_el_loop_del_mundo
async def test_el_profesional_de_alfa_no_alcanza_el_fiado_ni_los_clientes_de_beta(
    mundo: Mundo,
) -> None:
    """D3 (2026-09-25): el profesional usa el fiado y su buscador de clientes.

    Con el id de un cliente de beta: 404 al leer, cargar o revertir su fiado.
    El buscador de alfa no trae a nadie de beta ni ninguna cuenta del personal
    de alfa (admin, profesional, recepcion, el propio actor): solo clientes.
    """
    alfa, beta = mundo.alfa, mundo.beta
    actor = await mundo.actor(PROFESIONAL, alfa)
    ajenas = (
        Llamada("GET", f"/ledger/customers/{beta.cliente}"),
        Llamada(
            "POST",
            f"/ledger/customers/{beta.cliente}/movements",
            json={"movement_type": "charge", "amount": "10.00"},
        ),
        Llamada(
            "POST",
            f"/ledger/customers/{beta.cliente}/movements/{beta.movimiento}/reverse",
        ),
    )
    for llamada in ajenas:
        res = await mundo.llamar(actor, llamada)
        revisar_respuesta(res, llamada, beta.marcadores)
        assert res.status_code in IDOR_POR_ID, (llamada.url, res.status_code, res.text)

    for params in ({"q": "Cliente"}, {}):
        llamada = Llamada("GET", "/ledger/clients", params=params)
        res = await mundo.llamar(actor, llamada)
        revisar_respuesta(res, llamada, beta.marcadores)
        assert res.status_code == 200, res.text
        ids = {fila["public_id"] for fila in res.json()}
        assert alfa.cliente in ids, "el buscador de alfa vino sin su cliente"
        assert not ids & beta.marcadores, "trae clientes de beta"
        personal = {
            alfa.admin_id,
            alfa.profesional_id,
            alfa.recepcionista_id,
            actor.user_id,
        }
        assert not ids & personal, "trae cuentas del personal"
