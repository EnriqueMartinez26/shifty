"""Inventario: cada ruta de la app tiene su fila en la tabla de seguridad.

La tabla (``tests/security/rutas.py``) dice quien puede llamar cada ruta y
como se acota a la tienda. Si aparece un endpoint nuevo sin fila, este test
falla con la ruta en el mensaje: la matriz de roles y la pasada entre tiendas
no pueden probar lo que no conocen, y un endpoint sin probar es un endpoint
que nadie decidio quien puede usar.
"""

from __future__ import annotations

from modules.auth.dependencies import get_current_global_admin
from modules.billing.dependencies import block_writes_when_suspended
from tests.security.mundo import ANON, CLIENTE_OTP, ROLES, SUPERADMIN
from tests.security.rutas import (
    POR_CLAVE,
    TABLA,
    Alcance,
    claves_de,
    cotas_numericas,
    depende_de,
    requiere_token,
    ruta_de_la_app,
    rutas_de_la_app,
)

# Prefijos que NO son del panel de una tienda: no llevan la guarda de
# suscripcion suspendida por diseno (CLAUDE.md, "Una tienda suspendida no
# escribe": exentos auth, ops, superadmin y el portal publico).
PREFIJOS_SIN_GUARDA_DE_SUSPENSION = ("/auth/", "/ops/", "/superadmin/", "/public/")
RUTAS_SIN_GUARDA_DE_SUSPENSION = {("GET", "/"), ("GET", "/me")}


def test_cada_ruta_de_la_app_tiene_su_fila() -> None:
    faltantes = [
        f"  {method} {path}"
        for route in rutas_de_la_app()
        for method, path in claves_de(route)
        if (method, path) not in POR_CLAVE
    ]
    assert not faltantes, (
        "Rutas sin fila en tests/security/rutas.py::TABLA. Agrega la fila con "
        "los roles permitidos (verificados en el router y el handler), el "
        "alcance por tienda y una fabrica de request minimo:\n" + "\n".join(faltantes)
    )


def test_ninguna_fila_describe_una_ruta_que_ya_no_existe() -> None:
    existentes = {clave for route in rutas_de_la_app() for clave in claves_de(route)}
    sobrantes = [f"  {ruta}" for ruta in TABLA if ruta.clave not in existentes]
    assert not sobrantes, (
        "Filas de TABLA sin ruta en la app (se borro o cambio el path): "
        "borralas o corregilas:\n" + "\n".join(sobrantes)
    )
    assert len(POR_CLAVE) == len(TABLA), "hay filas duplicadas en TABLA"


def test_los_roles_de_la_tabla_existen() -> None:
    desconocidos = [
        f"  {ruta}: {sorted(ruta.permitidos - set(ROLES))}"
        for ruta in TABLA
        if not ruta.permitidos <= set(ROLES) or not ruta.permitidos
    ]
    assert not desconocidos, "roles invalidos o vacios:\n" + "\n".join(desconocidos)


def test_una_ruta_con_sesion_no_admite_al_anonimo() -> None:
    """La tabla no puede contradecir a las dependencias del router."""
    contradicciones = [
        f"  {ruta}"
        for ruta in TABLA
        if requiere_token(ruta_de_la_app(ruta.clave))
        and ruta.permitidos & {ANON, CLIENTE_OTP}
    ]
    assert not contradicciones, (
        "rutas que exigen get_current_user pero la tabla deja pasar a un rol "
        "sin sesion:\n" + "\n".join(contradicciones)
    )


def test_el_soporte_global_es_solo_del_superadmin() -> None:
    errores = []
    for ruta in TABLA:
        global_ = depende_de(ruta_de_la_app(ruta.clave), get_current_global_admin)
        if global_ and ruta.permitidos != {SUPERADMIN}:
            errores.append(f"  {ruta}: exige is_global_admin y la tabla dice otra cosa")
        if global_ != (ruta.alcance == Alcance.SUPERADMIN) and ruta.path.startswith(
            "/superadmin/"
        ):
            errores.append(
                f"  {ruta}: ruta de /superadmin sin get_current_global_admin"
            )
    assert not errores, "\n".join(errores)


def test_todo_router_del_panel_lleva_la_guarda_de_suspension() -> None:
    """Un endpoint nuevo del panel nace bloqueado para una tienda suspendida
    solo si su router lleva ``block_writes_when_suspended`` (CLAUDE.md)."""
    sin_guarda = [
        f"  {method} {path}"
        for route in rutas_de_la_app()
        for method, path in claves_de(route)
        if not path.startswith(PREFIJOS_SIN_GUARDA_DE_SUSPENSION)
        and (method, path) not in RUTAS_SIN_GUARDA_DE_SUSPENSION
        and not depende_de(route, block_writes_when_suspended)
    ]
    assert not sin_guarda, (
        "rutas del panel sin block_writes_when_suspended:\n" + "\n".join(sin_guarda)
    )


def test_todo_parametro_numerico_tiene_ge_y_le() -> None:
    """Regla 9: un solo lado deja un 500 alcanzable (desborde con offset)."""
    incompletos = [
        f"  {method} {path} ?{nombre} (ge={minimo}, le={maximo})"
        for method, path, nombre, minimo, maximo in cotas_numericas()
        if minimo is None or maximo is None
    ]
    assert cotas_numericas(), "no se encontro ningun parametro numerico"
    assert not incompletos, "parametros numericos sin las dos cotas:\n" + "\n".join(
        incompletos
    )
