"""Contrato del docker-compose: Celery recibe el mismo entorno que la API.

Regresion real: los servicios celery_worker/celery_beat solo recibian las
URLs de base/broker. Settings() fallaba por SECRET_KEY y SMTP_* faltantes,
caia al respaldo (DATABASE_URL invalida, Redis en localhost) y beat no podia
encolar ninguna tarea. Ningun job corria, y en silencio: el worker se
declaraba "ready".
"""

from pathlib import Path

import pytest
import yaml

from core.config import Settings

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _services() -> dict[str, dict[str, object]]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return dict(data["services"])


def _env_items(service: dict[str, object]) -> dict[str, str]:
    """`environment` normalizado a {clave: valor}, en cualquiera de sus formas."""
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(key): str(value) for key, value in env.items()}
    assert isinstance(env, list)
    pares = [str(item).split("=", 1) for item in env]
    return {par[0]: par[1] if len(par) > 1 else "" for par in pares}


def _env_keys(service: dict[str, object]) -> set[str]:
    return set(_env_items(service))


def _nodo_hijo(nodo: yaml.nodes.Node, clave: str) -> yaml.nodes.Node:
    assert isinstance(nodo, yaml.nodes.MappingNode), f"{clave}: el padre no es un mapa"
    for k, v in nodo.value:
        if str(k.value) == clave:
            return v
    raise AssertionError(f"el YAML no declara {clave!r}")


def _nodos_de_environment(
    texto: str, servicios: tuple[str, ...]
) -> dict[str, yaml.nodes.Node]:
    """Nodos SIN resolver del `environment` de cada servicio.

    PyYAML devuelve el MISMO objeto nodo para cada alias de un ancla, asi que
    comparar por identidad responde la pregunta que importa: los tres servicios
    apuntan al mismo bloque, o alguien copio uno.
    """
    raiz = yaml.compose(texto)
    assert raiz is not None, "el compose esta vacio"
    services = _nodo_hijo(raiz, "services")
    return {
        nombre: _nodo_hijo(_nodo_hijo(services, nombre), "environment")
        for nombre in servicios
    }


def verificar_paridad_de_entorno(texto: str, servicios: tuple[str, ...]) -> None:
    """Regla 22: un solo bloque de entorno para API, worker y beat.

    AUD2-B7-07 (2026-09-20): esto comparaba los CONJUNTOS DE NOMBRES de las
    variables. Como los tres servicios usan el mismo ancla, las claves son
    identicas por construccion y el test no podia fallar: alguien que
    reemplazara el alias de `celery_worker` por un bloque copiado con los mismos
    nombres y un `DATABASE_URL` distinto pasaba igual, y reproducia exactamente
    la regresion que el docstring de este archivo dice cubrir. Ahora se comparan
    los VALORES y, ademas, se exige que los tres apunten al MISMO ancla.
    """
    data = yaml.safe_load(texto)
    services = dict(data["services"])
    api = _env_items(services[servicios[0]])
    assert api, f"{servicios[0]} debe declarar environment en compose"
    for nombre in servicios[1:]:
        suyo = _env_items(services[nombre])
        distintas = {
            clave: (valor, suyo.get(clave))
            for clave, valor in api.items()
            if suyo.get(clave) != valor
        }
        assert not distintas, f"{nombre} no recibe lo mismo que la API: {distintas}"
        de_mas = set(suyo) - set(api)
        assert not de_mas, f"{nombre} recibe variables que la API no: {sorted(de_mas)}"

    nodos = _nodos_de_environment(texto, servicios)
    for nombre in servicios[1:]:
        assert nodos[nombre] is nodos[servicios[0]], (
            f"{nombre} no usa el mismo ancla que {servicios[0]}: es un bloque "
            "aparte que hoy coincide y manana no"
        )


def test_celery_recibe_el_mismo_entorno_que_la_api() -> None:
    verificar_paridad_de_entorno(
        COMPOSE.read_text(encoding="utf-8"),
        ("backend", "celery_worker", "celery_beat"),
    )


