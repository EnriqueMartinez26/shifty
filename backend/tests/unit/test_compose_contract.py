"""Contrato del docker-compose: Celery recibe el mismo entorno que la API.

Regresion real: los servicios celery_worker/celery_beat solo recibian las
URLs de base/broker. Settings() fallaba por SECRET_KEY y SMTP_* faltantes,
caia al respaldo (DATABASE_URL invalida, Redis en localhost) y beat no podia
encolar ninguna tarea. Ningun job corria, y en silencio: el worker se
declaraba "ready".
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config import Settings

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


class _Reset:
    """Valor de una clave marcada `!reset`: compose borra lo que traia el base."""

    def __repr__(self) -> str:
        return "!reset"


RESET = _Reset()


# PyYAML no trae stubs en el entorno (ignore_missing_imports): SafeLoader es Any.
class CargadorCompose(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader que entiende `!reset`, la etiqueta de compose (>= 2.24).

    `yaml.safe_load` rechaza una etiqueta que no conoce. Todo test que lea un
    compose pasa por aca, para que ninguno se debilite salteando el archivo.
    """


def _construir_reset(_cargador: yaml.SafeLoader, _nodo: yaml.nodes.Node) -> _Reset:
    return RESET


CargadorCompose.add_constructor("!reset", _construir_reset)


def cargar_compose(texto: str) -> dict[str, Any]:
    # CargadorCompose hereda de SafeLoader: no construye objetos de Python.
    data = yaml.load(texto, Loader=CargadorCompose)
    assert isinstance(data, dict), "el compose no es un mapa"
    return data


def fusionar(base: object, override: object) -> object:
    """Fusion de compose de `override` sobre `base`, como `docker compose config`.

    Los mapas se fusionan por clave y las LISTAS SE CONCATENAN: un `ports: []`
    o `volumes: []` en el override no quita nada. Solo `!reset` borra la clave.
    Compose reemplaza (no concatena) algunas listas como `command`; esta vista
    se usa para `ports` y `volumes`, que si concatena.
    """
    if isinstance(override, dict):
        fusionado = dict(base) if isinstance(base, dict) else {}
        for clave, valor in override.items():
            if valor is RESET:
                fusionado.pop(clave, None)
            else:
                fusionado[clave] = fusionar(fusionado.get(clave), valor)
        return fusionado
    if isinstance(override, list):
        previa = list(base) if isinstance(base, list) else []
        return previa + [item for item in override if item not in previa]
    return override


def servicios_fusionados(base: str, override: str) -> dict[str, dict[str, object]]:
    fusion = fusionar(cargar_compose(base), cargar_compose(override))
    assert isinstance(fusion, dict)
    return {
        str(nombre): dict(servicio or {})
        for nombre, servicio in dict(fusion["services"]).items()
    }


def _services() -> dict[str, dict[str, object]]:
    return dict(cargar_compose(COMPOSE.read_text(encoding="utf-8"))["services"])


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
    raiz = yaml.compose(texto, Loader=CargadorCompose)
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
    services = dict(cargar_compose(texto)["services"])
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
        ("backend", "celery_worker", "celery_worker_interactive", "celery_beat"),
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
    infra = ("db", "redis_cache", "redis_state", "rabbitmq")

    for nombre in infra:
        assert services[nombre].get("healthcheck"), (
            f"{nombre} no declara healthcheck: nadie puede esperar a que este listo"
        )

    for nombre in (
        "backend",
        "celery_worker",
        "celery_worker_interactive",
        "celery_beat",
    ):
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

SERVICIOS_DE_LA_APP = (
    "backend",
    "celery_worker",
    "celery_worker_interactive",
    "celery_beat",
)

