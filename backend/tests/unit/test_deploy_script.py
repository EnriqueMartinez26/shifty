"""scripts/deploy.sh: deploy y rollback en el VPS (F0-03, 2026-09-24).

Antes: imagenes sin version construidas en el mismo servidor (sin rollback) y
migraciones que corrian con el codigo nuevo ya arriba (R11-02, R11-03). Se
corre el script REAL con un `docker` falso (tests/unit/host_falso.py) y se
afirma sobre el orden de las llamadas: preflight antes de tocar nada, migrar
con el codigo viejo sirviendo, backend nuevo al lado del viejo, compuerta y
rollback sin migrar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.host_falso import (
    Host,
    _backup_fresco,
    _hay,
    _indice,
    _ultimo_indice,
    crear_host,
)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return crear_host(tmp_path)


def _preparar_deploy(host: Host, actual: str = "v1") -> None:
    (host.repo / ".deploy").mkdir(exist_ok=True)
    (host.repo / ".deploy" / "current").write_text(f"{actual}\n", encoding="utf-8")
    (host.fake / "backend_ids").write_text(
        "old1\nold2\nold3\n", encoding="utf-8", newline="\n"
    )
    _backup_fresco(host)


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
        llamadas, r"compose pull .*backend.*celery_worker_interactive.*nginx"
    )
    migra = _indice(
        llamadas, r"compose run --rm --no-deps -T backend alembic upgrade head"
    )
    backend = _indice(llamadas, r"compose up -d --no-deps .*--scale backend=6 backend")
    resto = _indice(llamadas, r"compose up -d --no-deps celery_worker ")
    reload = _ultimo_indice(llamadas, r"compose exec -T nginx nginx -s reload")
    assert pull < migra < backend < resto < reload
    # Rolling: las viejas se bajan despues de que las nuevas estan sanas.
    assert _indice(llamadas, r"docker stop .*old1") > backend
    assert _hay(llamadas, r"docker rm .*old1 old2 old3")
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
    assert ids == ["old1", "old2", "old3"]


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
    assert _hay(llamadas, r"compose up .*--scale backend=6 backend")
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
