"""scripts/deploy.sh: deploy y rollback en el VPS (F0-03, 2026-09-24).

Antes: imagenes sin version construidas en el mismo servidor (sin rollback) y
migraciones que corrian con el codigo nuevo ya arriba (R11-02, R11-03). Se
corre el script REAL con un `docker` falso (tests/unit/host_falso.py) y se
afirma sobre el orden de las llamadas: preflight antes de tocar nada, migrar
con el codigo viejo sirviendo, backend nuevo al lado del viejo, compuerta y
rollback sin migrar.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import subprocess
from pathlib import Path

import pytest

from tests.unit.host_falso import (
    REPO_ROOT,
    BASH,
    Host,
    _backup_fresco,
    _hay,
    _indice,
    _ultimo_indice,
    corrida_de_quality,
    crear_host,
    escribir_corridas_de_quality,
    flags_rechazados_por_compose,
)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return crear_host(tmp_path)


def _sembrar_borde(host: Host, conf: str = "server {}\n") -> Path:
    (host.repo / "nginx").mkdir(exist_ok=True)
    archivo = host.repo / "nginx" / "nginx.prod.conf"
    archivo.write_text(conf, encoding="utf-8", newline="\n")
    (host.repo / ".deploy").mkdir(exist_ok=True)
    huella = hashlib.sha256(
        f"{conf}\nasset-store={host.env['DEPLOY_ASSET_STORE']}\n".encode("utf-8")
    ).hexdigest()
    (host.repo / ".deploy" / "edge-conf.sha256").write_text(
        f"{huella}\n", encoding="utf-8", newline="\n"
    )
    return archivo


def _preparar_deploy(host: Host, actual: str = "v1") -> None:
    (host.repo / ".deploy").mkdir(exist_ok=True)
    (host.repo / ".deploy" / "current").write_text(f"{actual}\n", encoding="utf-8")
    # Las dos replicas de produccion (docker-compose.prod.yml, VPS de 8 GB).
    (host.fake / "backend_ids").write_text(
        "old1\nold2\n", encoding="utf-8", newline="\n"
    )
    # La SPA corre una sola replica.
    (host.fake / "frontend_ids").write_text(
        "front-old1\n", encoding="utf-8", newline="\n"
    )
    host.env["FAKE_RUNNING_VERSION"] = actual
    _backup_fresco(host)
    _sembrar_borde(host)
    # El .env del servidor: compose lo lee del directorio del proyecto.
    (host.repo / ".env").write_text(
        "COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml\n", encoding="utf-8"
    )


def _assets_falsos(host: Host, release: str, shared: str = "shared") -> Path:
    root = Path(host.env["FAKE_ASSET_FIXTURES"]) / release
    root.mkdir(parents=True, exist_ok=True)
    (root / f"chunk-{release}.js").write_text(
        f"window.release = '{release}';\n", encoding="utf-8", newline="\n"
    )
    (root / "shared.js").write_text(shared + "\n", encoding="utf-8", newline="\n")
    return root


def _importar_assets(host: Host, release: str) -> None:
    image_id = "sha256:" + hashlib.sha256(release.encode()).hexdigest()
    fixture_root = Path(host.env["FAKE_ASSET_FIXTURES"])
    source = fixture_root / release
    if not source.is_dir():
        source = fixture_root / "default"
    assert BASH is not None
    resultado = subprocess.run(
        [
            BASH,
            str(REPO_ROOT / "scripts" / "release-assets.sh"),
            "import",
            host.env["DEPLOY_ASSET_STORE"],
            release,
            image_id,
            source.as_posix(),
        ],
        cwd=host.repo,
        env=host.env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr


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


def test_preflight_rechaza_asset_store_dentro_del_checkout(host: Host) -> None:
    dentro = host.repo / "var" / "assets"

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        DEPLOY_ASSET_STORE=dentro.as_posix(),
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "fuera del checkout" in resultado.stderr
    assert not dentro.exists()
    assert not host.llamadas()
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
    frontend = _indice(
        llamadas, r"compose up -d --no-deps --no-build .*--scale frontend=2 frontend$"
    )
    resto = _indice(
        llamadas,
        r"compose up -d --no-deps --no-build --remove-orphans "
        r"celery_worker celery_worker_interactive celery_beat$",
    )
    reload = _ultimo_indice(llamadas, r"compose exec -T nginx nginx -s reload")
    assert pull < verifica < migra < backend < frontend < resto < reload
    assert not _hay(llamadas, r"compose pull nginx")
    assert not _hay(llamadas, r"compose up .*nginx$")
    assert _indice(llamadas, r"docker cp .*assets/\.") < migra
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
    assert not _hay(host.llamadas(), r"compose up .*--scale (backend|frontend)=")
    assert not _hay(host.llamadas(), r"compose up .*nginx$")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    assert not (host.repo / ".deploy" / "lock").exists()


def test_importa_current_rollback_y_candidate_antes_de_migrar(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    # The live frontend can lag the app marker during an earlier partial rollout.
    host.env["FAKE_RUNNING_VERSION"] = "v0"
    (host.repo / ".deploy" / "previous").write_text("v0\n", encoding="utf-8")
    _assets_falsos(host, "v0")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert {
        "v0.manifest",
        "v1.manifest",
        "v2.manifest",
    } <= {p.name for p in (store / ".manifests").glob("*.manifest")}
    llamadas = host.llamadas()
    extracciones = [i for i, line in enumerate(llamadas) if "docker cp " in line]
    migra = _indice(
        llamadas, r"compose run --rm --no-deps -T backend alembic upgrade head$"
    )
    frontend = _indice(llamadas, r"compose up .*--scale frontend=2 frontend$")
    assert len(extracciones) == 3, llamadas
    assert not _hay(llamadas, r"compose up .*nginx$")
    assert max(extracciones) < migra < frontend


def test_primer_deploy_en_host_vacio_importa_candidate_sin_front_activo(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    (host.repo / ".deploy" / "current").unlink()
    (host.repo / ".deploy" / "previous").unlink(missing_ok=True)
    (host.fake / "frontend_ids").write_text("", encoding="utf-8")
    (host.fake / "backend_ids").write_text("", encoding="utf-8")
    _assets_falsos(host, "v2")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert (store / ".manifests" / "v2.manifest").is_file()
    llamadas = host.llamadas()
    estimate = _indice(llamadas, r"docker run .*du -sk /usr/share/nginx/html/assets")
    create = _indice(llamadas, r"docker create --name shifty-assets-v2")
    copy = _indice(llamadas, r"docker cp .*assets/\.")
    migrate = _indice(
        llamadas,
        r"compose run --rm --no-deps -T backend alembic upgrade head$",
    )
    assert not _hay(llamadas, r"compose up .*nginx$")
    assert estimate < create < copy < migrate
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"


def test_host_con_current_registrado_sin_front_falla_cerrado(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    (host.fake / "frontend_ids").write_text("", encoding="utf-8")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "release registrado" in resultado.stderr
    assert not _hay(host.llamadas(), r"docker run .*du -sk")
    assert not _hay(host.llamadas(), r"docker (create|cp) ")
    assert not _hay(host.llamadas(), r"compose (run|up)")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_importa_cada_imagen_frontend_activa_si_hay_replicas_mixtas(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    # Simulate an interrupted older rollout: the app marker points to the
    # rollback target v0 while both v1 and v3 frontend replicas are serving.
    (host.repo / ".deploy" / "current").write_text("v0\n", encoding="utf-8")
    (host.fake / "frontend_ids").write_text(
        "front-old1\nfront-new3-v3\n", encoding="utf-8", newline="\n"
    )
    for release in ("v0", "v1", "v2", "v3"):
        _assets_falsos(host, release)

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert {
        "v0.manifest",
        "v1.manifest",
        "v2.manifest",
        "v3.manifest",
    } <= {p.name for p in (store / ".manifests").glob("*.manifest")}
    llamadas = host.llamadas()
    extracciones = [i for i, line in enumerate(llamadas) if "docker cp " in line]
    assert len(extracciones) == 4, llamadas
    assert max(extracciones) < _indice(
        llamadas, r"compose run --rm --no-deps -T backend alembic upgrade head$"
    )


def test_falla_capacity_antes_de_migrar_o_recrear_aplicacion(host: Host) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_ASSET_AVAILABLE_KB="0",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "espacio insuficiente" in resultado.stderr
    llamadas = host.llamadas()
    assert _hay(llamadas, r"docker run .*du -sk /usr/share/nginx/html/assets")
    assert not _hay(llamadas, r"docker (create|cp) ")
    assert not _hay(host.llamadas(), r"compose (run|up) .*--scale")
    assert not _hay(host.llamadas(), r"compose up .*--force-recreate .*nginx$")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    assert not (host.repo / ".deploy" / "previous").exists()
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert not list((store / ".manifests").glob("*.manifest"))
    assert not list((store / "assets").rglob("*"))


def test_release_ya_verificado_no_exige_espacio_ni_se_vuelve_a_extraer(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1")
    _importar_assets(host, "v1")
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    manifest = (store / ".manifests" / "v1.manifest").read_bytes()

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v1",
        FAKE_ASSET_AVAILABLE_KB="0",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "capacidad ok (sin bytes nuevos)" in resultado.stderr
    assert not _hay(host.llamadas(), r"docker run .*du -sk")
    assert not _hay(host.llamadas(), r"docker (create|cp) ")
    assert (store / ".manifests" / "v1.manifest").read_bytes() == manifest


def test_import_collision_leaves_live_assets_and_app_state_untouched(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1", shared="old immutable bytes")
    _assets_falsos(host, "v2", shared="different bytes")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "colision de asset" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose run")
    assert not _hay(host.llamadas(), r"compose up .*--force-recreate .*nginx$")
    assert not _hay(host.llamadas(), r"compose up .*--scale")
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert (store / ".manifests" / "v1.manifest").is_file()
    assert not (store / ".manifests" / "v2.manifest").exists()
    assert (store / "assets" / "shared.js").read_text(
        encoding="utf-8"
    ) == "old immutable bytes\n"
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    assert not (host.repo / ".deploy" / "previous").exists()


def test_falla_extraccion_preserva_manifest_y_app_actual(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1", shared="existing release")
    _importar_assets(host, "v1")
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    manifest = (store / ".manifests" / "v1.manifest").read_bytes()

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_ASSET_COPY_EXIT="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "no pude extraer" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose run")
    assert not _hay(host.llamadas(), r"compose up .*--scale")
    assert not _hay(host.llamadas(), r"compose up .*--force-recreate .*nginx$")
    assert (store / ".manifests" / "v1.manifest").read_bytes() == manifest
    assert (store / "assets" / "shared.js").read_text(encoding="utf-8") == (
        "existing release\n"
    )
    assert not (store / ".manifests" / "v2.manifest").exists()
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    assert not (host.repo / ".deploy" / "previous").exists()


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
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert (store / ".manifests" / "v1.manifest").is_file()
    assert (store / ".manifests" / "v2.manifest").is_file()
    assert (store / "assets" / "chunk-default.js").is_file()
    assert not _hay(llamadas, r"compose (down|rm) .*nginx")


# --- redeploy del mismo sha (2026-10-12, produccion) ---------------------------
# Correr otra vez `make deploy` con el sha que ya corria pisaba
# .deploy/previous con ese mismo sha: el log decia
# `deploy: 494f5072... -> 494f5072...` y previous paso de a203ee54 a 494f5072.
# El destino del rollback se perdia y `make rollback` "volvia" a lo que ya
# corria.


def _con_previous(host: Host, actual: str, previa: str) -> None:
    _preparar_deploy(host, actual=actual)
    (host.repo / ".deploy" / "previous").write_text(f"{previa}\n", encoding="utf-8")


def test_redeploy_del_mismo_sha_conserva_el_destino_del_rollback(
    host: Host,
) -> None:
    _con_previous(host, actual="v2", previa="v1")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert (host.repo / ".deploy" / "previous").read_text().strip() == "v1"
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"
    assert "redeploy de la misma version" in resultado.stderr


def test_deploy_de_otra_version_guarda_la_que_corria_como_previous(
    host: Host,
) -> None:
    _con_previous(host, actual="v2", previa="v1")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v3", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert (host.repo / ".deploy" / "previous").read_text().strip() == "v2"
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v3"
    assert "redeploy" not in resultado.stderr


def test_compuerta_fallida_en_un_redeploy_no_hace_rollback_y_conserva_previous(
    host: Host,
) -> None:
    """Antes del redeploy ya corria esta misma version: no hay a que volver.
    Ir a previous cambiaria de version sin que nadie lo pidiera, y una
    compuerta que falla con un sha que ya la paso apunta al entorno."""
    _con_previous(host, actual="v2", previa="v1")

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", FAKE_CURL_EXIT="22", **_BASE_DEPLOY
    )

    assert resultado.returncode == 1
    assert "ALERTA: deploy v2: fallo la compuerta en un redeploy" in resultado.stderr
    assert "make rollback" in resultado.stderr
    llamadas = host.llamadas()
    # Una sola ronda de backend: ni rollback a v2 ni a v1.
    rondas = [ll for ll in llamadas if re.search(r"compose up .*--scale backend=", ll)]
    assert len(rondas) == 1, rondas
    assert not _hay(llamadas, r"shifty-backend:v1")
    ids = (host.fake / "backend_ids").read_text().split()
    assert ids and all(i.endswith("-v2") for i in ids), ids
    assert (host.repo / ".deploy" / "previous").read_text().strip() == "v1"
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"


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


# --- frontend sin corte (2026-10-15, produccion) -----------------------------
#
# El frontend tenia container_name y el deploy lo RECREABA: entre que bajaba
# el contenedor viejo y nginx aprendia la IP del nuevo, la home daba 502. Log
# del deploy de 2026-10-15 23:49 UTC:
#   ✔ shifty_frontend Started
#   curl: (22) The requested URL returned error: 502
#   compuerta: https://shifty-ar.tech/ no respondio bien (1/12)
# Ahora se renueva como el backend: la replica nueva al lado de la vieja, sana
# antes de bajar la vieja, con el tiempo de DNS de nginx en el medio.


def _llamadas_de_un_deploy_ok(host: Host, **extra: str) -> list[str]:
    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", **{**_BASE_DEPLOY, **extra}
    )
    assert resultado.returncode == 0, resultado.stderr
    return host.llamadas()


def test_el_frontend_nuevo_esta_sano_antes_de_bajar_el_viejo(host: Host) -> None:
    _preparar_deploy(host, actual="v1")

    llamadas = _llamadas_de_un_deploy_ok(host)

    # Las replicas viejas del backend ya se bajaron: en el pico de memoria no
    # se suman las dos tandas.
    backend_viejo_fuera = _indice(llamadas, r"docker rm old1 old2$")
    front_nuevo = _indice(
        llamadas,
        r"compose up -d --no-deps --no-build --remove-orphans --no-recreate "
        r"--wait --wait-timeout 180 --scale frontend=2 frontend$",
    )
    # nginx re-resuelve `frontend` (resolve, valid=5s) antes de bajar la vieja.
    para_viejo = _indice(llamadas, r"docker stop -t 35 front-old1$")
    dns = _ultimo_indice(llamadas[:para_viejo], r"^sleep 6$")
    borra_viejo = _indice(llamadas, r"docker rm front-old1$")
    # Revision del PR #188: apenas se borra la vieja, el borde recarga y la
    # saca de sus peers (si no, la tiene hasta 5 s mas y la mitad de las
    # conexiones nuevas van a una IP que ya no existe). Antes que los workers.
    despues = llamadas[borra_viejo:]
    prueba = borra_viejo + _indice(despues, r"^docker compose exec -T nginx nginx -t$")
    recarga = borra_viejo + _indice(
        despues, r"^docker compose exec -T nginx nginx -s reload$"
    )
    resto = _indice(llamadas, r"compose up .* celery_beat$")
    assert backend_viejo_fuera < front_nuevo < dns < para_viejo < borra_viejo
    assert borra_viejo < prueba < recarga < resto, llamadas[borra_viejo : resto + 1]
    assert recarga == borra_viejo + 2, "el reload va justo despues de borrar la vieja"
    # El frontend nunca se recrea en el lugar: ningun `up` lo nombra sin
    # --no-recreate --scale (eso bajaba el viejo antes de tener el nuevo).
    for llamada in llamadas:
        if re.search(r"compose up .*\bfrontend\b", llamada):
            assert "--no-recreate" in llamada, llamada
            assert "--scale frontend=" in llamada, llamada
    ids = (host.fake / "frontend_ids").read_text().split()
    assert ids == ["front-new2-v2"], ids


def test_el_frontend_corre_una_sola_replica_despues_de_cada_deploy(
    host: Host,
) -> None:
    """Dos replicas solo durante el cambio: en estado estable alcanza una."""
    _preparar_deploy(host, actual="v1")

    _llamadas_de_un_deploy_ok(host)
    segundo = host.correr("deploy.sh", "deploy", APP_VERSION="v3", **_BASE_DEPLOY)

    assert segundo.returncode == 0, segundo.stderr
    assert _hay(host.llamadas(), r"docker stop -t 35 front-new2-v2$")
    ids = (host.fake / "frontend_ids").read_text().split()
    assert ids == ["front-new2-v3"], ids


def test_un_frontend_nuevo_que_no_queda_sano_se_descarta_y_hace_rollback(
    host: Host,
) -> None:
    """La SPA vieja nunca se baja sin una nueva sana. El backend ya es el
    nuevo: el rollback deja las dos piezas en la version anterior, tambien sin
    corte."""
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_UP_FRONTEND_FALLA_EN="v2",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 1, resultado.stderr
    # La alerta nombra la causa real, no la compuerta (revision del PR #188).
    assert (
        "ALERTA: deploy v2: el frontend nuevo no quedo sano, rollback a v1"
        in resultado.stderr
    )
    assert "fallo la compuerta" not in resultado.stderr
    llamadas = host.llamadas()
    descarta = _indice(llamadas, r"docker rm -f front-new2-v2$")
    rondas = [
        i
        for i, ll in enumerate(llamadas)
        if re.search(r"compose up .*--scale frontend=2 frontend$", ll)
    ]
    assert len(rondas) == 2, rondas
    # La vieja (v1) sigue sirviendo hasta que la del rollback esta sana.
    para_viejo = _indice(llamadas, r"docker stop -t 35 front-old1$")
    assert rondas[0] < descarta < rondas[1] < para_viejo
    assert sum(bool(re.search(r"alembic upgrade", ll)) for ll in llamadas) == 1
    assert (host.fake / "frontend_ids").read_text().split() == ["front-new2-v1"]
    ids = (host.fake / "backend_ids").read_text().split()
    assert ids and all(i.endswith("-v1") for i in ids), ids
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_un_borde_que_no_recarga_tras_el_frontend_lo_dice_en_la_alerta(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_NGINX_FAIL_ON_TEST="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert (
        "ALERTA: deploy v2: el borde no recargo despues de renovar el frontend, "
        "rollback a v1" in resultado.stderr
    )
    assert "nginx -t o reload fallo despues de bajar la replica vieja" in (
        resultado.stderr
    )


def test_rollback_renueva_el_frontend_sin_corte(host: Host) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "rollback", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    nuevo = _indice(
        llamadas, r"compose up .*--no-recreate .*--scale frontend=2 frontend$"
    )
    assert nuevo < _indice(llamadas, r"docker stop -t 35 front-old1$")
    assert (host.fake / "frontend_ids").read_text().split() == ["front-new2-v1"]


def test_sin_rolling_el_frontend_se_recrea_directo(host: Host) -> None:
    """DEPLOY_ROLLING=0 es la salida de emergencia si escalar falla: `up`
    directo, con el corte de antes."""
    _preparar_deploy(host, actual="v1")

    llamadas = _llamadas_de_un_deploy_ok(host, DEPLOY_ROLLING="0")

    assert _hay(
        llamadas,
        r"compose up -d --no-deps --no-build --remove-orphans --wait "
        r"--wait-timeout 180 frontend$",
    )
    assert not _hay(llamadas, r"--scale")


def test_un_deploy_sin_frontend_en_la_lista_no_recrea_frontend(host: Host) -> None:
    _preparar_deploy(host, actual="v1")

    llamadas = _llamadas_de_un_deploy_ok(
        host,
        DEPLOY_SERVICES="backend celery_worker celery_worker_interactive celery_beat",
    )

    assert not _hay(llamadas, r"compose up .*\bfrontend\b")


# --- make deploy-edge: el borde se recrea solo si cambio --------------------


def test_deploy_edge_falla_cerrado_si_faltan_assets_del_frontend_activo(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1")
    _importar_assets(host, "v1")
    host.env["FAKE_RUNNING_VERSION"] = "v3"

    resultado = host.correr(
        "deploy.sh", "edge", FAKE_ASSET_COPY_EXIT="1", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "no pude extraer" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up .*nginx$")


def _preparar_borde(host: Host, conf: str = "server {}\n") -> Path:
    _preparar_deploy(host, actual="v2")
    _importar_assets(host, "v2")
    return _sembrar_borde(host, conf=conf)


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


def test_deploy_edge_verifica_frontend_activo_no_el_marker_de_app(host: Host) -> None:
    _preparar_borde(host)
    inicial = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    assert inicial.returncode == 0, inicial.stderr
    (host.fake / "calls").unlink()
    # A backend-only deployment advances this marker without changing frontend.
    (host.repo / ".deploy" / "current").write_text("v3\n", encoding="utf-8")

    resultado = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert "verificado v2" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up .*nginx$")


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


# 2026-11-25: `nginx -t` corria recien dentro del borde recreado. Una config
# invalida dejaba un borde nuevo que no arrancaba y el sitio caido hasta el
# rollback. Ahora se prueba antes, en un contenedor efimero con la misma imagen
# y los mismos montajes, mientras el borde actual sigue sirviendo.
_NGINX_T_EFIMERO = r"compose run --rm --no-deps --entrypoint nginx -T nginx -t$"


def test_deploy_edge_prueba_la_config_nueva_antes_de_recrear(host: Host) -> None:
    archivo = _preparar_borde(host)
    host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    archivo.write_text("server { listen 443; }\n", encoding="utf-8")
    (host.fake / "calls").unlink()

    resultado = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    prueba = next(i for i, c in enumerate(llamadas) if re.search(_NGINX_T_EFIMERO, c))
    recrea = next(i for i, c in enumerate(llamadas) if "--force-recreate" in c)
    assert prueba < recrea, llamadas


def test_deploy_edge_no_recrea_si_la_config_nueva_no_pasa_nginx_t(host: Host) -> None:
    archivo = _preparar_borde(host)
    host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    huella = (host.repo / ".deploy" / "edge-conf.sha256").read_text(encoding="utf-8")
    archivo.write_text("server { esto_no_es_una_directiva; }\n", encoding="utf-8")
    (host.fake / "calls").unlink()

    resultado = host.correr(
        "deploy.sh", "edge", FAKE_EDGE_NGINX_T_EXIT="1", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "no pasa nginx -t" in resultado.stdout + resultado.stderr
    llamadas = host.llamadas()
    assert _hay(llamadas, _NGINX_T_EFIMERO)
    assert not _hay(llamadas, r"--force-recreate")
    assert not _hay(llamadas, r"nginx -s reload")
    # Sin registrar la huella nueva: el proximo `edge` vuelve a intentarlo.
    assert (host.repo / ".deploy" / "edge-conf.sha256").read_text(
        encoding="utf-8"
    ) == huella


def test_deploy_edge_sin_cambios_no_levanta_el_contenedor_de_prueba(host: Host) -> None:
    _preparar_borde(host)
    host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    (host.fake / "calls").unlink()

    resultado = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert not _hay(host.llamadas(), _NGINX_T_EFIMERO)


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
    assert f"head_sha={SHA}" in url
    # Los filtros de GitHub por estado, rama o evento salen de un indice que se
    # atrasa (2026-11-23): se verifican en la respuesta, no en la consulta.
    for filtro in ("status=", "branch=", "event="):
        assert filtro not in url, filtro
    llamadas = host.llamadas()
    assert _indice(llamadas, r"api\.github\.com") < _indice(llamadas, r"compose pull")
    assert "Quality verde en main" in resultado.stderr


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


# --- Quality sin el indice de `status=success` (2026-11-23) -------------------
#
# El preflight de 9c984669 freno con "Quality no paso en main": la corrida
# 45080249904 estaba completed/success desde las 23:07 UTC, pero la API con
# `status=success` (o `completed`) no la devolvia 4 h despues; sin ese filtro
# si. Ahora se piden las corridas del sha y se verifica cada campo en la
# respuesta, fallando cerrado ante cualquier duda.


def test_una_corrida_verde_que_el_filtro_de_status_no_mostraba_pasa(
    host: Host,
) -> None:
    """El caso de produccion: la respuesta trae la corrida real (sin el filtro
    que la escondia) y el deploy sigue."""
    _preparar_deploy(host)
    escribir_corridas_de_quality(
        host.fake / "gh_runs",
        corridas=[corrida_de_quality(id=45080249904, head_sha=SHA)],
    )

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert "status=" not in _consultas_a_github(host)[0]
    assert f"Quality verde en main para {SHA} (corrida 45080249904)" in resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == SHA


OTRO_SHA = "fedcba9876543210fedcba9876543210fedcba98"


@pytest.mark.parametrize(
    ("corridas", "version", "motivo"),
    [
        ([corrida_de_quality(conclusion="failure")], SHA, "esta completed/failure"),
        ([corrida_de_quality(conclusion="cancelled")], SHA, "esta completed/cancelled"),
        (
            [corrida_de_quality(status="in_progress", conclusion=None)],
            SHA,
            "esta in_progress/null",
        ),
        (
            [corrida_de_quality(status="queued", conclusion="")],
            SHA,
            "esta queued/-",
        ),
        (
            [corrida_de_quality(path=".github/workflows/security-scan.yml")],
            SHA,
            "no hay una corrida de un push a main",
        ),
        ([corrida_de_quality(head_sha=OTRO_SHA)], SHA, "no hay una corrida"),
        ([corrida_de_quality(head_sha=SHA)], SHA[:12], "no hay una corrida"),
        ([corrida_de_quality(head_branch="feat/x")], SHA, "no hay una corrida"),
        ([corrida_de_quality(event="workflow_dispatch")], SHA, "no hay una corrida"),
        ([corrida_de_quality(event="pull_request")], SHA, "no hay una corrida"),
        (
            # La verde vieja no tapa un reintento posterior en rojo.
            [
                corrida_de_quality(id=20, conclusion="failure"),
                corrida_de_quality(id=10),
            ],
            SHA,
            "la corrida 20 esta completed/failure",
        ),
        (
            # El orden de la respuesta no decide: decide el id mas nuevo.
            [
                corrida_de_quality(id=10),
                corrida_de_quality(id=20, status="in_progress", conclusion=None),
            ],
            SHA,
            "la corrida 20 esta in_progress/null",
        ),
        (
            # Lo verde esta solo en objetos anidados, no en la corrida.
            [
                corrida_de_quality(
                    status="in_progress",
                    conclusion=None,
                    head_commit={"status": "completed", "conclusion": "success"},
                    repository={"path": ".github/workflows/quality.yml"},
                )
            ],
            SHA,
            "esta in_progress/null",
        ),
    ],
    ids=[
        "fallida",
        "cancelada",
        "en-curso",
        "encolada-conclusion-vacia",
        "otro-workflow",
        "otro-sha",
        "sha-corto",
        "otra-rama",
        "a-mano",
        "pull-request",
        "reintento-rojo-mas-nuevo",
        "reintento-en-curso-mas-nuevo",
        "verde-solo-en-anidados",
    ],
)
def test_quality_frena_si_la_corrida_del_sha_no_es_un_verde_de_main(
    host: Host, corridas: list[dict[str, object]], version: str, motivo: str
) -> None:
    _preparar_deploy(host)
    escribir_corridas_de_quality(host.fake / "gh_runs", corridas=corridas)

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=version, **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "Quality no paso en main" in resultado.stderr
    assert motivo in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_un_reintento_verde_mas_nuevo_que_uno_rojo_pasa(host: Host) -> None:
    _preparar_deploy(host)
    escribir_corridas_de_quality(
        host.fake / "gh_runs",
        corridas=[
            corrida_de_quality(id=10, conclusion="failure"),
            corrida_de_quality(id=20),
        ],
    )

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert "(corrida 20)" in resultado.stderr


def test_mas_corridas_que_las_de_una_pagina_frena(host: Host) -> None:
    """Si la ultima corrida pudo quedar en otra pagina, no se adivina."""
    _preparar_deploy(host)
    escribir_corridas_de_quality(
        host.fake / "gh_runs", corridas=[corrida_de_quality()], total=101
    )

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION=SHA, **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "solo se leyeron 1" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose (pull|run|up)")


@pytest.mark.parametrize(
    "cuerpo",
    [
        '{"total_count": 1, "workflow_runs": [{"id": 1, "status": "completed"',
        '{"total_count": 1, "workflow_runs": [{"id": 1,}]}',
        '{"total_count": 1, "workflow_runs": [{"id": 1, "path": "a\\"}]}',
        '{"total_count": "1", "workflow_runs": []}',
        '[{"total_count": 1}]',
        "<html>502 Bad Gateway</html>",
        "",
    ],
    ids=[
        "cortada",
        "coma-de-mas",
        "string-sin-cerrar",
        "total-como-string",
        "raiz-no-objeto",
        "html",
        "vacia",
    ],
)
def test_una_respuesta_de_github_malformada_frena(host: Host, cuerpo: str) -> None:
    _preparar_deploy(host)
    (host.fake / "gh_runs").write_text(cuerpo + "\n", encoding="utf-8", newline="\n")

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


def test_redeploy_del_mismo_sha_protege_assets_del_previous(host: Host) -> None:
    _con_previous(host, actual="v2", previa="v1")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert (store / ".manifests" / "v1.manifest").is_file()
    assert (store / ".manifests" / "v2.manifest").is_file()
    assert (host.repo / ".deploy" / "previous").read_text().strip() == "v1"


def test_deploy_solo_backend_no_traba_el_siguiente_deploy_completo(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v3")

    backend_only = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        DEPLOY_SERVICES="backend celery_worker celery_worker_interactive celery_beat",
        **_BASE_DEPLOY,
    )
    assert backend_only.returncode == 0, backend_only.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v2"
    assert (host.repo / ".deploy" / "frontend-current").read_text().strip() == "v1"

    full_next = host.correr("deploy.sh", "deploy", APP_VERSION="v3", **_BASE_DEPLOY)
    assert full_next.returncode == 0, full_next.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v3"
    assert (host.repo / ".deploy" / "frontend-current").read_text().strip() == "v3"
    assert (host.repo / ".deploy" / "frontend-previous").read_text().strip() == "v1"

    (host.repo / "nginx").mkdir(exist_ok=True)
    (host.repo / "nginx" / "nginx.prod.conf").write_text(
        "server {}\n", encoding="utf-8", newline="\n"
    )
    edge = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    assert edge.returncode == 0, edge.stderr


def test_common_sh_exporta_asset_store_path_fallback_y_respeta_env(
    tmp_path: Path,
) -> None:
    assert BASH is not None
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    common = REPO_ROOT / "scripts" / "lib" / "common.sh"
    (repo / "scripts" / "lib" / "common.sh").write_bytes(common.read_bytes())

    (repo / ".env").write_text("COMPOSE_PROJECT_NAME=shifty\n", encoding="utf-8")
    env_clean = {
        k: v
        for k, v in os.environ.items()
        if k not in {"ASSET_STORE_PATH", "DEPLOY_ASSET_STORE", "SHIFTY_DIR"}
    }
    res_default = subprocess.run(
        [
            BASH,
            "-c",
            'source scripts/lib/common.sh && printf "%s" "${ASSET_STORE_PATH:-}"',
        ],
        cwd=repo,
        env={**env_clean, "SHIFTY_DIR": repo.as_posix()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_default.returncode == 0, res_default.stderr
    assert res_default.stdout == "/var/lib/shifty-assets"

    (repo / ".env").write_text(
        "COMPOSE_PROJECT_NAME=shifty\nASSET_STORE_PATH=/srv/custom-assets\n",
        encoding="utf-8",
    )
    res_explicit = subprocess.run(
        [
            BASH,
            "-c",
            'source scripts/lib/common.sh && printf "%s" "${ASSET_STORE_PATH:-UNSET}"',
        ],
        cwd=repo,
        env={**env_clean, "SHIFTY_DIR": repo.as_posix()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_explicit.returncode == 0, res_explicit.stderr
    assert res_explicit.stdout == "UNSET"


def test_rollback_sin_contenedor_frontend_corriendo_conserva_assets_y_recupera(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")
    (host.repo / ".deploy" / "frontend-current").write_text("v2\n", encoding="utf-8")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")
    _importar_assets(host, "v1")
    _importar_assets(host, "v2")
    (host.fake / "frontend_ids").write_text("", encoding="utf-8")

    resultado = host.correr("deploy.sh", "rollback", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert (store / ".manifests" / "v1.manifest").is_file()
    assert (store / ".manifests" / "v2.manifest").is_file()


def test_preflight_rechaza_asset_store_distinto_entre_ops_y_env(
    host: Host, tmp_path: Path
) -> None:
    _preparar_deploy(host, actual="v1")
    otro_store = (tmp_path / "otro-asset-store").as_posix()
    (host.repo / ".env").write_text(
        f"COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml\nASSET_STORE_PATH={otro_store}\n",
        encoding="utf-8",
    )

    resultado = host.correr("deploy.sh", "preflight", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "difiere de ASSET_STORE_PATH" in resultado.stderr


def test_segundo_deploy_con_borde_sin_cambios_no_recrea_nginx(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    (host.repo / "nginx").mkdir(exist_ok=True)
    (host.repo / "nginx" / "nginx.prod.conf").write_text(
        "server {}\n", encoding="utf-8", newline="\n"
    )
    primero = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)
    assert primero.returncode == 0, primero.stderr
    (host.fake / "calls").unlink()

    segundo = host.correr("deploy.sh", "deploy", APP_VERSION="v3", **_BASE_DEPLOY)

    assert segundo.returncode == 0, segundo.stderr
    assert not _hay(host.llamadas(), r"--force-recreate .*nginx$")
    assert _hay(host.llamadas(), r"compose exec -T nginx nginx -s reload")


# --- V5 regressions: P2-1, P2-4, P2-04 -------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"FAKE_NGINX_DOWN": "1"},
        {"FAKE_NGINX_MOUNT_MISSING": "1"},
        {"FAKE_NGINX_MOUNT_RW": "true"},
        {"FAKE_NGINX_STATE": "exited"},
        {"FAKE_NGINX_MOUNT_SOURCE": "/otro/store/assets"},
    ],
    ids=[
        "nginx-caido",
        "sin-mount-assets",
        "mount-rw-en-vez-de-ro",
        "nginx-no-running",
        "mount-fuera-de-store",
    ],
)
def test_p2_1_deploy_falla_cerrado_si_borde_no_tiene_mount_ro(
    host: Host, extra: dict[str, str]
) -> None:
    _preparar_deploy(host, actual="v1")

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY, **extra
    )

    assert resultado.returncode != 0
    assert "scripts/deploy.sh edge" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up .*nginx$")
    assert not _hay(host.llamadas(), r"alembic upgrade")
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


@pytest.mark.parametrize(
    "cambio",
    ["conf-cambiada", "sin-fingerprint", "imagen-cambiada"],
)
def test_p2_1_deploy_falla_cerrado_si_cambio_borde_sin_correr_edge(
    host: Host, cambio: str
) -> None:
    _preparar_deploy(host, actual="v1")
    extra: dict[str, str] = {}
    if cambio == "conf-cambiada":
        (host.repo / "nginx" / "nginx.prod.conf").write_text(
            "server { listen 443; }\n", encoding="utf-8", newline="\n"
        )
    elif cambio == "sin-fingerprint":
        (host.repo / ".deploy" / "edge-conf.sha256").unlink()
    elif cambio == "imagen-cambiada":
        extra["FAKE_IMAGE_ID"] = "sha256:nueva"

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY, **extra
    )

    assert resultado.returncode != 0
    assert "scripts/deploy.sh edge" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up .*nginx$")
    assert not _hay(host.llamadas(), r"alembic upgrade")


def test_p2_1_edge_prevalida_nginx_t_y_deja_vivo_intacto_si_falla(host: Host) -> None:
    _preparar_borde(host, conf="server {}\n")
    fingerprint_antes = (host.repo / ".deploy" / "edge-conf.sha256").read_text()
    (host.repo / "nginx" / "nginx.prod.conf").write_text(
        "server { broken; }\n", encoding="utf-8", newline="\n"
    )

    resultado = host.correr(
        "deploy.sh", "edge", FAKE_NGINX_TEST_EXIT="1", **_BASE_DEPLOY
    )

    assert resultado.returncode != 0
    assert "nginx -t" in resultado.stderr
    llamadas = host.llamadas()
    assert _hay(llamadas, r"compose pull nginx$")
    assert _hay(llamadas, _NGINX_T_EFIMERO)
    assert not _hay(llamadas, r"compose up .*nginx$")
    assert (host.repo / ".deploy" / "edge-conf.sha256").read_text() == fingerprint_antes


def test_p2_1_edge_importa_assets_pre_retencion_y_verifica_mount_ro(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    (host.repo / ".deploy" / "previous").write_text("v0\n", encoding="utf-8")
    # Backend-only advance: current is v2 while running frontend is v1.
    (host.repo / ".deploy" / "current").write_text("v2\n", encoding="utf-8")
    (host.repo / ".deploy" / "edge-conf.sha256").unlink()
    _assets_falsos(host, "v0")
    _assets_falsos(host, "v1")

    resultado = host.correr(
        "deploy.sh", "edge", FAKE_NGINX_MOUNT_MISSING="", **_BASE_DEPLOY
    )

    assert resultado.returncode == 0, resultado.stderr
    store = Path(host.env["DEPLOY_ASSET_STORE"])
    assert (store / ".manifests" / "v0.manifest").is_file()
    assert (store / ".manifests" / "v1.manifest").is_file()
    assert not (store / ".manifests" / "v2.manifest").exists()
    llamadas = host.llamadas()
    assert _indice(llamadas, r"docker cp .*assets/\.") < _indice(
        llamadas, _NGINX_T_EFIMERO
    )
    assert _hay(llamadas, r"--force-recreate .*nginx$")
    assert (host.repo / ".deploy" / "edge-conf.sha256").is_file()


def test_p2_1_edge_en_host_vacio_usa_app_version_y_siembra_fingerprint(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    (host.repo / ".deploy" / "current").unlink()
    (host.repo / ".deploy" / "edge-conf.sha256").unlink()
    (host.fake / "frontend_ids").write_text("", encoding="utf-8")
    (host.fake / "backend_ids").write_text("", encoding="utf-8")

    sin_version = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    assert sin_version.returncode != 0
    assert "APP_VERSION" in sin_version.stderr

    resultado = host.correr(
        "deploy.sh",
        "edge",
        APP_VERSION="v1",
        FAKE_NGINX_DOWN="1",
        FAKE_NGINX_MOUNT_MISSING="1",
        **_BASE_DEPLOY,
    )
    # Because FAKE_NGINX_DOWN=1 stays set after compose up, post-recreate check fails closed.
    assert resultado.returncode != 0
    assert "solo lectura" in resultado.stderr

    (host.fake / "calls").unlink()
    ok = host.correr("deploy.sh", "edge", APP_VERSION="v1", **_BASE_DEPLOY)
    assert ok.returncode == 0, ok.stderr
    assert (host.repo / ".deploy" / "edge-conf.sha256").is_file()
    assert _hay(host.llamadas(), _NGINX_T_EFIMERO)


def test_p2_1_edge_con_marker_y_sin_frontend_activo_falla_cerrado(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    (host.fake / "frontend_ids").write_text("", encoding="utf-8")

    resultado = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "release registrado" in resultado.stderr
    assert not _hay(host.llamadas(), r"compose up .*nginx$")


def test_p2_4_recupera_deploy_inicial_interrumpido_sin_previous_falso(
    host: Host,
) -> None:
    (host.repo / ".env").write_text(
        "COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml\n", encoding="utf-8"
    )
    _backup_fresco(host)
    _sembrar_borde(host)
    (host.fake / "backend_ids").write_text("new1-v1\n", encoding="utf-8", newline="\n")
    (host.fake / "frontend_ids").write_text("", encoding="utf-8", newline="\n")
    host.env["FAKE_RUNNING_VERSION"] = "v1"
    _assets_falsos(host, "v1")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v1", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    assert (host.repo / ".deploy" / "frontend-current").read_text().strip() == "v1"
    assert not (host.repo / ".deploy" / "previous").exists()
    assert not (host.repo / ".deploy" / "frontend-previous").exists()


@pytest.mark.parametrize(
    "marker",
    ["current", "previous", "frontend-current", "frontend-previous"],
)
def test_p2_4_host_con_marker_y_sin_frontend_sigue_fallando_cerrado(
    host: Host, marker: str
) -> None:
    _preparar_deploy(host, actual="v1")
    (host.repo / ".deploy" / "current").unlink()
    (host.repo / ".deploy" / marker).write_text("v1\n", encoding="utf-8")
    (host.fake / "frontend_ids").write_text("", encoding="utf-8")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode != 0
    assert "release registrado" in resultado.stderr
    assert not _hay(host.llamadas(), r"alembic upgrade")
    assert not _hay(host.llamadas(), r"compose up")


def test_p2_04_asset_js_valido_pasa_compuerta(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert "asset JS chunk-v2.js ok" in resultado.stderr
    asset_curls = [
        ll
        for ll in host.llamadas()
        if re.search(r"^curl .*https://shifty\.example\.com/assets/chunk-v2\.js$", ll)
    ]
    assert len(asset_curls) == 1, host.llamadas()
    assert "Accept-Encoding: identity" in asset_curls[0]
    assert " -L " not in asset_curls[0]
    assert " -k " not in asset_curls[0]


@pytest.mark.parametrize(
    ("extra", "motivo"),
    [
        ({"FAKE_ASSET_HTTP_CODE": "404"}, "devolvio HTTP 404"),
        (
            {
                "FAKE_ASSET_HTTP_CODE": "200",
                "FAKE_ASSET_HTTP_MIME": "text/html; charset=utf-8",
                "FAKE_ASSET_HTTP_BODY": "<!DOCTYPE html><html></html>",
            },
            "Content-Type invalido",
        ),
        (
            {
                "FAKE_ASSET_HTTP_CODE": "200",
                "FAKE_ASSET_HTTP_MIME": "application/javascript",
                "FAKE_ASSET_HTTP_BODY": "\n  <!doctype html><html></html>",
            },
            "devolvio HTML en vez de JavaScript",
        ),
        (
            {
                "FAKE_ASSET_HTTP_CODE": "200",
                "FAKE_ASSET_HTTP_MIME": "application/javascript",
                "FAKE_ASSET_HTTP_BODY": "console.log('corrupted');\n",
            },
            "no coincide en hash/tamano",
        ),
        ({"FAKE_ASSET_HTTP_EXIT": "28"}, "curl exit 28"),
        ({"FAKE_ASSET_HTTP_CODE": "403"}, "devolvio HTTP 403"),
    ],
    ids=[
        "http-404",
        "mime-html",
        "cuerpo-html-con-mime-js",
        "contenido-distinto",
        "timeout-curl-28",
        "http-403",
    ],
)
def test_p2_04_asset_smoke_fallido_dispara_rollback(
    host: Host, extra: dict[str, str], motivo: str
) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")

    resultado = host.correr(
        "deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY, **extra
    )

    assert resultado.returncode != 0
    assert motivo in resultado.stderr
    assert "rollback a v1" in resultado.stderr
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"
    ids = (host.fake / "backend_ids").read_text().split()
    assert ids and all(i.endswith("-v1") for i in ids), ids


def test_p2_04_rollback_verifica_el_asset_js_del_target_de_rollback(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")

    resultado = host.correr("deploy.sh", "rollback", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    assert "asset JS chunk-v1.js ok" in resultado.stderr
    assert _hay(
        host.llamadas(),
        r"^curl .*https://shifty\.example\.com/assets/chunk-v1\.js$",
    )
    assert (host.repo / ".deploy" / "current").read_text().strip() == "v1"


def test_p0_deploy_resuelve_imagen_exacta_de_nginx_y_frontend_con_dependencias_delante(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    _assets_falsos(host, "v1")
    _assets_falsos(host, "v2")

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        FAKE_NGINX_IMAGE="ghcr.io/x/nginx-custom:1.30.7-alpine",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    assert _hay(llamadas, r"^docker compose config nginx$")
    assert _hay(llamadas, r"^docker compose config frontend$")
    assert _hay(
        llamadas,
        r"^docker image inspect -f \{\{\.Id\}\} ghcr\.io/x/nginx-custom:1\.30\.7-alpine$",
    )
    assert _hay(
        llamadas,
        r"^docker image inspect -f \{\{\.Id\}\} ghcr\.io/x/shifty-frontend:v2$",
    )
    assert not _hay(llamadas, r"docker image inspect -f \{\{\.Id\}\} postgres:")
    assert not _hay(
        llamadas, r"docker image inspect -f \{\{\.Id\}\} ghcr\.io/x/shifty-backend:"
    )


def test_p0_edge_resuelve_imagen_exacta_de_nginx_con_dependencias_delante(
    host: Host,
) -> None:
    _preparar_borde(host)

    resultado = host.correr(
        "deploy.sh",
        "edge",
        FAKE_NGINX_IMAGE="ghcr.io/x/nginx-custom:1.30.7-alpine",
        FAKE_NGINX_RUNNING_IMAGE_ID="sha256:vieja",
        FAKE_IMAGE_ID="sha256:nueva",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    assert _hay(llamadas, r"^docker compose config nginx$")
    assert _hay(
        llamadas,
        r"^docker image inspect -f \{\{\.Id\}\} ghcr\.io/x/nginx-custom:1\.30\.7-alpine$",
    )
    assert not _hay(llamadas, r"docker image inspect -f \{\{\.Id\}\} postgres:")
    assert _hay(llamadas, r"--force-recreate .*nginx$")


def _hook_falla_escritura_current(host: Host) -> Path:
    hook = host.raiz / "fail-write-current.sh"
    hook.write_text(
        """printf() {
  if [ "${FUNCNAME[1]:-}" = "escribir_estado" ] && [ "${destino:-}" != "${destino%/current}" ]; then
    return 28
  fi
  builtin printf "$@"
}
""",
        encoding="utf-8",
        newline="\n",
    )
    return hook


def test_escribir_estado_fallido_en_deploy_falla_y_preserva_current(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v1")
    hook = _hook_falla_escritura_current(host)

    resultado = host.correr(
        "deploy.sh",
        "deploy",
        APP_VERSION="v2",
        DEPLOY_AUTO_ROLLBACK="0",
        BASH_ENV=hook.as_posix(),
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert (host.repo / ".deploy" / "current").read_text(
        encoding="utf-8"
    ).strip() == "v1"
    assert not list((host.repo / ".deploy").glob("current.*"))


def test_escribir_estado_fallido_en_rollback_falla_y_preserva_current(
    host: Host,
) -> None:
    _preparar_deploy(host, actual="v2")
    (host.repo / ".deploy" / "previous").write_text("v1\n", encoding="utf-8")
    hook = _hook_falla_escritura_current(host)

    resultado = host.correr(
        "deploy.sh",
        "rollback",
        BASH_ENV=hook.as_posix(),
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert (host.repo / ".deploy" / "current").read_text(
        encoding="utf-8"
    ).strip() == "v2"
    assert not list((host.repo / ".deploy").glob("current.*"))


def test_asset_extract_release_usa_nombres_unicos_por_indice(host: Host) -> None:
    _preparar_deploy(host, actual="v1")
    host.env["FAKE_RUNNING_VERSION"] = "v0"
    (host.repo / ".deploy" / "previous").write_text("v0\n", encoding="utf-8")
    for release in ("v0", "v1", "v2"):
        _assets_falsos(host, release)

    resultado = host.correr("deploy.sh", "deploy", APP_VERSION="v2", **_BASE_DEPLOY)

    assert resultado.returncode == 0, resultado.stderr
    nombres: list[str] = []
    for llamada in host.llamadas():
        match = re.search(r"^docker create --name (\S+) ", llamada)
        if match:
            nombres.append(match.group(1))
    assert len(nombres) == 3, nombres
    assert len(set(nombres)) == 3, nombres
    indices = [nombre.rsplit("-", 1)[-1] for nombre in nombres]
    assert indices == ["0", "1", "2"], nombres


def test_leer_env_repo_valida_clave_y_normaliza_valores(tmp_path: Path) -> None:
    assert BASH is not None
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    common = REPO_ROOT / "scripts" / "lib" / "common.sh"
    (repo / "scripts" / "lib" / "common.sh").write_bytes(common.read_bytes())
    (repo / ".env").write_bytes(
        b'COMPOSE_FILE="docker-compose.yml"  \r\n'
        b"COMPOSE_FILE = 'docker-compose.yml:docker-compose.prod.yml' \r\n"
    )

    ok = subprocess.run(
        [
            BASH,
            "-c",
            "set -euo pipefail; source scripts/lib/common.sh; leer_env_repo COMPOSE_FILE",
        ],
        cwd=repo,
        env={**os.environ, "SHIFTY_DIR": repo.as_posix()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip() == "docker-compose.yml:docker-compose.prod.yml"

    invalida = subprocess.run(
        [
            BASH,
            "-c",
            'source scripts/lib/common.sh; leer_env_repo "BAD/KEY"',
        ],
        cwd=repo,
        env={**os.environ, "SHIFTY_DIR": repo.as_posix()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalida.returncode != 0


def test_deploy_edge_rollback_pre_retencion_recrea_sin_exigir_montaje_assets(
    host: Host,
) -> None:
    archivo = _preparar_borde(
        host, conf="server { location ^~ /assets/ { root /srv/shifty-assets; } }\n"
    )
    inicial = host.correr("deploy.sh", "edge", **_BASE_DEPLOY)
    assert inicial.returncode == 0, inicial.stderr
    huella_anterior = (host.repo / ".deploy" / "edge-conf.sha256").read_text(
        encoding="utf-8"
    )

    # Also verify that if only compose drops the mount while the live container
    # still mounts assets (huella unchanged), edge still recreates to drop it.
    (host.repo / "docker-compose.prod.yml").write_text(
        "services:\n  nginx:\n    image: nginx:1.30.7-alpine\n",
        encoding="utf-8",
        newline="\n",
    )
    archivo.write_text("server { listen 443; }\n", encoding="utf-8", newline="\n")
    (host.repo / ".deploy" / "edge-conf.sha256").write_text(
        hashlib.sha256(
            f"server {{ listen 443; }}\n\nasset-store={host.env['DEPLOY_ASSET_STORE']}\n".encode(
                "utf-8"
            )
        ).hexdigest()
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (host.fake / "calls").unlink()

    recrea_por_mount = host.correr(
        "deploy.sh",
        "edge",
        FAKE_EDGE_WITHOUT_ASSETS_MOUNT="1",
        **_BASE_DEPLOY,
    )
    assert recrea_por_mount.returncode == 0, recrea_por_mount.stderr
    llamadas_mount = host.llamadas()
    assert _hay(llamadas_mount, _NGINX_T_EFIMERO)
    assert _hay(llamadas_mount, r"--force-recreate .*nginx$")

    # Now restore the previous fingerprint and verify full rollback with mount gone.
    (host.repo / ".deploy" / "edge-conf.sha256").write_text(
        huella_anterior, encoding="utf-8", newline="\n"
    )
    (host.fake / "calls").unlink()

    resultado = host.correr(
        "deploy.sh",
        "edge",
        FAKE_EDGE_WITHOUT_ASSETS_MOUNT="1",
        FAKE_NGINX_MOUNT_MISSING="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    prueba = next(i for i, c in enumerate(llamadas) if re.search(_NGINX_T_EFIMERO, c))
    recrea = next(i for i, c in enumerate(llamadas) if "--force-recreate" in c)
    assert prueba < recrea, llamadas
    assert _hay(llamadas, r"compose exec -T nginx nginx -s reload")
    huella_nueva = (host.repo / ".deploy" / "edge-conf.sha256").read_text(
        encoding="utf-8"
    )
    assert huella_nueva != huella_anterior


def test_deploy_edge_falla_cerrado_si_nginx_conf_usa_assets_sin_montaje_compose(
    host: Host,
) -> None:
    _preparar_borde(
        host, conf="server { location ^~ /assets/ { root /srv/shifty-assets; } }\n"
    )
    (host.repo / "docker-compose.prod.yml").write_text(
        "services:\n  nginx:\n    image: nginx:1.30.7-alpine\n",
        encoding="utf-8",
        newline="\n",
    )
    (host.repo / ".deploy" / "edge-conf.sha256").unlink()
    (host.fake / "calls").unlink(missing_ok=True)

    resultado = host.correr(
        "deploy.sh",
        "edge",
        FAKE_EDGE_WITHOUT_ASSETS_MOUNT="1",
        FAKE_NGINX_MOUNT_MISSING="1",
        **_BASE_DEPLOY,
    )

    assert resultado.returncode != 0
    assert "solo lectura" in resultado.stderr
    assert not _hay(host.llamadas(), r"nginx -s reload")
    assert not (host.repo / ".deploy" / "edge-conf.sha256").exists()


def test_deploy_edge_recupera_con_imagen_local_si_registro_no_responde(
    host: Host,
) -> None:
    _preparar_borde(host)
    (host.fake / "calls").unlink(missing_ok=True)

    con_local = host.correr(
        "deploy.sh",
        "edge",
        FAKE_PULL_EXIT="1",
        FAKE_IMAGE_ID="sha256:igual",
        **_BASE_DEPLOY,
    )
    assert con_local.returncode == 0, con_local.stderr
    assert _hay(host.llamadas(), r"compose exec -T nginx nginx -s reload")

    (host.fake / "calls").unlink()
    sin_local = host.correr(
        "deploy.sh",
        "edge",
        FAKE_PULL_EXIT="1",
        FAKE_IMAGE_ID="",
        **_BASE_DEPLOY,
    )
    assert sin_local.returncode != 0
    assert "falta la imagen" in sin_local.stderr
    assert not _hay(host.llamadas(), r"--force-recreate")
