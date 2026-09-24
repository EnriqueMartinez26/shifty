"""Escenario de la prueba de aceptacion: mezcla, forma de carga y conteos.

2026-09-24 (plan §9). Lo que se puede fijar sin generar carga: la mezcla de
150 clientes + 45 duenos + 5 superadmin, la rampa de 5 minutos con 20 de
meseta, el manifiesto que deja el seed y el conteo de codigos que usa
``scripts/perf_acceptance_check.py``. Se carga el modulo puro, nunca el
locustfile: importar ``locust`` parchea el proceso con gevent.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULO = BACKEND_ROOT / "loadtests" / "aceptacion.py"
LOCUSTFILE = BACKEND_ROOT / "loadtests" / "locust_aceptacion.py"


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aceptacion", MODULO)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_la_mezcla_es_la_del_plan() -> None:
    m = _modulo()
    assert (m.CLIENTES, m.DUENOS, m.SUPERADMINS) == (150, 45, 5)
    assert m.TOTAL_USUARIOS == 200
    assert (m.RAMPA_S, m.MESETA_S) == (300, 1200)
    assert (m.RAFAGA_CADA_S, m.RAFAGA_TAMANO) == (300, 10)


def test_la_forma_sube_en_cinco_minutos_y_corta_al_final_de_la_meseta() -> None:
    m = _modulo()

    usuarios, ritmo = m.forma_de_carga(0)
    assert usuarios == 200
    assert ritmo * 300 == pytest.approx(200), "200 usuarios en 300 s"
    assert m.forma_de_carga(1499) == (200, pytest.approx(200 / 300))
    assert m.forma_de_carga(1500) is None


def test_el_locustfile_usa_la_mezcla_y_no_importa_locust_en_el_modulo_puro() -> None:
    texto = LOCUSTFILE.read_text(encoding="utf-8")
    for peso in ("weight = CLIENTES", "weight = DUENOS", "weight = SUPERADMINS"):
        assert peso in texto
    assert "LoadTestShape" in texto
    assert "reset_all()" in texto, "el p95 se juzga en la meseta, no en la rampa"
    assert "import locust" not in MODULO.read_text(encoding="utf-8")
    assert "from locust" not in MODULO.read_text(encoding="utf-8")


def test_el_manifiesto_trae_tiendas_sin_contrasenas(tmp_path: Path) -> None:
    manifiesto = tmp_path / "manifiesto.json"
    manifiesto.write_text(
        json.dumps(
            {
                "stores": [
                    {
                        "slug": "cap-001",
                        "store_public_id": "S1",
                        "owner_email": "owner-001@capacidad.example.com",
                        "service_ids": ["SV1", "SV2"],
                        "staff_ids": ["ST1"],
                    },
                    {
                        "slug": "cap-002",
                        "store_public_id": "S2",
                        "owner_email": "owner-002@capacidad.example.com",
                        "service_ids": [],
                        "staff_ids": ["ST2"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    tiendas = _modulo().cargar_manifiesto(manifiesto)

    assert [t.slug for t in tiendas] == ["cap-001"], "sin servicios no se reserva"
    assert tiendas[0].service_ids == ("SV1", "SV2")


def test_un_manifiesto_vacio_se_rechaza(tmp_path: Path) -> None:
    manifiesto = tmp_path / "vacio.json"
    manifiesto.write_text('{"stores": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="manifiesto"):
        _modulo().cargar_manifiesto(manifiesto)


def test_las_fechas_son_distintas_y_dentro_de_los_14_dias() -> None:
    fechas = _modulo().fechas_de_consulta(
        date(2026, 9, 24), random.Random(1), cantidad=4
    )

    assert len(set(fechas)) == 4
    assert all("2026-09-25" <= f <= "2026-10-08" for f in fechas)


def test_solo_se_reserva_un_slot_disponible() -> None:
    m = _modulo()
    slots = [
        {"starts_at": "a", "status": "booked"},
        {"starts_at": "b", "status": "available"},
        {"starts_at": "c", "status": "blocked"},
    ]

    assert m.slot_libre(slots, random.Random(0))["starts_at"] == "b"
    assert m.slot_libre(slots[:1], random.Random(0)) is None


def test_el_conteo_separa_rutas_conexiones_y_rafagas() -> None:
    conteo = _modulo().ConteoDeCodigos()
    conteo.registrar("GET", "/public/services", 200)
    conteo.registrar("GET", "/public/services", 200)
    conteo.registrar("POST", "/public/appointments", 409)
    conteo.registrar("GET", "/public/staff", 0)
    conteo.registrar_rafaga([201, 409, 409, None])

    assert conteo.como_dict() == {
        "por_ruta": {
            "GET /public/services": {"200": 2},
            "POST /public/appointments": {"409": 1},
        },
        "errores_de_conexion": 1,
        "rafagas": [{"201": 1, "409": 2, "0": 1}],
    }


def test_se_desenvuelve_la_respuesta_canonica_de_la_api() -> None:
    """Fuera de los tests la API responde ``{"success": ..., "data": ...}``.

    El ensayo del 2026-09-24 lo mostro: sin desenvolver, el token del login
    no aparecia (todo el panel en 401) y la disponibilidad no traia slots.
    """
    m = _modulo()

    assert m.datos_de({"success": True, "data": {"access_token": "t"}}) == {
        "access_token": "t"
    }
    assert m.datos_de({"success": True, "data": [{"status": "available"}]}) == [
        {"status": "available"}
    ]
    assert m.datos_de([1, 2]) == [1, 2], "una respuesta cruda pasa igual"
    assert m.datos_de({"access_token": "t"}) == {"access_token": "t"}


def test_el_manifiesto_se_arma_desde_la_api_publica_de_staging() -> None:
    """CI no tiene el archivo del seed: lo reconstruye por slug ``cap-NNN``."""
    m = _modulo()
    pedidos: list[str] = []
    respuestas = {
        "/public/stores/cap-001": {"success": True, "data": {"public_id": "S1"}},
        "/public/services?store_public_id=S1": {
            "success": True,
            "data": [{"public_id": "SV1"}, {"public_id": "SV2"}],
        },
        "/public/staff?store_public_id=S1": {
            "success": True,
            "data": [{"public_id": "ST1"}],
        },
        # cap-002 no existe (404): se saltea.
    }

    def obtener(ruta: str) -> object:
        pedidos.append(ruta)
        return respuestas.get(ruta)

    manifiesto = m.manifiesto_desde_api(
        obtener, tiendas=2, dominio="capacidad.example.com"
    )

    assert manifiesto["stores"] == [
        {
            "slug": "cap-001",
            "store_public_id": "S1",
            "owner_email": "owner-001@capacidad.example.com",
            "service_ids": ["SV1", "SV2"],
            "staff_ids": ["ST1"],
        }
    ]
    assert "/public/stores/cap-002" in pedidos
    assert not any("cap-002" in p and "services" in p for p in pedidos)
