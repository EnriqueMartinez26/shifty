"""Seed de capacidad: solo staging, sin contrasenas en el repo ni en logs.

2026-09-24 (plan §9, plan-capacidad §5.3). ``scripts/seed_capacidad.py``
siembra 200 tiendas ``cap-NNN`` con 90 dias de historial para la prueba de
aceptacion. Crea cuentas de dueno con una contrasena conocida por quien corre
la prueba: en produccion eso es una puerta abierta, asi que el script se niega
(regla 17: falla cerrado) si ``ENV`` o la configuracion cargada dicen
produccion, y no tiene contrasena por defecto.

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

from core.config import Environment, settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "seed_capacidad.py"
CLAVE = "clave-de-prueba-larga"


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


def test_se_niega_si_la_configuracion_cargada_es_de_produccion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aunque la variable diga otra cosa: gana lo que la app cree que es."""
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    with pytest.raises(SystemExit):
        _modulo().verificar_entorno({"ENV": "staging", "SEED_OWNER_PASSWORD": CLAVE})


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


def test_main_en_produccion_no_toca_la_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modulo = _modulo()
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SEED_OWNER_PASSWORD", CLAVE)
    monkeypatch.setattr(
        modulo,
        "create_async_engine",
        lambda *_a, **_kw: pytest.fail("no debe conectar"),
    )

    with pytest.raises(SystemExit):
        modulo.main(["--stores", "1"])


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
