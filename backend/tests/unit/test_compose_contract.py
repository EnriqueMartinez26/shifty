"""Contrato del docker-compose: Celery recibe el mismo entorno que la API.

Regresion real: los servicios celery_worker/celery_beat solo recibian las
URLs de base/broker. Settings() fallaba por SECRET_KEY y SMTP_* faltantes,
caia al respaldo (DATABASE_URL invalida, Redis en localhost) y beat no podia
encolar ninguna tarea. Ningun job corria, y en silencio: el worker se
declaraba "ready".
"""

from pathlib import Path

import yaml

from core.config import Settings

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _services() -> dict[str, dict[str, object]]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return dict(data["services"])


def _env_keys(service: dict[str, object]) -> set[str]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(key) for key in env}
    assert isinstance(env, list)
    return {str(item).split("=", 1)[0] for item in env}


def test_celery_recibe_el_mismo_entorno_que_la_api() -> None:
    services = _services()
    api = _env_keys(services["backend"])
    assert api, "el backend debe declarar environment en compose"
    for name in ("celery_worker", "celery_beat"):
        faltan = api - _env_keys(services[name])
        assert not faltan, f"{name} no recibe: {sorted(faltan)}"


def test_el_entorno_de_compose_cubre_lo_obligatorio_de_settings() -> None:
    obligatorios = {
        name for name, field in Settings.model_fields.items() if field.is_required()
    }
    declarados = _env_keys(_services()["backend"])
    faltan = obligatorios - declarados
    assert not faltan, f"Settings exige variables que compose no declara: {faltan}"
