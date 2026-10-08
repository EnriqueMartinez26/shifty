"""scripts/deploy.sh: deploy y rollback en el VPS (F0-03, 2026-09-24).

Antes: imagenes sin version construidas en el mismo servidor (sin rollback) y
migraciones que corrian con el codigo nuevo ya arriba (R11-02, R11-03). Se
corre el script REAL con un `docker` falso (tests/unit/host_falso.py) y se
afirma sobre el orden de las llamadas: preflight antes de tocar nada, migrar
con el codigo viejo sirviendo, backend nuevo al lado del viejo, compuerta y
rollback sin migrar.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from tests.unit.host_falso import (
    REPO_ROOT,
    Host,
    _backup_fresco,
    _hay,
    _indice,
    _ultimo_indice,
    crear_host,
    escribir_corridas_de_quality,
    flags_rechazados_por_compose,
)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return crear_host(tmp_path)


def _preparar_deploy(host: Host, actual: str = "v1") -> None:
    (host.repo / ".deploy").mkdir(exist_ok=True)
    (host.repo / ".deploy" / "current").write_text(f"{actual}\n", encoding="utf-8")
    # Las dos replicas de produccion (docker-compose.prod.yml, VPS de 8 GB).
    (host.fake / "backend_ids").write_text(
        "old1\nold2\n", encoding="utf-8", newline="\n"
    )
    _backup_fresco(host)
    # El .env del servidor: compose lo lee del directorio del proyecto.
    (host.repo / ".env").write_text(
        "COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml\n", encoding="utf-8"
    )


_BASE_DEPLOY = {
    "DOMAIN": "shifty.example.com",
    "DEPLOY_GATE_CHECKS": "2",
    "DEPLOY_GATE_INTERVAL": "0",
}


def test_deploy_exige_app_version(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr("deploy.sh", "deploy", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "APP_VERSION" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


@pytest.mark.parametrize(
    ("extra", "motivo"),
    [
        ({"FAKE_COMPOSE_VERSION": "2.23.3"}, "2.24"),
        ({"FAKE_CONFIG_EXIT": "1"}, "config"),
        ({"FAKE_DISK_USE": "85"}, "disco"),
        ({"FAKE_DB_DOWN": "1"}, "db"),
        ({"FAKE_SERVICES": "db backend nginx"}, "celery_worker"),
    ],
    ids=[
        "compose-viejo",
        "config-invalido",
        "disco-lleno",
        "db-caida",
        "servicio-que-falta",
    ],
)
def test_el_preflight_frena_antes_de_tocar_nada(
    host: Host, extra: dict[str, str], motivo: str
) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY, **extra
    )

    assert resultado.returncode != 0
    assert motivo in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


def test_el_preflight_exige_un_backup_de_menos_de_24_horas(host: Host) -> None:
    _preparar_deploy(host)
    _backup_fresco(host, horas=30)

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "backup" in resultado.stderr.lower()
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


def test_el_preflight_sin_registro_de_backup_frena(host: Host) -> None:
    _preparar_deploy(host)
    (host.backups / "last-success").unlink()

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


def test_deploy_migra_con_el_codigo_viejo_sirviendo_y_despues_recrea(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    pull = _indice(
        llamadas, r"compose pull backend .*celery_worker_interactive .*frontend$"
    )
    verifica = _indice(llamadas, r"docker image inspect ghcr.io/x/shifty-backend:v2$")
    migra = _indice(
        llamadas,
        r"compose run --rm --no-deps -T backend alembic upgrade head$",
    )
    backend = _indice(
        llamadas, r"compose up -d --no-deps --no-build .*--scale backend=4 backend"
    )
    # El borde NO se recrea en un deploy normal (solo `make deploy-edge`).
    resto = _indice(
        llamadas,
        r"compose up -d --no-deps --no-build --remove-orphans "
        r"celery_worker celery_worker_interactive celery_beat frontend$",
    )
    reload = _ultimo_indice(llamadas, r"compose exec -T nginx nginx -s reload")
    assert pull < verifica < migra < backend < resto < reload
    assert not _hay(llamadas, r"compose (pull|up) .*\bnginx\b")
    # Rolling: las viejas se bajan despues de que las nuevas estan sanas.
    assert _indice(llamadas, r"docker stop .*old1") > backend
    assert _hay(llamadas, r"docker rm old1 old2$")
    # La compuerta pego contra la ruta real de la API.
    assert _hay(llamadas, r"curl .*https://shifty.example.com/api/ops/health/ready")
    assert (host.repo / ".deploy" / "previous").read_text().strip() == "v1"
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"
    assert not (host.repo / ".deploy" / "lock").exists()


def test_una_migracion_fallida_no_recrea_nada(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", FAKE_MIGRATE_EXIT="1", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert not _hay(host.llamadas(), r"compose up")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    assert not (host.repo / ".deploy" / "lock").exists()


def test_backend_nuevo_que_no_queda_sano_se_descarta_y_quedan_los_viejos(
    host: Host,
) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_UP_BACKEND_EXIT="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    llamadas = host.llamadas()
    assert _hay(llamadas, r"docker rm -f .*new4-v2")
    assert not _hay(llamadas, r"docker stop .*old1")
    assert not _hay(llamadas, r"compose up -d --no-deps celery_worker ")
    ids = (host.fake / "backend_ids").read_text().split()
    assert ids == ["old1", "old2"]


def test_compuerta_fallida_vuelve_a_la_version_anterior_sin_migrar(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", FAKE_CURL_EXIT="22", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "rollback" in resultado.stderr.lower()
    llamadas = host.llamadas()
    assert sum(bool(re.search(r"alembic upgrade", ll)) for ll in llamadas) == 1
    # Segunda ronda de backend con la version anterior.
    assert _hay(llamadas, r"compose up .*--scale backend=\d+ backend")
    ids = (host.fake / "backend_ids").read_text().split()
    assert ids and all(i.endswith("-v1") for i in ids), ids
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_compuerta_con_5xx_sobre_el_umbral_hace_rollback(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    lineas = ['{"m":"GET","u":"/x","s":200,"rt":"0.010"}'] * 100
    lineas += ['{"m":"GET","u":"/x","s":502,"rt":"0.010"}'] * 3
    (host.fake / "nginx.log").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "5xx" in resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_pocos_5xx_con_poco_trafico_no_disparan_rollback(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    lineas = ['{"m":"GET","u":"/x","s":200,"rt":"0.010"}'] * 50
    lineas += ['{"m":"GET","u":"/x","s":"502","rt":"0.010"}']
    (host.fake / "nginx.log").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr


def test_un_contenedor_unhealthy_hace_fallar_la_compuerta(host: Host) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_HEALTH="unhealthy",
        FAKE_UP_BACKEND_EXIT="0",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "unhealthy" in resultado.stderr


def test_rollback_usa_la_version_previa_y_nunca_migra(host: Host) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "rollback", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    assert not _hay(llamadas, r"alembic")
    assert _hay(llamadas, r"compose up .*--scale backend=4 backend")
    assert _hay(llamadas, r"compose exec -T nginx nginx -s reload")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_rollback_sin_version_previa_falla_claro(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr("deploy.sh", "rollback", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "previous" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up")


def test_un_deploy_en_curso_frena_otro(host: Host) -> None:
    _preparar_deploy(host)
    (host.repo / ".deploy" / "lock").mkdir()

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "lock" in resultado.stderr
    assert (host.repo / ".deploy" / "lock").exists(), "borro el lock de otro deploy"


def test_rollback_funciona_aunque_compose_exija_app_version(host: Host) -> None:
    """docker-compose.prod.yml usa ${APP_VERSION:?}: el preflight del rollback
    corre `compose config` y tiene que tener ya la version anterior."""
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")

    resultado = host.correr(
        "deploy.sh", "rollback", FAKE_EXIGE_VERSION="1", **_BASE_DEPLOY
    )

    assert resultado.returncode == 0, resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_deploy_sin_app_version_no_toma_la_que_corre(host: Host) -> None:
    """La version en curso (.deploy/current) sirve a los crons, nunca para
    que un `make deploy` sin APP_VERSION redespliegue en silencio."""
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh", "deploy", FAKE_EXIGE_VERSION="1", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "APP_VERSION" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


# --- revision 2026-09-24: cwd, COMPOSE_FILE, nunca construir, borde aparte ----


def test_deploy_habla_con_compose_desde_el_clon_aunque_se_llame_de_otro_lado(
    host: Host,
) -> None:
    """Compose toma el proyecto, el .env y COMPOSE_FILE del directorio actual:
    corrido desde otro lado hablaria con otro proyecto (o con ninguno)."""
    _preparar_deploy(host, actual="v1")
    otro = host.raiz / "otro-directorio"
    otro.mkdir()

    resultado = host.correr_desde(
        otro, "deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY
    )

    assert resultado.returncode == 0, resultado.stderr
    cwd = (host.fake / "cwd").read_text(encoding="utf-8").strip()
    assert Path(cwd).resolve() == host.repo.resolve()


@pytest.mark.parametrize(
    "contenido",
    ["", "COMPOSE_FILE=docker-compose.yml\n"],
    ids=["sin-compose-file", "sin-override-de-prod"],
)
def test_el_preflight_exige_el_compose_de_produccion(
    host: Host, contenido: str
) -> None:
    """Sin docker-compose.prod.yml el deploy levantaria el compose de
    desarrollo: puertos publicados, entorno de dev, imagenes `:dev`."""
    _preparar_deploy(host)
    (host.repo / ".env").write_text(contenido, encoding="utf-8")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "docker-compose.prod.yml" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


def test_compose_file_del_entorno_le_gana_al_env(host: Host) -> None:
    _preparar_deploy(host)
    (host.repo / ".env").write_text("", encoding="utf-8")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        COMPOSE_FILE="docker-compose.yml:docker-compose.prod.yml",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr


def test_ningun_up_ni_run_construye_imagenes(host: Host) -> None:
    """El VPS nunca construye: sin --no-build, una imagen que falta se
    construiria desde el arbol del clon y correria codigo sin version. `run`
    no tiene --no-build (2026-10-02): no lleva --build y lo que le impide
    construir es la vista de produccion sin `build`
    (test_compose_contract::test_produccion_no_construye_ninguna_imagen)."""
    _preparar_deploy(host, actual="v1")

    host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", FAKE_CURL_EXIT="22", **_BASE_DEPLOY
    )

    llamadas = [ll for ll in host.llamadas() if re.search(r"compose (up|run) ", ll)]
    assert llamadas
    for llamada in llamadas:
        if " run " in llamada:
            assert "--build" not in llamada.split(), llamada
            continue
        assert "--no-build" in llamada, llamada
        # `redis` paso a `redis_cache`/`redis_state`: sin esto el contenedor
        # viejo sigue vivo y retiene el 6379.
        if " up " in llamada:
            assert "--remove-orphans" in llamada, llamada


def test_pull_fallido_frena_el_deploy_antes_de_migrar(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", FAKE_PULL_EXIT="1", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "pull" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (run|up)")


def test_una_imagen_que_no_quedo_local_frena_el_deploy(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", FAKE_MISSING_TAG="v2", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "ghcr.io/x/shifty-backend:v2" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (run|up)")


def test_rollback_con_pull_fallido_usa_las_imagenes_locales_si_estan(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "rollback", FAKE_PULL_EXIT="1", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_rollback_sin_la_imagen_previa_falla_con_alerta_y_no_toca_nada(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")

    resultado = host.correr(
        "deploy.sh",
        "rollback",
        FAKE_PULL_EXIT="1",
        FAKE_MISSING_TAG="v1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 2
    assert "ALERTA" in resultado.stderr
    assert "shifty-backend:v1" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"


# --- make deploy-edge: el borde se recrea solo si cambio --------------------


def _preparar_borde(host: Host, conf: str = "server {}\n") -> Path:
    _preparar_deploy(host, actual="v2")
    (host.repo / "nginx").mkdir()
    archivo = host.repo / "nginx" / "nginx.prod.conf"
    archivo.write_text(conf, encoding="utf-8")
    return archivo


def test_deploy_edge_sin_cambios_solo_recarga(host: Host) -> None:
    _preparar_borde(host)
    primero = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    assert primero.returncode == 0, primero.stderr
    (host.fake / "calls").unlink()

    resultado = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    assert not _hay(llamadas, r"--force-recreate")
    assert _hay(llamadas, r"compose exec -T nginx nginx -t")
    assert _hay(llamadas, r"compose exec -T nginx nginx -s reload")


def test_deploy_edge_recrea_si_cambio_la_config(host: Host) -> None:
    archivo = _preparar_borde(host)
    host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    archivo.write_text("server { listen 443; }\n", encoding="utf-8")
    (host.fake / "calls").unlink()

    resultado = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert _hay(
        host.llamadas(),
        r"compose up -d --no-deps --no-build --remove-orphans --force-recreate .*nginx$",
    )


def test_deploy_edge_recrea_si_cambio_la_imagen(host: Host) -> None:
    _preparar_borde(host)
    host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    (host.fake / "calls").unlink()

    resultado = host.correr(
        "deploy.sh", "edge", FAKE_IMAGE_ID="sha256:nueva", **_BASE_DEPLOY
    )

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    assert _hay(llamadas, r"compose pull nginx")
    assert _hay(llamadas, r"--force-recreate .*nginx$")


# --- ronda final: BACKUP_DIR, huerfanos y alarmas de RabbitMQ -----------------


def test_el_preflight_crea_backup_dir_si_falta(host: Host) -> None:
    """El volumen pg_backups es un bind: si el directorio del host no existe,
    `db` no arranca. El preflight lo crea (0750) antes de tocar nada."""
    _preparar_deploy(host, actual="v1")
    faltante = host.raiz / "no-existe" / "backups"

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        BACKUP_DIR=faltante.as_posix(),
        DEPLOY_SKIP_BACKUP_CHECK="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert faltante.is_dir()


def test_una_alarma_de_rabbitmq_hace_fallar_la_compuerta(host: Host) -> None:
    """Con la alarma de memoria activa RabbitMQ BLOQUEA a los publicadores:
    un deploy que la dispara no es sano aunque /ready conteste."""
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_RABBIT_ALARMS='[{"type":"resource_alarm","resource":"memory"}]',
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "alarm" in resultado.stderr
    assert _hay(host.llamadas(), r"compose exec -T rabbitmq rabbitmq-diagnostics")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


# 2026-10-08, primer deploy real: RabbitMQ 3.13.7 contesta
# `rabbitmq-diagnostics -q alarms --formatter json` con un OBJETO, no con una
# lista. La compuerta solo aceptaba vacio o `[]` y fallo con
# "rabbitmq tiene alarmas activas: {"alarms":[],"node":"rabbit@rabbitmq",
# "result":"ok"}": todo deploy terminaba en rollback.
#
# Las dos formas que imprime 3.13.7 salen de
# deps/rabbitmq_cli/lib/rabbitmq/cli/diagnostics/commands/alarms_command.ex
# (tag v3.13.7): sin alarmas, `{"alarms":[],"node":...,"result":"ok"}`; CON
# alarmas, otro objeto SIN clave `alarms` (`local`, `global`, `message`) y
# `result` igual a "ok", con exit 0. Nunca imprime vacio ni `[]` con
# `--formatter json`: esas dos salidas ya no cuentan como "sin alarmas".
_SIN_ALARMAS_3_13 = '{"alarms":[],"node":"rabbit@rabbitmq","result":"ok"}'
_ALARMA_DE_MEMORIA_3_13 = (
    '{"global":[],"local":["Memory alarm on node rabbit@rabbitmq"],'
    '"message":"Node rabbit@rabbitmq reported alarms","result":"ok"}'
)


@pytest.mark.parametrize(
    "salida",
    [
        _SIN_ALARMAS_3_13,
        '{\n  "alarms": [ ],\n  "node": "rabbit@rabbitmq",\n  "result": "ok"\n}',
        '{"result":"ok","alarms":[],"node":"rabbit@rabbitmq"}',
    ],
    ids=["objeto-3.13", "objeto-indentado", "otro-orden"],
)
def test_rabbitmq_sin_alarmas_pasa_la_compuerta(host: Host, salida: str) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_RABBIT_ALARMS=salida,
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "alarmas activas" not in resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"


@pytest.mark.parametrize(
    "salida",
    [
        _ALARMA_DE_MEMORIA_3_13,
        (
            '{"global":["Free disk space alarm on node rabbit@otro"],"local":[],'
            '"message":"Node rabbit@rabbitmq reported alarms","result":"ok"}'
        ),
        # `alarms` vacia no alcanza: cualquier clave fuera de alarms, node y
        # result (aca `global`) es una forma que la compuerta no conoce.
        '{"alarms":[],"global":["Memory alarm on node rabbit@otro"],"result":"ok"}',
        '{"alarms":[],"node":"rabbit@rabbitmq","result":"ok","local":[]}',
        '{"alarms":[{"resource":"memory"}],"node":"rabbit@rabbitmq","result":"ok"}',
        '[{"type":"resource_alarm","resource":"disk"}]',
        # Dos claves `alarms` (una vacia): no se adivina cual vale.
        '{"alarms":[],"alarms":[{"resource":"memory"}],"result":"ok"}',
        '{"alarms":[],"alarms":[],"node":"rabbit@rabbitmq","result":"ok"}',
        '{"node":"rabbit@rabbitmq","result":"ok"}',
        '{"alarms":[],"node":"rabbit@rabbitmq","result":"error"}',
        "[]",
        "",
        "Error: unable to perform an operation on node 'rabbit@rabbitmq'",
        'basura {"alarms":[]} basura',
    ],
    ids=[
        "real-3.13-alarma-local",
        "real-3.13-alarma-global",
        "alarms-vacia-y-global",
        "alarms-vacia-y-local",
        "alarms-con-alarma",
        "lista-con-alarma",
        "alarms-duplicada",
        "alarms-vacia-duplicada",
        "sin-clave-alarms",
        "result-error",
        "lista-vacia",
        "vacio",
        "texto",
        "basura-alrededor",
    ],
)
def test_rabbitmq_con_alarmas_o_ilegible_hace_fallar_la_compuerta(
    host: Host, salida: str
) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_RABBIT_ALARMS=salida,
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "rabbitmq tiene alarmas activas" in resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_la_compuerta_conoce_la_version_de_rabbitmq_que_corre() -> None:
    """rabbitmq_sin_alarmas solo entiende el JSON de 3.13.7. Subir la imagen
    obliga a releer alarms_command.ex del tag nuevo y ajustar la compuerta:
    con otra forma, todo deploy fallaria (cerrado, pero fallaria)."""
    for archivo in ("docker-compose.yml", "docker-compose.prod.yml"):
        texto = (REPO_ROOT / archivo).read_text(encoding="utf-8")
        tags = re.findall(r"^\s*image:\s*rabbitmq:(\S+)", texto, re.MULTILINE)
        assert tags, archivo
        for tag in tags:
            assert tag.startswith("3.13.7-"), f"{archivo}: rabbitmq:{tag}"


# --- flags de compose (2026-10-02) ------------------------------------------
#
# `migrar` corria `compose run --rm --no-deps --no-build ...`: `run` no tiene
# `--no-build` en ninguna version (Compose 5.5.1: "unknown flag: --no-build"),
# asi que el primer deploy real moria al migrar. El `docker` falso validaba
# nada y el test afirmaba ese string. host_falso valida ahora cada llamada a
# compose contra los flags de Compose 2.24 (la minima de DEPLOY_MIN_COMPOSE).


@pytest.mark.parametrize(
    ("argumentos", "rechazados"),
    [
        (
            "run --rm --no-deps --no-build -T backend alembic upgrade head",
            ["run --no-build"],
        ),
        # `--pull` de `run` existe recien desde Compose 2.33.0.
        ("run --rm --pull never -T backend alembic upgrade head", ["run --pull"]),
        ("run --rm --no-deps -T backend alembic upgrade head --no-build", []),
        (
            "up -d --no-deps --no-build --remove-orphans --wait --wait-timeout 180 --scale backend=6 backend",
            [],
        ),
        ("exec -T db sh -c --no-build", []),
        ("logs --no-log-prefix --since 2m nginx", []),
        ("config --images backend frontend", []),
        ("up -d --sin-esto backend", ["up --sin-esto"]),
        ("ps -qz", ["ps -z"]),
    ],
)
def test_el_docker_falso_rechaza_flags_que_compose_2_24_no_entiende(
    argumentos: str, rechazados: list[str]
) -> None:
    assert flags_rechazados_por_compose(argumentos.split()) == rechazados


def test_la_migracion_no_pasa_flags_que_compose_run_rechaza(host: Host) -> None:
    """Sin el validador, este deploy pasaba con el `docker` falso y moria en el
    VPS: `docker compose run` no entiende `--no-build`."""
    _preparar_deploy(host, actual="v1")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    migra = [ll for ll in host.llamadas() if "alembic upgrade head" in ll]
    assert migra == [
        "docker compose run --rm --no-deps -T backend alembic upgrade head"
    ], migra


# --- Quality verde para la version (2026-10-03) ------------------------------
#
# build-images.yml publica solo despues de un Quality verde en main, pero
# `workflow_dispatch` reconstruye a mano cualquier rama sin esa compuerta. El
# preflight le vuelve a preguntar a GitHub si Quality paso en main para ESE sha
# antes de migrar.

SHA = "0123456789abcdef0123456789abcdef01234567"


def _consultas_a_github(host: Host) -> list[str]:
    # Llamadas de curl a la API de GitHub (el host esta anclado: CodeQL marca
    # un `"api.github.com" in url` como saneamiento de URL incompleto).
    return [
        ll
        for ll in host.llamadas()
        if re.search(r"^curl .*https://api\.github\.com/", ll)
    ]


def test_deploy_pregunta_si_quality_paso_en_main_para_ese_sha(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    consultas = _consultas_a_github(host)
    assert len(consultas) == 1, consultas
    url = consultas[0]
    assert (
        "https://api.github.com/repos/EnriqueMartinez26/shifty/actions/workflows/quality.yml/runs?"
        in url
    )
    for parametro in (
        f"head_sha={SHA}",
        "branch=main",
        "event=push",
        "status=success",
    ):
        assert parametro in url, parametro
    llamadas = host.llamadas()
    assert _indice(llamadas, r"api\.github\.com") < _indice(llamadas, r"compose pull")


@pytest.mark.parametrize(
    ("extra", "verdes", "motivo"),
    [
        ({}, 0, "Quality no paso en main"),
        ({"FAKE_GH_EXIT": "22"}, 1, "no pude preguntarle a GitHub"),
    ],
    ids=["sin-quality-verde", "github-no-responde"],
)
def test_deploy_frena_sin_un_quality_verde_antes_de_tocar_nada(
    host: Host, extra: dict[str, str], verdes: int, motivo: str
) -> None:
    _preparar_deploy(host)
    escribir_corridas_de_quality(host.fake / "gh_runs", verdes=verdes)

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY, **extra
    )

    assert resultado.returncode != 0
    assert motivo in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_una_respuesta_de_github_ilegible_frena(host: Host) -> None:
    _preparar_deploy(host)
    (host.fake / "gh_runs").write_text('{"message": "API rate limit exceeded"}\n')

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "respuesta inesperada de GitHub" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


def test_una_version_con_caracteres_raros_no_llega_a_la_url(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION=f"{SHA}&branch=x", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "APP_VERSION" in resultado.stderr
    assert not _consultas_a_github(host)
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


def test_saltear_la_verificacion_de_quality_avisa(host: Host) -> None:
    """Para staging con una imagen de rama (workflow_dispatch): se puede, pero
    queda una alerta."""
    _preparar_deploy(host)
    escribir_corridas_de_quality(host.fake / "gh_runs", verdes=0)

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION=SHA,
        DEPLOY_SKIP_QUALITY_CHECK="1",
        ALERT_WEBHOOK_URL="https://hook",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert not _consultas_a_github(host)
    assert "ALERTA: deploy: " in resultado.stderr
    assert "SIN verificar Quality" in resultado.stderr


def test_rollback_no_le_pregunta_a_github(host: Host) -> None:
    """El rollback es el camino de emergencia: con GitHub caido tiene que
    poder volver a la version anterior."""
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "rollback", FAKE_GH_EXIT="22", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert not _consultas_a_github(host)


# --- repo privado (2026-10-08) -----------------------------------------------
#
# El repo paso a privado y la API de GitHub contesta 404 sin token: el primer
# deploy real solo salio con DEPLOY_SKIP_QUALITY_CHECK=1, que avisa "Solo para
# staging". DEPLOY_GITHUB_TOKEN (opcional, en /etc/shifty/ops.env) viaja como
# `Authorization: Bearer` por stdin (`curl -K -`): nunca en argv, que cualquier
# usuario del host ve en `ps`.

TOKEN = "github_pat_11ABCDEFG0123456789_abcdefXYZ"


def test_con_token_la_consulta_a_github_va_autenticada_sin_token_en_argv(
    host: Host,
) -> None:
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION=SHA,
        DEPLOY_GITHUB_TOKEN=TOKEN,
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    consultas = _consultas_a_github(host)
    assert len(consultas) == 1, consultas
    configuracion = (host.fake / "curl_config").read_text(encoding="utf-8")
    assert f'header = "Authorization: Bearer {TOKEN}"' in configuracion
    assert TOKEN not in "\n".join(host.llamadas())
    assert TOKEN not in resultado.stderr
    assert TOKEN not in resultado.stdout


def test_el_token_de_github_se_toma_de_ops_env(host: Host) -> None:
    _preparar_deploy(host)
    ops_env = host.raiz / "ops.env"
    ops_env.write_text(f"DEPLOY_GITHUB_TOKEN={TOKEN}\n", encoding="utf-8")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION=SHA,
        SHIFTY_OPS_ENV=ops_env.as_posix(),
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    configuracion = (host.fake / "curl_config").read_text(encoding="utf-8")
    assert f"Authorization: Bearer {TOKEN}" in configuracion
    assert TOKEN not in "\n".join(host.llamadas())


def test_sin_token_la_consulta_a_github_sigue_anonima(host: Host) -> None:
    _preparar_deploy(host)

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    consultas = _consultas_a_github(host)
    assert len(consultas) == 1, consultas
    assert " -K " not in consultas[0]
    assert "Authorization" not in "\n".join(host.llamadas())
    assert not (host.fake / "curl_config").exists()


@pytest.mark.parametrize(
    "token",
    [f'{TOKEN}"\nurl = "https://evil.example', f"{TOKEN} x", f"{TOKEN}\\"],
    ids=["comillas-y-salto", "espacio", "barra"],
)
def test_un_token_con_caracteres_raros_frena_sin_mostrarlo(
    host: Host, token: str
) -> None:
    """El token va dentro de una linea de configuracion de curl: un caracter
    fuera de [A-Za-z0-9_] podria inyectar otras opciones."""
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION=SHA,
        DEPLOY_GITHUB_TOKEN=token,
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "DEPLOY_GITHUB_TOKEN" in resultado.stderr
    assert TOKEN not in resultado.stderr
    assert not _consultas_a_github(host)
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


# --- ops.env ilegible (2026-10-08) -------------------------------------------
#
# deploy.sh corre como `deploy`; el runbook decia /etc/shifty/ops.env root 600.
# common.sh lo salteaba EN SILENCIO (`[ -r ]`) y el deploy seguia sin DOMAIN,
# sin alertas y sin token. Un ops.env que existe y no se puede leer avisa.


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="Windows y root leen un archivo en modo 000",
)
def test_un_ops_env_ilegible_avisa_en_vez_de_saltearse_en_silencio(
    host: Host,
) -> None:
    _preparar_deploy(host)
    ops_env = host.raiz / "ops.env"
    ops_env.write_text("DOMAIN=shifty.example.com\n", encoding="utf-8")
    ops_env.chmod(0)
    try:
        resultado = host.correr(
            "deploy.sh",
            "preflight",
            APP_VERSION=SHA,
            SHIFTY_OPS_ENV=ops_env.as_posix(),
            **_BASE_DEPLOY,
        )
    finally:
        ops_env.chmod(0o600)

    assert f"{ops_env.as_posix()} existe pero no se puede leer" in resultado.stderr


def test_sin_ops_env_no_hay_aviso(host: Host) -> None:
    """El aviso es para un archivo ilegible, no para uno que no existe (el
    staging o un host sin ops.env siguen con sus defaults)."""
    _preparar_deploy(host)

    resultado = host.correr("deploy.sh", "preflight", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert "no se puede leer" not in resultado.stderr


# --- revision del PR #135 (2026-10-08) ---------------------------------------


def test_github_que_rechaza_el_token_frena_sin_mostrarlo(host: Host) -> None:
    """Token vencido o sin "Actions: read": curl -f sale con 22. Falla cerrada
    con un mensaje que apunta al token, sin imprimirlo."""
    _preparar_deploy(host)

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION=SHA,
        DEPLOY_GITHUB_TOKEN=TOKEN,
        FAKE_GH_EXIT="22",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "no pude preguntarle a GitHub" in resultado.stderr
    assert "DEPLOY_GITHUB_TOKEN" in resultado.stderr
    assert TOKEN not in resultado.stderr
    assert TOKEN not in resultado.stdout
    assert TOKEN not in "\n".join(host.llamadas())
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


@pytest.mark.parametrize("origen", ["entorno", "ops.env"])
def test_el_token_de_github_no_llega_a_docker(host: Host, origen: str) -> None:
    """common.sh carga ops.env con `set -a`: sin `export -n`, el token viajaba
    en el entorno de cada `docker compose` (y de lo que este lance)."""
    _preparar_deploy(host)
    extra = {"DEPLOY_GITHUB_TOKEN": TOKEN}
    if origen == "ops.env":
        ops_env = host.raiz / "ops.env"
        ops_env.write_text(f"DEPLOY_GITHUB_TOKEN={TOKEN}\n", encoding="utf-8")
        extra = {"SHIFTY_OPS_ENV": ops_env.as_posix()}

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY, **extra
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _hay(host.llamadas(), r"compose pull")
    assert "Authorization: Bearer" in (host.fake / "curl_config").read_text(
        encoding="utf-8"
    )
    assert not (host.fake / "docker_ve_el_token").exists(), (
        host.fake / "docker_ve_el_token"
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="Windows y root entran a un directorio en modo 000",
)
def test_un_directorio_de_ops_env_sin_permiso_avisa(host: Host) -> None:
    """Con /etc/shifty root 0700 (el runbook viejo) el usuario deploy ni
    siquiera ve si ops.env existe: `[ -e ]` da falso y el aviso del archivo
    ilegible no salia."""
    _preparar_deploy(host)
    directorio = host.raiz / "etc-shifty"
    directorio.mkdir()
    ops_env = directorio / "ops.env"
    ops_env.write_text("DOMAIN=shifty.example.com\n", encoding="utf-8")
    directorio.chmod(0)
    try:
        resultado = host.correr(
            "deploy.sh",
            "preflight",
            APP_VERSION=SHA,
            SHIFTY_OPS_ENV=ops_env.as_posix(),
            **_BASE_DEPLOY,
        )
    finally:
        directorio.chmod(0o755)

    assert f"no puedo entrar a {directorio.as_posix()}" in resultado.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="Windows no tiene bits de grupo")
def test_el_preflight_crea_backup_dir_legible_para_el_grupo(host: Host) -> None:
    """deploy.sh corre como `deploy` y el runbook pide root:deploy 0750: el
    directorio que crea el propio script queda igual (antes, 0700)."""
    _preparar_deploy(host, actual="v1")
    faltante = host.raiz / "no-existe" / "backups"

    resultado = host.correr(
        "deploy.sh",
        "preflight",
        APP_VERSION=SHA,
        BACKUP_DIR=faltante.as_posix(),
        DEPLOY_SKIP_BACKUP_CHECK="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert faltante.stat().st_mode & 0o777 == 0o750


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="Windows y root escriben en un directorio de solo lectura",
)
def test_backup_dir_que_no_se_puede_crear_sugiere_root_deploy_0750(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    padre = host.raiz / "solo-lectura"
    padre.mkdir()
    padre.chmod(0o555)
    try:
        resultado = host.correr(
            "deploy.sh",
            "preflight",
            APP_VERSION=SHA,
            BACKUP_DIR=(padre / "backups").as_posix(),
            **_BASE_DEPLOY,
        )
    finally:
        padre.chmod(0o755)

    assert resultado.returncode != 0
    assert "install -d -o root -g deploy -m 0750" in resultado.stderr