# Sin estas no se arranca: tienen que venir del entorno con `:?`, nunca con un
# valor por default.
CRITICAS_EN_PRODUCCION = (
    "SECRET_KEY",
    "FIELD_ENCRYPTION_KEY",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "APP_DB_PASSWORD",
    "REDIS_URL",
    "REDIS_CACHE_URL",
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
    return dict(cargar_compose(COMPOSE_PROD.read_text(encoding="utf-8"))["services"])


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
        for clave in (
            "DATABASE_URL",
            "REDIS_URL",
            "REDIS_CACHE_URL",
            "CELERY_BROKER_URL",
        ):
            valor = env.get(clave, "")
            for host in ("@db:", "//redis", "@rabbitmq:"):
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

    F0-18 (decision 7): la prueba del worker dejo de ser `inspect ping`, que
    levantaba un Python completo (~120 MB) dentro del cgroup del worker. Ahora
    mira la antiguedad del archivo que el worker toca en cada `heartbeat_sent`.
    Sigue probando que CONSUME: ese latido lo emite el consumidor sobre su
    conexion al broker (bootstep Heart, cada 2 s); con la conexion caida o el
    loop del consumidor trabado deja de latir, el archivo envejece y el
    contenedor queda unhealthy. Un proceso que solo esta vivo no lo renueva.
    """
    from core.celery_app import WORKER_HEARTBEAT_FILE

    latido = Path(WORKER_HEARTBEAT_FILE)
    for nombre in ("celery_worker", "celery_worker_interactive"):
        worker = _prueba_del_healthcheck(nombre)
        assert "inspect ping" not in worker, (
            f"{nombre}: inspect ping levanta un Python entero en el cgroup: {worker!r}"
        )
        assert f"find {latido.parent.as_posix()} " in worker, (nombre, worker)
        assert f"-name '{latido.name}'" in worker, (
            f"{nombre} no mira el archivo que toca core/celery_app.py: {worker!r}"
        )
        # Obsoleto a los 120 s (decision 7): 60 latidos perdidos, no uno.
        assert "-newermt '-120 seconds'" in worker, (nombre, worker)
        assert "grep -q ." in worker, (
            f"{nombre}: find sale 0 aunque no encuentre nada: {worker!r}"
        )

    # El archivo de schedule NO vive en /app. La primera version de este
    # healthcheck buscaba /app/celerybeat-schedule* y dejaba a beat unhealthy
    # para siempre; el test pasaba porque miraba un substring. Desde F0-17 vive
    # en el volumen `beat_schedule` (antes en /tmp, que se perdia en cada
    # recreacion): el healthcheck, el montaje y core/celery_app.py tienen que
    # nombrar el MISMO directorio.
    from core.celery_app import celery_app

    archivo = Path(str(celery_app.conf.beat_schedule_filename))
    directorio = archivo.parent.as_posix()
    beat = _prueba_del_healthcheck("celery_beat")
    assert f"-name '{archivo.name}*'" in beat, (
        f"el healthcheck de beat no busca {archivo.name!r}, que es lo que "
        f"escribe core/celery_app.py: {beat!r}"
    )
    assert f"find {directorio} " in beat, (
        f"el healthcheck de beat no mira {directorio}, donde beat escribe: {beat!r}"
    )
    assert "/app" not in beat, f"el healthcheck de beat sigue mirando /app: {beat!r}"
    montajes = [_montaje(v) for v in _services()["celery_beat"].get("volumes") or []]  # type: ignore[attr-defined]
    assert ("beat_schedule", directorio) in montajes, (
        f"el schedule de beat no vive en el volumen beat_schedule: {montajes}"
    )
    dockerfile = (COMPOSE.parent / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert directorio in dockerfile, (
        "la imagen no crea el directorio del schedule con dueno appuser: un "
        "volumen nuevo copia el dueno de la imagen, y sin el beat no escribe"
    )

    for prueba in (_prueba_del_healthcheck("celery_worker"), beat):
        assert "$HOSTNAME" not in prueba or "$$HOSTNAME" in prueba, (
            f"$HOSTNAME sin escapar lo interpola compose, no el shell: {prueba!r}"
        )


# --- El ejemplo de produccion tiene que levantar el stack (AUD2-C-01, V-diff) --
#
# compose interpola cada archivo ANTES de fusionarlos: un `${VAR:?}` del compose
# base aborta `docker compose config` en produccion aunque el override no use
# esa variable. Asi que toda variable exigida con `:?` en cualquiera de los dos
# composes tiene que estar declarada en backend/.env.production.example, que
# es el archivo que el operador copia a la RAIZ como .env.

ENV_PRODUCCION_EXAMPLE = COMPOSE_PROD.parent / "backend" / ".env.production.example"


def _exigidas_con_interrogacion() -> set[str]:
    exigidas: set[str] = set()
    for compose in (COMPOSE, COMPOSE_PROD):
        exigidas.update(re.findall(r"\$\{([A-Z_]+):\?", compose.read_text("utf-8")))
    return exigidas


def _declaradas_en(ruta: Path) -> set[str]:
    return {
        linea.split("=", 1)[0].strip()
        for linea in ruta.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.lstrip().startswith("#") and "=" in linea
    }


# Exigidas con `:?` pero que NO van en el .env: las pasa el script de deploy en
# cada corrida. APP_VERSION en el .env queda vieja despues del primer deploy y
# un `up` a mano volveria a la version anterior (docs/DEPLOY_RUNBOOK.md).
NO_VAN_EN_EL_ENV = {"APP_VERSION"}


def test_el_ejemplo_de_produccion_declara_todo_lo_que_los_composes_exigen() -> None:
    exigidas = _exigidas_con_interrogacion()
    assert exigidas, "ningun compose exige variables con :?"
    assert NO_VAN_EN_EL_ENV <= exigidas, "la excepcion nombra variables que nadie exige"
    faltan = exigidas - NO_VAN_EN_EL_ENV - _declaradas_en(ENV_PRODUCCION_EXAMPLE)
    assert not faltan, (
        "el compose aborta en produccion si falta alguna de estas, y el "
        f"ejemplo que se copia como .env no las declara: {sorted(faltan)}"
    )


def test_el_ejemplo_de_produccion_dice_que_se_copia_a_la_raiz() -> None:
    texto = ENV_PRODUCCION_EXAMPLE.read_text(encoding="utf-8")
    assert "raiz" in texto.lower() and "env_file" in texto, (
        "nadie dice que este archivo se copia a la raiz del repo como .env, que "
        "es lo que resuelve env_file: .env en docker-compose.prod.yml"
    )


def test_el_override_fija_env_production() -> None:
    for servicio in SERVICIOS_DE_LA_APP:
        assert _env_prod(servicio).get("ENV") == "production", (
            f"{servicio}: el override no fija ENV=production y las guardas de "
            "core/config.py no se activan"
        )


def test_el_worker_de_celery_acota_su_concurrencia_y_su_memoria() -> None:
    """2026-09-24: el worker vivia al 99% de su limite de 512 MB.

    Sin `--concurrency`, Celery prefork abre un hijo por CPU del host (8 en la
    maquina de desarrollo, 9 procesos de 85-110 MB). Los jobs periodicos estan
    serializados por advisory locks y SKIP LOCKED, asi que mas hijos no procesan
    mas rapido: solo reservan memoria y un pool de conexiones cada uno. Un hijo
    que pase el limite del contenedor lo mata el OOM killer en medio de un job.
    """
    comando = str(_services()["celery_worker"]["command"])
    concurrencia = re.search(r"--concurrency[= ](\S+)", comando)
    assert concurrencia, f"el worker no fija --concurrency: {comando!r}"
    assert "--max-memory-per-child" in comando, (
        f"el worker no recicla hijos que crecen: {comando!r}"
    )


# --- El codigo sale de la imagen (2026-09-24) ---------------------------------
#
# Sintoma: el compose base montaba ./backend:/app (con /app/.venv anonimo
# encima) en backend, celery_worker y celery_beat, y ./frontend:/app (con
# /app/node_modules) en frontend. El override de produccion intentaba
# cancelarlos con `volumes: []`, pero compose FUSIONA las listas: una lista
# vacia no quita nada (solo `!reset` lo haria), y `docker-compose config` de
# produccion seguia mostrando los montajes. Produccion corria el checkout del
# servidor en vez de la imagen; el .venv anonimo sobrevivia entre deploys y
# quedaba viejo (el crash-loop del contenedor no-root); y en Docker Desktop
# importar la app por el bind mount tardaba ~131 s, mas que el healthcheck de
# Celery. uvicorn corre sin --reload: el montaje no daba recarga en caliente.

SERVICIOS_CON_CODIGO = (
    "backend",
    "celery_worker",
    "celery_worker_interactive",
    "celery_beat",
    "frontend",
)
FUENTES_DE_CODIGO = ("./backend", "./frontend", "backend", "frontend")


def _montaje(volumen: object) -> tuple[str, str]:
    """(origen, destino) de un volumen en forma corta o larga; origen '' si es anonimo."""
    if isinstance(volumen, dict):
        return str(volumen.get("source") or ""), str(volumen.get("target") or "")
    partes = str(volumen).split(":")
    if len(partes) == 1:
        return "", partes[0]
    return partes[0], partes[1]


def montajes_de_codigo(
    servicios: dict[str, Any], nombres: tuple[str, ...]
) -> list[str]:
    """Volumenes que tapan /app o que traen el codigo del host.

    Recibe servicios ya cargados: el compose base o la vista fusionada.
    """
    encontrados: list[str] = []
    for nombre in nombres:
        for volumen in (servicios[nombre] or {}).get("volumes") or []:
            origen, destino = _montaje(volumen)
            origen = origen.rstrip("/")
            tapa_app = destino == "/app" or destino.startswith("/app/")
            trae_codigo = any(
                origen == fuente or origen.startswith(f"{fuente}/")
                for fuente in FUENTES_DE_CODIGO
            )
            if tapa_app or trae_codigo:
                encontrados.append(f"{nombre}: {volumen}")
    return encontrados


def test_los_servicios_de_la_app_no_montan_codigo_del_host() -> None:
    # Tambien la vista FUSIONADA de produccion: un override que agregue
    # ./backend:/app no aparece mirando solo el compose base.
    vistas = {
        "compose base": _services(),
        "produccion (base + override)": _servicios_de_produccion(),
    }
    for vista, servicios in vistas.items():
        encontrados = montajes_de_codigo(servicios, SERVICIOS_CON_CODIGO)
        assert not encontrados, (
            f"{vista}: el codigo tiene que salir de la imagen, no de un montaje "
            f"sobre /app: {encontrados}"
        )


_COMPOSE_CON_MONTAJES_DE_CODIGO = """
services:
  backend:
    volumes:
      - ./backend:/app
      - /app/.venv
  frontend:
    volumes:
      - type: bind
        source: ./frontend/src
        target: /srv/src
"""


def test_el_contrato_ve_los_montajes_de_codigo_en_cualquier_forma() -> None:
    """Sin este contraejemplo, el test de arriba podria no detectar nada."""
    encontrados = montajes_de_codigo(
        cargar_compose(_COMPOSE_CON_MONTAJES_DE_CODIGO)["services"],
        ("backend", "frontend"),
    )
    assert len(encontrados) == 3, encontrados


_BASE_SIN_MONTAJES = """
services:
  backend:
    image: shifty-backend
"""

_OVERRIDE_QUE_MONTA_CODIGO = """
services:
  backend:
    volumes:
      - ./backend:/app
"""


def test_el_contrato_ve_un_montaje_que_agrega_el_override_de_produccion() -> None:
    """El base limpio no alcanza: lo que corre es la fusion con el override."""
    encontrados = montajes_de_codigo(
        servicios_fusionados(_BASE_SIN_MONTAJES, _OVERRIDE_QUE_MONTA_CODIGO),
        ("backend",),
    )
    assert encontrados == ["backend: ./backend:/app"], encontrados


def test_produccion_no_cancela_listas_con_una_lista_vacia() -> None:
    """`volumes: []` o `ports: []` en el override no quitan los del base:
    compose fusiona listas. Lo que se quiere quitar va con `!reset []`."""
    vacias = [
        f"{nombre}.{clave}"
        for nombre, servicio in _servicios_prod().items()
        if isinstance(servicio, dict)
        for clave in ("volumes", "ports")
        if clave in servicio and servicio[clave] in ([], None)
    ]
    assert not vacias, (
        "estas claves del override son una lista vacia, que no cancela lo que "
        f"declara el compose base (usar `!reset []`): {vacias}"
    )


# --- En produccion solo nginx publica puertos (2026-09-24) --------------------
#
# Sintoma: el override declaraba `ports: []` en backend, frontend, db, redis y
# rabbitmq para despublicarlos, pero compose fusiona las listas: el `config` de
# produccion seguia publicando en 127.0.0.1 backend:8000, frontend:3000,
# db:5432, redis:6379 y rabbitmq:5672/15672. Con backend:8000 alcanzable desde
# el host se salteaba nginx y se podia spoofear X-Forwarded-For para evadir el
# rate limit. Solo `ports: !reset []` (compose >= 2.24) los quita. Por eso el
# contrato mira la vista FUSIONADA, no el override suelto.


def _servicios_de_produccion() -> dict[str, dict[str, object]]:
    """Base + override fusionados: lo que corre en produccion."""
    return servicios_fusionados(
        COMPOSE.read_text(encoding="utf-8"), COMPOSE_PROD.read_text(encoding="utf-8")
    )


def puertos_publicados(
    servicios: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    return {
        nombre: [str(puerto) for puerto in puertos]
        for nombre, servicio in servicios.items()
        if isinstance(puertos := servicio.get("ports"), list) and puertos
    }


def test_en_produccion_solo_nginx_publica_puertos() -> None:
    publicados = puertos_publicados(_servicios_de_produccion())
    assert set(publicados) == {"nginx"}, (
        f"en produccion publican puertos servicios internos, no solo nginx: {publicados}"
    )
    assert {"80:80", "443:443"} <= set(publicados["nginx"]), publicados["nginx"]


_BASE_CON_PUERTOS = """
services:
  backend:
    ports:
      - "127.0.0.1:8000:8000"
"""

_OVERRIDE_CON_LISTA_VACIA = """
services:
  backend:
    ports: []
"""

_OVERRIDE_CON_RESET = """
services:
  backend:
    ports: !reset []
"""


def test_la_vista_fusionada_distingue_la_lista_vacia_del_reset() -> None:
    """Sin este contraejemplo, la fusion del test podria no ser la de compose."""
    con_lista_vacia = servicios_fusionados(_BASE_CON_PUERTOS, _OVERRIDE_CON_LISTA_VACIA)
    assert puertos_publicados(con_lista_vacia) == {"backend": ["127.0.0.1:8000:8000"]}
    con_reset = servicios_fusionados(_BASE_CON_PUERTOS, _OVERRIDE_CON_RESET)
    assert puertos_publicados(con_reset) == {}


# --- La API escala por replicas de un proceso (F0-04, plan de rendimiento) ----
#
# Decision de Mateo (2026-09-24): tres replicas de UN proceso de uvicorn, no
# `--workers 3`. Con varios workers dentro de un contenedor, uno que muere en
# loop queda escondido detras de un contenedor "sano" (regla 21). Con replicas,
# cada proceso tiene su healthcheck y su reinicio. `container_name` fija un
# nombre unico por servicio, asi que compose no puede levantar mas de una.


def _dockerfile_cmd() -> list[str]:
    import json

    dockerfile = COMPOSE.parent / "backend" / "Dockerfile"
    lineas = [
        linea
        for linea in dockerfile.read_text(encoding="utf-8").splitlines()
        if linea.startswith("CMD ")
    ]
    assert len(lineas) == 1, f"el Dockerfile del backend declara {len(lineas)} CMD"
    cmd = json.loads(lineas[0].removeprefix("CMD "))
    assert isinstance(cmd, list), "el CMD no esta en forma exec (JSON)"
    return [str(parte) for parte in cmd]


def test_la_api_escala_por_replicas_de_un_proceso() -> None:
    base = _services()["backend"]
    assert "container_name" not in base, (
        "backend fija container_name: compose no puede levantar mas de una replica"
    )
    deploy_base = base.get("deploy") or {}
    assert isinstance(deploy_base, dict)
    assert deploy_base.get("replicas", 1) == 1, "en desarrollo corre una sola replica"

    deploy_prod = _servicios_de_produccion()["backend"].get("deploy") or {}
    assert isinstance(deploy_prod, dict)
    assert deploy_prod.get("replicas") == 3, (
        f"produccion no corre tres replicas de la API: {deploy_prod!r}"
    )

    cmd = _dockerfile_cmd()
    assert cmd[0] == "uvicorn", cmd
    assert not any(parte.startswith("--workers") for parte in cmd), (
        f"la API vuelve a multiplicarse por dentro del contenedor: {cmd}"
    )
    assert "command" not in base, "backend no puede pisar el CMD de la imagen"


# --- Apagado ordenado (F0-21, plan de rendimiento) ----------------------------
#
# Docker manda SIGTERM y, pasado `stop_grace_period` (10 s por default), SIGKILL.
# uvicorn sin `--timeout-graceful-shutdown` espera a las conexiones abiertas sin
# tope, asi que el SIGKILL cortaba requests a mitad de un cobro. El proceso
# tiene que rendirse ANTES de que docker lo mate: el margen entre los dos es
# lo que asegura que el cierre del pool y de Redis (lifespan) llegue a correr.
# El worker de Celery termina la tarea en curso (acks_late): su margen cubre el
# soft time limit tipico de un lote, no el hard limit entero.


def _segundos(valor: object) -> float:
    texto = str(valor).strip()
    match = re.fullmatch(r"(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", texto)
    assert match and texto, f"duracion de compose no reconocida: {valor!r}"
    return int(match.group(1) or 0) * 60 + float(match.group(2) or 0)


def test_la_api_se_apaga_antes_de_que_docker_la_mate() -> None:
    cmd = _dockerfile_cmd()
    assert "--timeout-graceful-shutdown" in cmd, (
        f"uvicorn espera conexiones abiertas sin tope al apagarse: {cmd}"
    )
    tope = float(cmd[cmd.index("--timeout-graceful-shutdown") + 1])
    gracia = _segundos(_services()["backend"].get("stop_grace_period", "10s"))
    assert tope == 30, f"el tope de apagado de uvicorn es {tope}, el plan fija 30"
    assert gracia >= tope + 5, (
        f"docker mata la API a los {gracia}s y uvicorn recien se rinde a los {tope}s"
    )


def test_el_worker_tiene_tiempo_de_terminar_la_tarea_en_curso() -> None:
    gracia = _segundos(_services()["celery_worker"].get("stop_grace_period", "10s"))
    assert gracia >= 60, f"el worker recibe SIGKILL a los {gracia}s"


# --- Imagenes con version, una sola para la app (F0-02, plan de rendimiento) --
#
# API, worker y beat corren EL MISMO codigo: si cada uno construye su imagen,
# reconstruir solo uno deja a los otros con el codigo viejo (regla 22; paso con
# Celery como root). Ahora hay una imagen, construida solo por `backend` y
# reutilizada por los procesos de Celery, con el tag de la version: el VPS hace
# `pull` de lo que publico CI y el rollback es volver al tag anterior.

REGISTRO = "ghcr.io/enriquemartinez26"
PROCESOS_DE_LA_APP = (
    "backend",
    "celery_worker",
    "celery_worker_interactive",
    "celery_beat",
)


def _imagen(servicio: str) -> str:
    return f"{REGISTRO}/shifty-{servicio}:${{APP_VERSION:-dev}}"


def test_la_app_corre_una_sola_imagen_versionada() -> None:
    servicios = _services()
    for nombre in PROCESOS_DE_LA_APP:
        assert servicios[nombre].get("image") == _imagen("backend"), (
            f"{nombre} no corre la imagen versionada de la app: "
            f"{servicios[nombre].get('image')!r}"
        )
    constructores = [n for n in PROCESOS_DE_LA_APP if "build" in servicios[n]]
    assert constructores == ["backend"], (
        "la imagen de la app la construye solo backend; los procesos de Celery "
        f"la reutilizan: construyen {constructores}"
    )
    for nombre in ("frontend", "nginx"):
        assert servicios[nombre].get("image") == _imagen(nombre), (
            f"{nombre}: {servicios[nombre].get('image')!r}"
        )


def test_la_version_llega_a_los_procesos_de_la_app() -> None:
    # Alimenta Settings.VERSION: el release de Sentry y el de la API.
    assert _env_items(_services()["backend"]).get("VERSION") == "${APP_VERSION:-dev}"
    for servicio in SERVICIOS_DE_LA_APP:
        assert "${APP_VERSION:?" in _env_prod(servicio).get("VERSION", ""), (
            f"{servicio}: produccion no exige la version desplegada"
        )


def test_produccion_no_corre_una_imagen_sin_version() -> None:
    """Sin APP_VERSION, `:-dev` en el servidor corre lo que haya quedado con ese
    tag (un build local viejo) en vez de fallar."""
    produccion = _servicios_de_produccion()
    for nombre in (*PROCESOS_DE_LA_APP, "frontend"):
        imagen = str(produccion[nombre].get("image", ""))
        assert imagen.startswith(f"{REGISTRO}/shifty-"), (nombre, imagen)
        assert "${APP_VERSION:?" in imagen, (
            f"{nombre} en produccion no exige APP_VERSION: {imagen!r}"
        )


# --- Infraestructura con version fija (F0-05, plan de rendimiento) ------------
#
# `postgres:16-alpine` o `redis:7-alpine` se mueven solos: un `pull` + `up`
# recreaba la base con otra version menor sin que nadie lo decidiera. Cada
# imagen de terceros declara al menos version menor; subirla es un commit.

VERSION_FIJA = re.compile(r"^[a-z0-9./-]+:\d+\.\d+(\.\d+)?(-[a-z0-9]+)*$")


def imagenes_sin_version_fija(servicios: dict[str, dict[str, object]]) -> list[str]:
    return [
        f"{nombre}: {imagen}"
        for nombre, servicio in servicios.items()
        if (imagen := str(servicio.get("image", "")))
        and not imagen.startswith(f"{REGISTRO}/")
        and not VERSION_FIJA.match(imagen)
    ]


def test_la_infraestructura_corre_versiones_fijas() -> None:
    for vista, servicios in {
        "compose base": _services(),
        "produccion (base + override)": _servicios_de_produccion(),
    }.items():
        sueltas = imagenes_sin_version_fija(servicios)
        assert not sueltas, f"{vista}: imagenes sin version menor fija: {sueltas}"
    assert _services()["db"]["image"] == "postgres:16.14-alpine"


def test_el_contrato_ve_una_imagen_con_solo_la_version_mayor() -> None:
    servicios: dict[str, dict[str, object]] = {
        "db": {"image": "postgres:16-alpine"},
        "cache": {"image": "redis:7.4-alpine"},
        "mq": {"image": "rabbitmq:latest"},
    }
    assert imagenes_sin_version_fija(servicios) == [
        "db: postgres:16-alpine",
        "mq: rabbitmq:latest",
    ]


# --- Postgres dimensionado (F0-14, plan de rendimiento) -----------------------
#
# Con los defaults de la imagen (shared_buffers 128 MB, work_mem 4 MB, jit on,
# sin pg_stat_statements ni slow log) la base no usaba la memoria del VPS y no
# habia forma de ver que consulta era lenta. `command` NO se fusiona: el del
# override reemplaza entero al del base, por eso produccion repite
# shared_preload_libraries y el umbral del slow log.

POSTGRES_PRODUCCION = {
    "shared_buffers": "1GB",
    "effective_cache_size": "3GB",
    "work_mem": "8MB",
    "maintenance_work_mem": "256MB",
    "max_connections": "150",
    "max_wal_size": "2GB",
    "min_wal_size": "512MB",
    "checkpoint_timeout": "15min",
    "wal_compression": "lz4",
    "random_page_cost": "1.1",
    "effective_io_concurrency": "200",
    "jit": "off",
    "autovacuum_naptime": "30s",
    "autovacuum_vacuum_cost_limit": "1000",
    "log_min_duration_statement": "250",
    # Sin los valores de los parametros: el slow log no puede volcar emails ni
    # telefonos que vayan como bind.
    "log_parameter_max_length": "0",
    "log_lock_waits": "on",
    "log_temp_files": "0",
    "log_autovacuum_min_duration": "5s",
    "track_io_timing": "on",
    "shared_preload_libraries": "pg_stat_statements",
}

POSTGRES_DESARROLLO = {
    "shared_preload_libraries": "pg_stat_statements",
    "log_min_duration_statement": "250",
}


def parametros_de_postgres(comando: object) -> dict[str, str]:
    """`-c clave=valor` del command de postgres, en forma de lista o de texto."""
    partes = comando if isinstance(comando, list) else str(comando).split()
    partes = [str(p) for p in partes]
    assert partes and partes[0] == "postgres", f"no arranca postgres: {partes}"
    parametros: dict[str, str] = {}
    for i, parte in enumerate(partes):
        if parte == "-c":
            clave, _, valor = partes[i + 1].partition("=")
            parametros[clave] = valor
    return parametros


def test_postgres_de_desarrollo_mide_las_consultas_lentas() -> None:
    db = _services()["db"]
    parametros = parametros_de_postgres(db.get("command"))
    assert parametros == POSTGRES_DESARROLLO, parametros
    assert db.get("shm_size") == "256m", db.get("shm_size")


def test_postgres_de_produccion_usa_la_memoria_del_servidor() -> None:
    db = _servicios_prod()["db"]
    assert parametros_de_postgres(db.get("command")) == POSTGRES_PRODUCCION
    # shared_buffers de 1 GB necesita /dev/shm; el default de docker es 64 MB.
    assert db.get("shm_size") == "512m", db.get("shm_size")
    # Si el host se queda sin memoria, el OOM killer elige otro proceso antes
    # que la base.
    assert db.get("oom_score_adj") == -800, db.get("oom_score_adj")
    limites = _servicios_de_produccion()["db"]["deploy"]
    assert isinstance(limites, dict)
    assert limites["resources"]["limits"]["memory"] == "4G", limites


# --- Pool de la base: 5 + 5 por proceso (F2-04, plan de rendimiento) ---------
#
# Con los mails y Mercado Pago fuera de las transacciones (F1-05, F2-01,
# F2-02) ningun request retiene una conexion durante una llamada de red, asi
# que el pool por proceso baja de 10 + 5 a 5 + 5. La suma de todos los
# procesos que abren conexiones tiene que entrar en max_connections con lugar
# para migraciones, backups y una consola.

POOL_POR_PROCESO = {
    "DB_POOL_SIZE": "${DB_POOL_SIZE:-5}",
    "DB_MAX_OVERFLOW": "${DB_MAX_OVERFLOW:-5}",
}


def _concurrencia(servicio: str) -> int:
    encontrado = re.search(r"--concurrency=(?:\$\{[A-Z_]+:-)?(\d+)", _comando(servicio))
    assert encontrado, _comando(servicio)
    return int(encontrado.group(1))


def test_el_pool_de_la_base_es_de_5_mas_5_por_proceso() -> None:
    desarrollo = _env_items(_services()["backend"])
    for clave, valor in POOL_POR_PROCESO.items():
        assert desarrollo.get(clave) == valor, (clave, desarrollo.get(clave))
        assert _env_prod("backend").get(clave) == valor, clave


def _default_de(valor: str) -> int:
    encontrado = re.fullmatch(r"\$\{[A-Z_]+:-(\d+)\}", valor)
    assert encontrado, valor
    return int(encontrado.group(1))


def test_los_pools_de_produccion_entran_en_max_connections() -> None:
    entorno = _env_prod("backend")
    por_proceso = _default_de(entorno.get("DB_POOL_SIZE", "")) + _default_de(
        entorno.get("DB_MAX_OVERFLOW", "")
    )
    deploy = _servicios_prod()["backend"]["deploy"]
    assert isinstance(deploy, dict)
    replicas = int(deploy["replicas"])
    hijos = _concurrencia("celery_worker") + _concurrencia("celery_worker_interactive")
    de_la_app = (replicas + hijos) * por_proceso
    tope = int(POSTGRES_PRODUCCION["max_connections"])
    # Beat no corre tareas y los padres de prefork desechan su pool antes del
    # fork (core/celery_app.py): no suman. Margen: la mitad para el resto.
    assert de_la_app <= tope // 2, (de_la_app, tope)


# --- Dos Redis: cache y estado (F0-15, plan de rendimiento; decision 5) -------
#
# Un solo Redis con desalojo expulsaba lockout, idempotencia y rate limit bajo
# presion de memoria; sin desalojo, el cache de disponibilidad lo llenaba y
# TODA escritura fallaba. El de cache desaloja y no persiste (se recalcula); el
# de estado no desaloja y guarda RDB (un reinicio no borra lockouts ni el replay
# de idempotencia de un cobro). El codigo solo manda al de cache la
# disponibilidad (core/redis.py::get_availability_cache).


def _argumentos(comando: object) -> list[str]:
    assert isinstance(comando, list), (
        f"el command no esta en forma de lista: {comando!r}"
    )
    return [str(parte) for parte in comando]


def _opcion(argumentos: list[str], nombre: str) -> list[str]:
    i = argumentos.index(nombre)
    siguiente = [
        j for j in range(i + 1, len(argumentos)) if argumentos[j].startswith("--")
    ]
    return argumentos[i + 1 : siguiente[0] if siguiente else len(argumentos)]


def _megas(valor: str) -> int:
    match = re.fullmatch(r"(\d+)(mb|m|M)", valor)
    assert match, valor
    return int(match.group(1))


def _limite(servicio: dict[str, object]) -> str:
    deploy = servicio.get("deploy")
    assert isinstance(deploy, dict), servicio
    return str(deploy["resources"]["limits"]["memory"])


def test_el_redis_de_cache_desaloja_y_no_persiste() -> None:
    servicios = _services()
    assert "redis" not in servicios, "sigue el Redis unico"
    cache = servicios["redis_cache"]
    argumentos = _argumentos(cache.get("command"))
    assert argumentos[0] == "redis-server", argumentos
    # volatile-ttl: toda clave del cache tiene TTL, y el desalojo empieza por
    # la que vence antes. Los slots (300 s) se van antes que las versiones y
    # generaciones (7 dias): se sostiene el invariante de
    # core/availability_cache.py (una version no desaparece mientras viva un
    # slot escrito bajo ella). allkeys-lru podia expulsar una version antes.
    assert _opcion(argumentos, "--maxmemory-policy") == ["volatile-ttl"]
    assert _opcion(argumentos, "--save") == [""], "el cache no persiste"
    assert _opcion(argumentos, "--appendonly") == ["no"]
    maxmemory = _megas(_opcion(argumentos, "--maxmemory")[0])
    assert maxmemory == 96
    # El limite del contenedor deja margen para la fragmentacion y los buffers
    # de clientes, que maxmemory no cuenta.
    assert _megas(_limite(cache)) >= 2 * maxmemory
    assert not cache.get("volumes"), "el cache no necesita volumen"


def test_el_redis_de_estado_no_desaloja_y_persiste() -> None:
    estado = _services()["redis_state"]
    argumentos = _argumentos(estado.get("command"))
    assert _opcion(argumentos, "--maxmemory-policy") == ["noeviction"]
    assert _opcion(argumentos, "--save") == ["60", "1"]
    maxmemory = _megas(_opcion(argumentos, "--maxmemory")[0])
    assert maxmemory == 48
    assert _megas(_limite(estado)) >= 2 * maxmemory
    volumenes = estado.get("volumes") or []
    assert isinstance(volumenes, list), volumenes
    destinos = [_montaje(v) for v in volumenes]
    assert ("redis_state_data", "/data") in destinos, destinos


def test_cada_uso_de_redis_apunta_a_su_instancia() -> None:
    env = _env_items(_services()["backend"])
    assert env["REDIS_URL"].startswith("redis://redis_state:"), env["REDIS_URL"]
    assert env["REDIS_CACHE_URL"].startswith("redis://redis_cache:"), env
    # Los resultados de Celery son estado, no cache.
    assert env["CELERY_RESULT_BACKEND_URL"].startswith("redis://redis_state:"), env
    # 2 s x 2 intentos x ~6 operaciones por request retenian un request 24 s
    # con Redis caido; con 0,5 s el peor caso baja a 6.
    for clave in (
        "REDIS_SOCKET_TIMEOUT_SECONDS",
        "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
    ):
        for vista, valor in (
            ("desarrollo", env[clave]),
            ("produccion", _env_prod("backend")[clave]),
        ):
            assert valor == "0.5" or valor.endswith(":-0.5}"), (vista, clave, valor)


# --- RabbitMQ acotado (F0-16, plan de rendimiento; decision 6) ----------------
#
# Sin configuracion, RabbitMQ calcula su alarma de memoria como el 40% de la
# RAM que VE, que en un contenedor es la del host (16 GB): el limite de 256 MB
# del cgroup lo mataba por OOM mucho antes de que la alarma frenara a los
# publicadores. Con el umbral absoluto por debajo del limite, la alarma llega
# primero. Produccion corre la imagen sin management (el 15672 ya no se
# publica y el plugin cuesta memoria).

RABBITMQ_CONF = COMPOSE.parent / "deploy" / "rabbitmq" / "rabbitmq.conf"
RABBITMQ_CONF_EN_EL_CONTENEDOR = "/etc/rabbitmq/conf.d/10-shifty.conf"


def _conf_de_rabbitmq() -> dict[str, str]:
    return {
        clave.strip(): valor.strip()
        for linea in RABBITMQ_CONF.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.lstrip().startswith("#")
        for clave, _, valor in [linea.partition("=")]
    }


def test_rabbitmq_frena_a_los_publicadores_antes_del_oom() -> None:
    conf = _conf_de_rabbitmq()
    assert conf.get("vm_memory_high_watermark.absolute") == "280MiB", conf
    assert conf.get("disk_free_limit.absolute") == "1GB", conf

    for vista, servicios in {
        "compose base": _services(),
        "produccion (base + override)": _servicios_de_produccion(),
    }.items():
        rabbit = servicios["rabbitmq"]
        montajes = [str(v) for v in rabbit.get("volumes") or []]  # type: ignore[attr-defined]
        esperado = (
            f"./deploy/rabbitmq/rabbitmq.conf:{RABBITMQ_CONF_EN_EL_CONTENEDOR}:ro"
        )
        assert esperado in montajes, (vista, montajes)
        assert _megas(_limite(rabbit)) == 384, (vista, _limite(rabbit))
        # 280 MiB de alarma dentro de 384 MB de limite: margen para Erlang.
        assert 280 < _megas(_limite(rabbit))
        # Con 180 MiB un broker recien arrancado ya levantaba la alarma en un
        # host de 16 nucleos (~170 MB propios); dos schedulers de Erlang
        # bajan la memoria base (decision de Mateo, 2026-09-24).
        env = _env_items(rabbit)
        assert env.get("RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS") == "+S 2:2", (vista, env)
        # El healthcheck no puede depender del plugin de management.
        prueba = str(rabbit["healthcheck"]["test"])  # type: ignore[index]
        assert "check_running" in prueba and "15672" not in prueba, prueba


def test_produccion_corre_rabbitmq_sin_management() -> None:
    imagen = str(_servicios_de_produccion()["rabbitmq"]["image"])
    assert imagen == "rabbitmq:3.13.7-alpine", imagen
    assert "management" in str(_services()["rabbitmq"]["image"]), (
        "desarrollo conserva la consola de management"
    )


# --- Workers de Celery (F0-18, plan de rendimiento; decision 7) ---------------
#
# El worker general consume solo la cola `celery` y recicla los hijos que pasan
# 150 MB; el OTP va a la cola `interactive`, que atiende un worker aparte con
# un solo hijo: su latencia no depende de que termine un lote del outbox.


def _comando(nombre: str) -> str:
    return str(_services()[nombre].get("command", ""))


def test_el_worker_general_consume_la_cola_celery_con_tope_de_memoria() -> None:
    worker = _services()["celery_worker"]
    comando = _comando("celery_worker")
    assert re.search(r"(^| )-Q celery( |$)", comando), comando
    assert "--max-memory-per-child=150000" in comando, comando
    assert _limite(worker) == "768M", _limite(worker)
    deploy = worker["deploy"]
    assert isinstance(deploy, dict)
    assert str(deploy["resources"]["limits"].get("cpus")) == "1.5", deploy


def test_el_otp_tiene_su_propio_worker() -> None:
    servicios = _services()
    interactivo = servicios["celery_worker_interactive"]
    comando = _comando("celery_worker_interactive")
    assert re.search(r"(^| )-Q interactive( |$)", comando), comando
    assert "--concurrency=1" in comando, comando
    assert "--max-memory-per-child=" in comando, comando
    assert _limite(interactivo) == "256M", _limite(interactivo)
    assert interactivo.get("image") == servicios["celery_worker"].get("image")
    assert "build" not in interactivo
    assert _segundos(interactivo.get("stop_grace_period", "10s")) >= 30
    # La cola la fija core/celery_app.py; si cambia ahi, este worker no la ve.
    from core.celery_app import celery_app

    assert celery_app.conf.task_routes["send_otp_email"]["queue"] == "interactive"
    assert celery_app.conf.task_routes["send_booking_email"]["queue"] == "interactive"


# --- Limites de memoria para el VPS de 16 GB (F0-19, plan de rendimiento) -----
#
# Sin limite, un contenedor que crece se come la memoria del host y el OOM
# killer elige a cualquiera (la base incluida). La suma de la tabla deja
# margen para el sistema y el cache de disco de Postgres. Sin `cpus` en la API
# ni en la base: el throttling de CFS mete picos en el p95 (plan §8).

LIMITES_EN_PRODUCCION = {
    "db": "4G",
    "redis_cache": "192M",
    "redis_state": "96M",
    "rabbitmq": "384M",
    "backend": "512M",
    "celery_worker": "768M",
    "celery_worker_interactive": "256M",
    "celery_beat": "256M",
    "frontend": "64M",
    "nginx": "256M",
}


def test_cada_servicio_tiene_su_limite_de_memoria() -> None:
    produccion = _servicios_de_produccion()
    assert set(produccion) == set(LIMITES_EN_PRODUCCION), sorted(produccion)
    limites = {nombre: _limite(servicio) for nombre, servicio in produccion.items()}
    assert limites == LIMITES_EN_PRODUCCION, limites
    replicas = produccion["backend"]["deploy"]["replicas"]  # type: ignore[index]
    assert replicas == 3


def test_la_api_y_la_base_no_tienen_tope_de_cpu() -> None:
    for vista, servicios in {
        "compose base": _services(),
        "produccion (base + override)": _servicios_de_produccion(),
    }.items():
        for nombre in ("backend", "db"):
            deploy = servicios[nombre].get("deploy") or {}
            assert isinstance(deploy, dict)
            limites = deploy.get("resources", {}).get("limits", {})
            assert "cpus" not in limites, f"{vista}: {nombre} con tope de CPU"


def test_nginx_puede_abrir_suficientes_conexiones() -> None:
    ulimits = _services()["nginx"].get("ulimits")
    assert isinstance(ulimits, dict), ulimits
    nofile = ulimits.get("nofile")
    valores = list(nofile.values()) if isinstance(nofile, dict) else [nofile]
    assert all(int(str(v)) >= 65536 for v in valores), nofile


def test_nginx_de_produccion_sirve_el_desafio_de_certbot() -> None:
    """F0-12 (decision 4): certbot en el host con webroot. El borde sirve
    `/.well-known/acme-challenge/` desde /var/www/acme (nginx/, lane A); sin
    el montaje la renovacion del certificado falla a los 90 dias."""
    montajes = [str(v) for v in _servicios_prod()["nginx"].get("volumes") or []]  # type: ignore[attr-defined]
    assert "./nginx/acme:/var/www/acme:ro" in montajes, montajes


# --- Logs con rotacion (F0-22, plan de rendimiento; decision 26) --------------
#
# El driver json-file por defecto no rota: un contenedor ruidoso llenaba el
# disco del host, que es el mismo de la base. 20 MB x 5 por contenedor. Un
# solo ancla, igual que el entorno: un servicio nuevo que copie el bloque a
# mano hoy coincide y manana no.

LOGGING_ESPERADO = {
    "driver": "json-file",
    "options": {"max-size": "20m", "max-file": "5"},
}


def test_todos_los_servicios_rotan_sus_logs() -> None:
    texto = COMPOSE.read_text(encoding="utf-8")
    servicios = _services()
    for nombre, servicio in servicios.items():
        assert servicio.get("logging") == LOGGING_ESPERADO, (
            f"{nombre} no rota sus logs: {servicio.get('logging')!r}"
        )
    raiz = yaml.compose(texto, Loader=CargadorCompose)
    assert raiz is not None
    nodos = {
        nombre: _nodo_hijo(_nodo_hijo(_nodo_hijo(raiz, "services"), nombre), "logging")
        for nombre in servicios
    }
    primero = next(iter(nodos.values()))
    copiados = [nombre for nombre, nodo in nodos.items() if nodo is not primero]
    assert not copiados, f"estos servicios no usan el ancla x-logging: {copiados}"


def test_la_api_no_duplica_el_access_log_de_nginx() -> None:
    # nginx ya registra cada request; el access log de uvicorn duplicaba
    # cada linea y llevaba la query entera (client_phone incluido).
    assert "--no-access-log" in _dockerfile_cmd()


def test_app_version_la_pasa_el_deploy_y_no_el_env() -> None:
    """APP_VERSION en el .env queda vieja despues del primer deploy. El `:?`
    sigue: un `up` a mano en produccion sin la version falla a la vista, y el
    mensaje dice de donde sale."""
    declaradas = _declaradas_en(ENV_PRODUCCION_EXAMPLE)
    assert not (NO_VAN_EN_EL_ENV & declaradas), (
        f"el ejemplo del .env declara {sorted(NO_VAN_EN_EL_ENV & declaradas)}"
    )
    texto = COMPOSE_PROD.read_text(encoding="utf-8")
    mensajes = re.findall(r"\$\{APP_VERSION:\?([^}]*)\}", texto)
    assert mensajes, "produccion no exige APP_VERSION"
    for mensaje in mensajes:
        assert "scripts/deploy.sh" in mensaje and "no va en .env" in mensaje, mensaje


# --- Backups de la base (F0-20, lane de operacion) ----------------------------
#
# scripts/backup corre `pg_dump` dentro de `db` y escribe en /backups; ese
# directorio es un bind al disco del host (BACKUP_DIR) para que la copia
# sobreviva a un `down -v` y la tome la copia fuera del host.


def test_la_base_de_produccion_escribe_los_backups_en_el_host() -> None:
    db = _servicios_de_produccion()["db"]
    montajes = [_montaje(v) for v in db.get("volumes") or []]  # type: ignore[attr-defined]
    assert ("pg_backups", "/backups") in montajes, montajes
    assert ("postgres_data", "/var/lib/postgresql/data") in montajes, montajes
    volumen = cargar_compose(COMPOSE_PROD.read_text(encoding="utf-8"))["volumes"][
        "pg_backups"
    ]
    assert volumen == {
        "driver": "local",
        "driver_opts": {
            "type": "none",
            "o": "bind",
            "device": "${BACKUP_DIR:-/var/backups/shifty}",
        },
    }, volumen


# --- Produccion nunca construye (revision independiente del lane C) ----------
#
# El VPS corre lo que CI publico: un `build` en la vista de produccion deja que
# un `up` sin `--no-build` construya en el servidor una imagen que nadie
# reviso, con el tag de la version. El borde corre la imagen OFICIAL de nginx
# con la configuracion montada: no depende del release y no se recrea en cada
# deploy (se recarga con `nginx -s reload`).


def test_produccion_no_construye_ninguna_imagen() -> None:
    produccion = _servicios_de_produccion()
    construyen = sorted(n for n, s in produccion.items() if "build" in s)
    assert not construyen, f"en produccion construyen imagen: {construyen}"
    # Desarrollo sigue construyendo: el reset es solo del override.
    base = _services()
    assert {"backend", "frontend", "nginx"} <= {
        n for n, s in base.items() if "build" in s
    }


def test_el_borde_de_produccion_corre_la_imagen_oficial_de_nginx() -> None:
    nginx = _servicios_de_produccion()["nginx"]
    assert nginx.get("image") == "nginx:1.27.5-alpine", nginx.get("image")
    montajes = [str(v) for v in nginx.get("volumes") or []]  # type: ignore[attr-defined]
    assert any(m.endswith(":/etc/nginx/conf.d/default.conf:ro") for m in montajes), (
        montajes
    )


# --- Nombres de contenedor por proyecto (revision independiente del lane C) --
#
# Un nombre fijo (`shifty_db`) choca con un segundo proyecto compose en el
# mismo host (staging, decision 29). El prefijo sale del nombre del proyecto;
# por defecto sigue siendo `shifty`, que es lo que usan los scripts locales.

PREFIJO_DE_PROYECTO = "${COMPOSE_PROJECT_NAME:-shifty}_"

NOMBRES_EN_DESARROLLO = {
    "db": "shifty_db",
    "redis_cache": "shifty_redis_cache",
    "redis_state": "shifty_redis_state",
    "rabbitmq": "shifty_rabbitmq",
    "celery_worker": "shifty_celery",
    "celery_worker_interactive": "shifty_celery_interactive",
    "celery_beat": "shifty_celery_beat",
    "frontend": "shifty_frontend",
    "nginx": "shifty_nginx",
}


def test_los_nombres_de_contenedor_llevan_el_proyecto() -> None:
    nombres = {
        nombre: str(servicio["container_name"])
        for nombre, servicio in _services().items()
        if "container_name" in servicio
    }
    assert set(nombres) == set(NOMBRES_EN_DESARROLLO), sorted(nombres)
    for nombre, valor in nombres.items():
        assert valor.startswith(PREFIJO_DE_PROYECTO), (nombre, valor)
    # Sin COMPOSE_PROJECT_NAME resuelven a los nombres de siempre.
    resueltos = {
        nombre: valor.replace(PREFIJO_DE_PROYECTO, "shifty_")
        for nombre, valor in nombres.items()
    }
    assert resueltos == NOMBRES_EN_DESARROLLO, resueltos


def test_rabbitmq_conserva_su_nodo_al_recrearse() -> None:
    """Sin hostname fijo, el nodo se llama rabbit@<id del contenedor>: un
    contenedor recreado arranca con otro nombre, otro directorio de mnesia
    dentro del volumen y sin las colas ni los mensajes que habia."""
    assert _services()["rabbitmq"].get("hostname") == "rabbitmq"
