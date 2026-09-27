"""Seed de capacidad: solo staging, sin contrasenas en el repo ni en logs.

2026-09-24 (plan §9, plan-capacidad §5.3). ``scripts/seed_capacidad.py``
siembra 200 tiendas ``cap-NNN`` con 90 dias de historial para la prueba de
aceptacion. Crea cuentas de dueno con una contrasena conocida por quien corre
la prueba: en produccion eso es una puerta abierta, asi que el script falla
cerrado (regla 17) con DOS capas y sin contrasena por defecto:

- el destino: ``--expect-database`` y ``--expect-host`` tienen que coincidir
  con lo que dice ``DATABASE_URL`` y el nombre de la base tiene que contener
  ``staging`` (o nombrarse con ``--allow-database-name``, que queda en el
  log). ``ENV`` no alcanza: el operador lo pisa con ``-e ENV=staging`` y el
  compose de produccion, que staging tambien usa, fija ``ENV: production``;
  el mismo comando en el clon equivocado sembraba produccion (revision de
  perf/f5, 2026-09-24).
- ``ENV``: produccion se rechaza aunque la base coincida.

El plan de turnos se genera sin superposicion por profesional (la exclusion
GiST abortaria la transaccion de la tienda entera) y en estados que el
trigger acepta: pasado terminado, futuro pendiente o confirmado.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "seed_capacidad.py"
CLAVE = "clave-de-prueba-larga"
URL_STAGING = (
    "postgresql+asyncpg://shifty_app:clave-app@db:5432/shifty_staging?ssl=disable"
)
URL_PROD = "postgresql+asyncpg://shifty_app:clave-app@db:5432/shifty_db?ssl=disable"
DESTINO_OK = ["--expect-database", "shifty_staging", "--expect-host", "db"]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_capacidad", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize("env", ["production", "PRODUCTION", " production "])
def test_se_niega_en_produccion(env: str) -> None:
    with pytest.raises(SystemExit) as salida:
        _modulo().verificar_entorno({"ENV": env, "SEED_OWNER_PASSWORD": CLAVE})

    assert "produccion" in str(salida.value)


@pytest.mark.parametrize("env", ["", "prod", "test"])
def test_exige_un_entorno_explicito_de_staging_o_desarrollo(env: str) -> None:
    with pytest.raises(SystemExit):
        _modulo().verificar_entorno({"ENV": env, "SEED_OWNER_PASSWORD": CLAVE})


@pytest.mark.parametrize("clave", ["", "corta"])
def test_exige_la_contrasena_de_los_duenos_por_entorno(clave: str) -> None:
    with pytest.raises(SystemExit) as salida:
        _modulo().verificar_entorno({"ENV": "staging", "SEED_OWNER_PASSWORD": clave})

    assert "SEED_OWNER_PASSWORD" in str(salida.value)
    if clave:
        assert clave not in str(salida.value)


def test_en_staging_con_contrasena_devuelve_la_clave() -> None:
    entorno = {"ENV": "staging", "SEED_OWNER_PASSWORD": CLAVE}

    assert _modulo().verificar_entorno(entorno) == CLAVE


def test_main_en_produccion_no_toca_la_base_aunque_la_base_coincida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modulo = _modulo()
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", URL_STAGING)
    monkeypatch.setenv("SEED_OWNER_PASSWORD", CLAVE)
    monkeypatch.setattr(
        modulo,
        "create_async_engine",
        lambda *_a, **_kw: pytest.fail("no debe conectar"),
    )

    with pytest.raises(SystemExit) as salida:
        modulo.main(["--stores", "1", *DESTINO_OK])

    assert "produccion" in str(salida.value)


def test_los_slugs_llevan_el_prefijo_de_la_prueba() -> None:
    modulo = _modulo()

    assert modulo.slug_de(7) == "cap-007"
    assert modulo.slug_de(200) == "cap-200"


def test_el_plan_de_turnos_no_superpone_a_ningun_profesional() -> None:
    modulo = _modulo()
    hoy = date(2026, 9, 24)

    plan = modulo.planear_turnos(
        random.Random(3),
        hoy=hoy,
        profesionales=3,
        duraciones=[30, 45, 60],
        clientes=30,
        dias_historial=90,
        por_dia=6,
        dias_futuros=14,
        ocupacion=0.4,
    )

    ocupados = Counter((t.profesional, t.dia, t.hora) for t in plan)
    assert max(ocupados.values()) == 1, "dos turnos del mismo profesional a la vez"
    assert all(t.dia.weekday() != 6 for t in plan), "los domingos no abre"
    assert all(9 <= t.hora <= 18 and t.minutos <= 60 for t in plan)

    pasados = [t for t in plan if t.dia < hoy]
    futuros = [t for t in plan if t.dia > hoy]
    assert {t.estado for t in pasados} <= {"completed", "cancelled", "absent"}
    assert {t.estado for t in futuros} <= {"pending", "confirmed"}
    assert min(t.dia for t in pasados) >= hoy - timedelta(days=90)
    dias_habiles_pasados = sum(
        1 for d in range(1, 91) if (hoy - timedelta(days=d)).weekday() != 6
    )
    assert len(pasados) == dias_habiles_pasados * 6
    # 40 % de 10 horas por profesional y dia habil.
    dias_habiles_futuros = sum(
        1 for d in range(1, 15) if (hoy + timedelta(days=d)).weekday() != 6
    )
    assert len(futuros) == dias_habiles_futuros * 3 * 4


def test_la_base_esperada_de_staging_pasa() -> None:
    _modulo().verificar_destino(
        URL_STAGING, base="shifty_staging", host="db", permitir=None
    )


@pytest.mark.parametrize(
    ("base", "host"),
    [("otra_staging", "db"), ("shifty_staging", "db-prod")],
    ids=["otra-base", "otro-host"],
)
def test_un_destino_distinto_del_esperado_se_rechaza(base: str, host: str) -> None:
    with pytest.raises(SystemExit) as salida:
        _modulo().verificar_destino(URL_STAGING, base=base, host=host, permitir=None)

    assert "no coincide" in str(salida.value)
    assert "clave-app" not in str(salida.value)


def test_una_base_con_nombre_de_produccion_se_rechaza() -> None:
    """``shifty_db`` es el nombre por defecto del compose: el de produccion."""
    with pytest.raises(SystemExit) as salida:
        _modulo().verificar_destino(
            URL_PROD, base="shifty_db", host="db", permitir=None
        )

    assert "staging" in str(salida.value)
    assert "--allow-database-name" in str(salida.value)


def test_la_excepcion_explicita_por_nombre_pasa_y_queda_en_el_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _modulo().verificar_destino(
        URL_PROD, base="shifty_db", host="db", permitir="shifty_db"
    )

    assert "--allow-database-name shifty_db" in capsys.readouterr().out


def test_la_excepcion_tiene_que_nombrar_la_misma_base() -> None:
    with pytest.raises(SystemExit):
        _modulo().verificar_destino(
            URL_PROD, base="shifty_db", host="db", permitir="shifty_test"
        )


def test_main_exige_la_base_esperada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setenv("SEED_OWNER_PASSWORD", CLAVE)
    monkeypatch.setenv("DATABASE_URL", URL_STAGING)

    with pytest.raises(SystemExit):
        _modulo().main(["--stores", "1"])


def test_main_con_la_base_equivocada_no_toca_la_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modulo = _modulo()
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setenv("SEED_OWNER_PASSWORD", CLAVE)
    monkeypatch.setenv("DATABASE_URL", URL_PROD)
    monkeypatch.setattr(
        modulo,
        "create_async_engine",
        lambda *_a, **_kw: pytest.fail("no debe conectar"),
    )

    with pytest.raises(SystemExit):
        modulo.main(["--stores", "1", *DESTINO_OK])


def test_main_normaliza_el_dominio_a_minusculas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La base exige emails en minusculas (``ck_users_email_lower``)."""
    modulo = _modulo()
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setenv("SEED_OWNER_PASSWORD", CLAVE)
    monkeypatch.setenv("DATABASE_URL", URL_STAGING)
    recibidas: list[object] = []

    async def sembrar_falso(_url: str, opciones: object, _clave: str) -> int:
        recibidas.append(opciones)
        return 0

    monkeypatch.setattr(modulo, "sembrar", sembrar_falso)

    assert modulo.main([*DESTINO_OK, "--domain", " Capacidad.Example.COM "]) == 0
    assert getattr(recibidas[0], "dominio") == "capacidad.example.com"


def test_los_clientes_no_comparten_la_clave_del_dueno() -> None:
    """Un cliente sembrado nunca inicia sesion: hash inutilizable, como la app."""
    dueno, clientes = _modulo()._personas(
        store_id="01J9ZX", indice=1, owner_email="o@x.com", hash_dueno="HASH-DUENO"
    )

    assert dueno.hashed_password == "HASH-DUENO"
    assert {c.hashed_password for c in clientes} != {"HASH-DUENO"}
    assert all(c.hashed_password != "HASH-DUENO" for c in clientes)