_COMPOSE_CON_BLOQUE_COPIADO = """
x-app-environment: &app_environment
  ENV: development
  DATABASE_URL: postgresql+asyncpg://app@db:5432/shifty
services:
  backend:
    environment: *app_environment
  celery_worker:
    environment:
      ENV: development
      DATABASE_URL: postgresql+asyncpg://app@otra-base:5432/shifty
  celery_beat:
    environment: *app_environment
"""


def test_un_bloque_copiado_con_otro_valor_no_pasa_el_contrato() -> None:
    """La regresion de 2026-09-08 con las MISMAS claves y otra base.

    Es el caso que el contrato viejo no podia ver. Sin este contraejemplo el
    test de arriba es decorativo: contra el compose real no puede fallar nunca.
    """
    with pytest.raises(AssertionError, match="celery_worker"):
        verificar_paridad_de_entorno(
            _COMPOSE_CON_BLOQUE_COPIADO,
            ("backend", "celery_worker", "celery_beat"),
        )


_COMPOSE_CON_ANCLA_DUPLICADA = """
x-app-environment: &app_environment
  ENV: development
services:
  backend:
    environment: *app_environment
  celery_worker:
    environment:
      ENV: development
  celery_beat:
    environment: *app_environment
"""


def test_un_bloque_copiado_identico_tampoco_pasa() -> None:
    """Hoy coincide; manana alguien edita uno solo y nadie se entera."""
    with pytest.raises(AssertionError, match="ancla"):
        verificar_paridad_de_entorno(
            _COMPOSE_CON_ANCLA_DUPLICADA,
            ("backend", "celery_worker", "celery_beat"),
        )


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


# --- Override de produccion (AUD2-C-01, 2026-09-19) ---------------------------
#
# Sintoma: docker-compose.prod.yml no declaraba environment ni env_file, asi que
# los tres procesos heredaban el ancla de DESARROLLO. Dos consecuencias: las
# claves que el ancla lista llegaban con su default de desarrollo de forma
# explicita (COOKIE_SECURE=false, EXPOSE_API_DOCS=true, OTP_PROVIDER=console,
# OTP_DEBUG_EXPOSE_CODE=true), lo que anula apply_production_defaults porque usa
# setdefault; y las que el ancla NO lista se ignoraban aunque estuvieran en el
# .env, incluida DATABASE_URL, que el ancla construye contra el `db` del
# compose. Un operador que siga .env.production.example arrancaba contra el
# Postgres del contenedor en vez de su base administrada, sin ningun error.

COMPOSE_PROD = Path(__file__).resolve().parents[3] / "docker-compose.prod.yml"

SERVICIOS_DE_LA_APP = ("backend", "celery_worker", "celery_beat")

# Sin estas no se arranca: tienen que venir del entorno con `:?`, nunca con un
# valor por default.
CRITICAS_EN_PRODUCCION = (
    "SECRET_KEY",
    "FIELD_ENCRYPTION_KEY",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "APP_DB_PASSWORD",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND_URL",
    "CORS_ORIGINS",
)

# Valor de desarrollo que no puede aparecer como default en produccion.
DEFAULTS_DE_DESARROLLO_PROHIBIDOS = {
    "COOKIE_SECURE": "false",
    "EXPOSE_API_DOCS": "true",
    "OTP_PROVIDER": "console",
    "OTP_DEBUG_EXPOSE_CODE": "true",
}


def _servicios_prod() -> dict[str, dict[str, object]]:
    data = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))
    return dict(data["services"])


def _env_prod(servicio: str) -> dict[str, str]:
    env = _servicios_prod()[servicio].get("environment") or {}
    assert isinstance(env, dict), f"{servicio} declara environment como lista"
    return {str(k): str(v) for k, v in env.items()}


def test_produccion_no_hereda_el_entorno_de_desarrollo() -> None:
    del_ancla = _env_keys(_services()["backend"])
    for servicio in SERVICIOS_DE_LA_APP:
        faltan = del_ancla - set(_env_prod(servicio))
        assert not faltan, (
            f"{servicio} en produccion hereda del ancla de desarrollo: {sorted(faltan)}"
        )


