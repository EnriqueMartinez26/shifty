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


def _depends(service: dict[str, object]) -> dict[str, str]:
    """Normaliza `depends_on` a {servicio: condicion} ('' en la forma corta)."""
    dep = service.get("depends_on") or {}
    if isinstance(dep, dict):
        return {
            str(name): str((cfg or {}).get("condition", ""))
            if isinstance(cfg, dict)
            else ""
            for name, cfg in dep.items()
        }
    assert isinstance(dep, list)
    return {str(name): "" for name in dep}


def test_los_procesos_esperan_a_que_sus_dependencias_esten_sanas() -> None:
    """Defecto real (2026-09-17, C-10): `depends_on` en forma corta.

    Sintoma: la forma corta solo ordena el arranque. Con `restart: always`,
    el primer `up` en frio dejaba a backend/celery_worker/celery_beat
    reiniciandose contra una base que todavia no escuchaba. El Postgres de
    CI si tiene `--health-cmd` (quality.yml), asi que el stack local era el
    unico sin la guarda.
    """
    services = _services()
    infra = ("db", "redis", "rabbitmq")

    for nombre in infra:
        assert services[nombre].get("healthcheck"), (
            f"{nombre} no declara healthcheck: nadie puede esperar a que este listo"
        )

    for nombre in ("backend", "celery_worker", "celery_beat"):
        deps = _depends(services[nombre])
        for dependencia in infra:
            assert deps.get(dependencia) == "service_healthy", (
                f"{nombre} arranca contra {dependencia} sin esperar su healthcheck: "
                f"{deps.get(dependencia)!r}"
            )
