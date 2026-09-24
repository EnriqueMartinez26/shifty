"""Matriz de roles: cada ruta contra cada rol, con un request valido.

Para cada fila de ``TABLA`` y cada rol (``anon``, ``client-otp``,
``professional``, ``receptionist``, ``store_admin``, ``super_admin``):

- permitido: la ruta responde uno de sus codigos ``ok`` (2xx salvo que la
  fila diga otra cosa). Asi se prueba ademas que la fabrica arma un request
  que de verdad pasa, y que el rechazo de los otros roles no es casual.
- no permitido: 401 si la ruta exige sesion y el actor no tiene token, 403 en
  cualquier otro caso. Nunca 404 (esconderia que la ruta existe detras de un
  error de datos) ni 5xx.

Segunda pasada: la tienda del admin SUSPENDIDA. Las lecturas siguen, las
escrituras de ``SUSPENSION_ALLOWED_WRITES`` siguen, el resto responde 402;
en el portal publico solo desaparecen la vitrina, la reserva y el alta en la
lista de espera (404, como una tienda inexistente).

En SQLite no hay RLS: esto prueba la capa de aplicacion sola (CLAUDE.md §2).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _pytest.mark.structures import ParameterSet

from modules.billing.dependencies import (
    SAFE_METHODS,
    SUSPENSION_ALLOWED_WRITES,
    block_writes_when_suspended,
)
from tests.security.mundo import ADMIN_TIENDA, ANON, ROLES, Mundo
from tests.security.rutas import (
    DEFECTOS_MATRIZ,
    TABLA,
    Alcance,
    Ruta,
    depende_de,
    requiere_token,
    ruta_de_la_app,
)
from tests.security.verificacion import (
    exigir,
    pagos_sin_red,
    revisar_respuesta,
    xfail_de,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Portal publico de una tienda suspendida: mismo 404 que una inexistente.
PUBLICAS_QUE_DESAPARECEN = {
    ("GET", "/public/stores/{slug}"),
    ("POST", "/public/appointments"),
    ("POST", "/public/waitlist"),
}


@pytest.fixture(scope="module", autouse=True)
def _pagos() -> Iterator[None]:
    with pagos_sin_red():
        yield


def _casos() -> Iterator[ParameterSet]:
    for ruta in TABLA:
        for rol in ROLES:
            motivo = DEFECTOS_MATRIZ.get((ruta.method, ruta.path, rol))
            yield pytest.param(ruta, rol, id=f"{ruta} [{rol}]", marks=xfail_de(motivo))


@pytest.mark.parametrize(("ruta", "rol"), list(_casos()))
async def test_cada_rol_recibe_lo_que_dice_la_tabla(
    mundo: Mundo, ruta: Ruta, rol: str
) -> None:
    actor = await mundo.actor(rol, mundo.alfa)
    llamada = await ruta.fabrica(mundo, actor, mundo.alfa)
    res = await mundo.llamar(actor, llamada)

    # El soporte global ve todas las tiendas por diseno; cualquier otro caso
    # que devuelva datos de beta a un actor de alfa es una fuga.
    soporte = ruta.alcance is Alcance.SUPERADMIN and rol in ruta.permitidos
    revisar_respuesta(res, llamada, set() if soporte else mundo.beta.marcadores)
    if rol in ruta.permitidos:
        exigir(
            res.status_code in ruta.ok,
            f"{ruta} con {rol} deberia pasar ({sorted(ruta.ok)}) y respondio "
            f"{res.status_code}: {res.text[:400]}",
        )
        return
    sin_sesion = actor.token is None and requiere_token(ruta_de_la_app(ruta.clave))
    esperado = 401 if sin_sesion else 403
    exigir(
        res.status_code == esperado,
        f"{ruta} con {rol} deberia rechazarse con {esperado} y respondio "
        f"{res.status_code}: {res.text[:400]}",
    )


def _casos_de_suspension() -> Iterator[ParameterSet]:
    for ruta in TABLA:
        route = ruta_de_la_app(ruta.clave)
        if ADMIN_TIENDA in ruta.permitidos and depende_de(
            route, block_writes_when_suspended
        ):
            yield pytest.param(ruta, id=str(ruta))


@pytest.mark.parametrize("ruta", list(_casos_de_suspension()))
async def test_tienda_suspendida_solo_escribe_lo_permitido(
    mundo: Mundo, ruta: Ruta
) -> None:
    actor = await mundo.actor(ADMIN_TIENDA, mundo.alfa)
    # La preparacion corre con la tienda activa: el admin del mundo tambien
    # queda bloqueado mientras dura la suspension.
    llamada = await ruta.fabrica(mundo, actor, mundo.alfa)
    await mundo.suspender(mundo.alfa, True)
    try:
        res = await mundo.llamar(actor, llamada)
    finally:
        await mundo.suspender(mundo.alfa, False)

    revisar_respuesta(res, llamada, mundo.beta.marcadores)
    if ruta.method in SAFE_METHODS or ruta.clave in SUSPENSION_ALLOWED_WRITES:
        assert res.status_code in ruta.ok, (
            f"{ruta} deberia seguir andando con la tienda suspendida y respondio "
            f"{res.status_code}: {res.text[:400]}"
        )
    else:
        assert res.status_code == 402, (
            f"{ruta} escribio con la tienda suspendida: {res.status_code} "
            f"{res.text[:400]}"
        )


def _casos_publicos() -> Iterator[ParameterSet]:
    for ruta in TABLA:
        if ruta.path.startswith("/public/") and ANON in ruta.permitidos:
            yield pytest.param(ruta, id=str(ruta))


@pytest.mark.parametrize("ruta", list(_casos_publicos()))
async def test_portal_de_una_tienda_suspendida(mundo: Mundo, ruta: Ruta) -> None:
    actor = await mundo.actor(ANON, mundo.alfa)
    llamada = await ruta.fabrica(mundo, actor, mundo.alfa)
    await mundo.suspender(mundo.alfa, True)
    try:
        res = await mundo.llamar(actor, llamada)
    finally:
        await mundo.suspender(mundo.alfa, False)

    revisar_respuesta(res, llamada, mundo.beta.marcadores)
    if ruta.clave in PUBLICAS_QUE_DESAPARECEN:
        assert res.status_code == 404, (
            f"{ruta} con la tienda suspendida respondio {res.status_code}: "
            f"{res.text[:400]}"
        )
    else:
        assert res.status_code in ruta.ok, (
            f"{ruta} con la tienda suspendida respondio {res.status_code}: "
            f"{res.text[:400]}"
        )
    assert ruta.alcance in (Alcance.PUBLICA, Alcance.PUBLICA_TIENDA)