def test_produccion_le_pasa_el_env_del_operador_a_los_tres_servicios() -> None:
    for servicio in SERVICIOS_DE_LA_APP:
        env_file = _servicios_prod()[servicio].get("env_file")
        assert env_file, f"{servicio} no declara env_file: el .env no llega entero"
        archivos = env_file if isinstance(env_file, list) else [env_file]
        assert ".env" in [str(a) for a in archivos], f"{servicio}: {archivos}"


def test_produccion_exige_las_criticas_y_no_inventa_defaults() -> None:
    for servicio in SERVICIOS_DE_LA_APP:
        env = _env_prod(servicio)
        for clave in CRITICAS_EN_PRODUCCION:
            valor = env.get(clave, "")
            assert f"${{{clave}:?" in valor, (
                f"{servicio}.{clave} no es obligatoria en produccion: {valor!r}"
            )


def test_produccion_no_repite_ningun_valor_de_desarrollo() -> None:
    for servicio in SERVICIOS_DE_LA_APP:
        env = _env_prod(servicio)
        for clave, prohibido in DEFAULTS_DE_DESARROLLO_PROHIBIDOS.items():
            valor = env.get(clave, "")
            assert f":-{prohibido}" not in valor and valor != prohibido, (
                f"{servicio}.{clave} usa el valor de desarrollo: {valor!r}"
            )
        # Los servicios del compose no pueden quedar cableados: en produccion
        # la base, Redis y el broker pueden ser administrados.
        for clave in ("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL"):
            valor = env.get(clave, "")
            for host in ("@db:", "//redis:", "@rabbitmq:"):
                assert host not in valor, (
                    f"{servicio}.{clave} apunta al contenedor del compose: {valor!r}"
                )


def test_los_tres_servicios_comparten_el_entorno_tambien_en_produccion() -> None:
    # Regla 22: la paridad vale para el override igual que para el base, y con
    # el mismo criterio (valores y ancla, no solo nombres; AUD2-B7-07).
    verificar_paridad_de_entorno(
        COMPOSE_PROD.read_text(encoding="utf-8"), SERVICIOS_DE_LA_APP
    )


def _prueba_del_healthcheck(servicio: str) -> str:
    healthcheck = _services()[servicio].get("healthcheck")
    assert isinstance(healthcheck, dict), f"{servicio} no declara healthcheck"
    return str(healthcheck["test"])


def test_los_procesos_de_celery_declaran_healthcheck() -> None:
    """AUD2-C-09 (2026-09-19): un worker vivo que no consume se veia sano.

    db, redis, rabbitmq y backend tenian healthcheck; los dos procesos de
    Celery, ninguno. Con restart: always, un worker que dejo de consumir o un
    beat que dejo de agendar se ven igual que uno sano en `docker compose ps`.
    Es el incidente de 2026-09-08 que este mismo archivo describe: "ningun job
    corria, y en silencio: el worker se declaraba ready".
    """
    worker = _prueba_del_healthcheck("celery_worker")
    assert "inspect ping" in worker, (
        f"el healthcheck del worker no pregunta si consume: {worker!r}"
    )

    # El archivo de schedule NO vive en /app: core/celery_app.py lo manda al
    # tmp del sistema (en el contenedor, /tmp) con un nombre propio. La primera
    # version de este healthcheck buscaba /app/celerybeat-schedule* y dejaba a
    # beat unhealthy para siempre; el test pasaba porque miraba un substring.
    from core.celery_app import celery_app

    archivo = Path(str(celery_app.conf.beat_schedule_filename))
    beat = _prueba_del_healthcheck("celery_beat")
    assert f"-name '{archivo.name}*'" in beat, (
        f"el healthcheck de beat no busca {archivo.name!r}, que es lo que "
        f"escribe core/celery_app.py: {beat!r}"
    )
    assert "find /tmp " in beat, (
        "el healthcheck de beat no mira /tmp, que es tempfile.gettempdir() "
        f"dentro del contenedor: {beat!r}"
    )
    assert "/app" not in beat, f"el healthcheck de beat sigue mirando /app: {beat!r}"

    for prueba in (worker, beat):
        assert "$HOSTNAME" not in prueba or "$$HOSTNAME" in prueba, (
            f"$HOSTNAME sin escapar lo interpola compose, no el shell: {prueba!r}"
        )
