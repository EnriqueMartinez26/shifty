"""scripts/guard.sh y scripts/checks.sh: guard y chequeos del host (F0-21, F0-23).

2026-09-24. `restart: always` no actua sobre un contenedor `unhealthy`, y nadie
miraba el reloj, el certificado ni el disco (R11-05, R11-20). Se corren los
scripts REALES con binarios falsos (tests/unit/host_falso.py).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.unit.host_falso import (
    DEPLOY,
    Host,
    _hay,
    _lineas_de_cron,
    crear_host,
)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return crear_host(tmp_path)


def test_guard_reinicia_el_unhealthy_y_avisa(host: Host) -> None:
    resultado = host.correr(
        "guard.sh", FAKE_UNHEALTHY_IDS="abc123", ALERT_WEBHOOK_URL="https://hook"
    )

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    assert _hay(
        llamadas,
        r"docker ps -q --filter health=unhealthy "
        r"--filter label=com.docker.compose.project=shifty "
        r"--filter label=com.docker.compose.oneoff=False",
    )
    assert _hay(llamadas, r"docker restart abc123")
    assert _hay(llamadas, r"curl .*https://hook")


def test_guard_no_pasa_de_tres_reinicios_por_hora(host: Host) -> None:
    for _ in range(4):
        host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")

    reinicios = [ll for ll in host.llamadas() if ll.startswith("docker restart")]
    assert len(reinicios) == 3
    ultimo = host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")
    assert "ya se reinicio" in ultimo.stderr


def test_guard_olvida_los_reinicios_de_hace_mas_de_una_hora(host: Host) -> None:
    viejo = int(time.time()) - 3700
    (host.state / "guard").mkdir(parents=True)
    (host.state / "guard" / "abc123").write_text(
        f"{viejo}\n{viejo}\n{viejo}\n", encoding="utf-8"
    )

    host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")

    assert _hay(host.llamadas(), r"docker restart abc123")


def test_guard_no_actua_durante_un_deploy(host: Host) -> None:
    (host.repo / ".deploy" / "lock").mkdir(parents=True)

    resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")

    assert resultado.returncode == 0
    assert not _hay(host.llamadas(), r"docker restart")


# --- revision 2026-09-24: que NO reinicia el guard ----------------------------
# Convencion del docker falso: el contenedor `shifty-<servicio>-<n>` es del
# servicio <servicio> (label com.docker.compose.service).


def _reinicios(host: Host) -> list[str]:
    return [ll for ll in host.llamadas() if ll.startswith("docker restart")]


@pytest.mark.parametrize("servicio", ["db", "rabbitmq"])
def test_guard_no_reinicia_la_base_ni_rabbitmq_solo_avisa(
    host: Host, servicio: str
) -> None:
    """Reiniciar Postgres o RabbitMQ en caliente corta todas las conexiones y
    puede empeorar lo que lo puso unhealthy: eso lo decide una persona."""
    resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS=f"shifty-{servicio}-1")

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    assert "ALERTA" in resultado.stderr
    assert f"shifty-{servicio}-1" in resultado.stderr


@pytest.mark.parametrize("dependencia", ["db", "redis_state"])
def test_guard_no_reinicia_nada_si_una_dependencia_esta_caida(
    host: Host, dependencia: str
) -> None:
    """Con la base o el Redis de estado caidos, el backend queda unhealthy por
    arrastre: reiniciarlo en bucle no arregla nada y quema el tope."""
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS=f"shifty-{dependencia}-1 shifty-backend-1 shifty-backend-2",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    assert "ALERTA" in resultado.stderr
    assert dependencia in resultado.stderr


def test_guard_tiene_un_tope_global_de_seis_reinicios_por_hora(host: Host) -> None:
    ids = " ".join(f"shifty-backend-{n}" for n in range(1, 9))

    resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS=ids)

    assert resultado.returncode == 0, resultado.stderr
    assert len(_reinicios(host)) == 6
    assert "tope global" in resultado.stderr

    # La hora siguiente sigue contando los 6 de antes.
    (host.fake / "calls").unlink()
    host.correr("guard.sh", FAKE_UNHEALTHY_IDS="shifty-backend-9")
    assert _reinicios(host) == []


# --- checks.sh --------------------------------------------------------------


def _fecha_en(dias: int) -> str:
    return time.strftime(
        "%b %d %H:%M:%S %Y GMT", time.gmtime(time.time() + dias * 86400)
    )


def test_checks_todo_bien_no_alerta_y_anota_docker_stats(host: Host) -> None:
    stats = host.raiz / "stats.log"

    resultado = host.correr(
        "checks.sh",
        DOMAIN="shifty.example.com",
        FAKE_CERT_END=_fecha_en(60),
        STATS_LOG=stats.as_posix(),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "ALERTA" not in resultado.stderr
    assert "shifty-backend-1" in stats.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("extra", "motivo"),
    [
        ({"FAKE_NTP": "no"}, "NTP"),
        ({"FAKE_CERT_END": _fecha_en(10)}, "certificado"),
        ({"FAKE_CERT_END": ""}, "certificado"),
        ({"FAKE_DISK_USE": "81"}, "disco"),
        ({"FAKE_MEM_PERC": "95.1%"}, "memoria"),
    ],
    ids=["ntp", "cert-por-vencer", "cert-ilegible", "disco", "memoria-contenedor"],
)
def test_checks_alerta_cada_problema(
    host: Host, extra: dict[str, str], motivo: str
) -> None:
    base = {"DOMAIN": "shifty.example.com", "FAKE_CERT_END": _fecha_en(60)}
    base.update(extra)

    resultado = host.correr(
        "checks.sh", STATS_LOG=(host.raiz / "stats.log").as_posix(), **base
    )

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr
    assert motivo in resultado.stderr


# --- cron y logrotate --------------------------------------------------------


def test_los_archivos_de_cron_no_llevan_punto_en_el_nombre() -> None:
    """cron.d ignora en silencio los archivos con punto en el nombre."""
    archivos = sorted((DEPLOY / "cron").iterdir())
    assert archivos
    for archivo in archivos:
        assert "." not in archivo.name, archivo.name


def test_cron_del_guard_corre_cada_minuto_como_root() -> None:
    lineas = _lineas_de_cron("shifty-guard")
    guard = next(ll for ll in lineas if "guard.sh" in ll)
    assert guard.split()[:6] == ["*", "*", "*", "*", "*", "root"]
    checks = next(ll for ll in lineas if "checks.sh" in ll)
    assert checks.split()[1:5] == ["*", "*", "*", "*"] and checks.split()[5] == "root"
    assert any("backup-check.sh" in ll for ll in lineas)


def test_logrotate_cubre_los_logs_de_los_scripts() -> None:
    texto = (DEPLOY / "logrotate" / "shifty").read_text(encoding="utf-8")
    assert "/var/log/shifty/*.log" in texto
    assert "rotate" in texto and "copytruncate" in texto


# --- scripts/cert-deploy-hook.sh: renovacion de certbot ------------------------


def test_el_hook_de_certbot_copia_los_certificados_y_recarga_el_borde(
    host: Host,
) -> None:
    """Se COPIAN (no symlink): ./nginx/certs se monta en el contenedor y un
    symlink a /etc/letsencrypt/live apuntaria a una ruta que adentro no
    existe. La recarga necesita APP_VERSION: el compose de prod la exige."""
    linaje = host.raiz / "letsencrypt" / "live" / "shifty.example.com"
    linaje.mkdir(parents=True)
    (linaje / "fullchain.pem").write_text("CADENA\n", encoding="utf-8")
    (linaje / "privkey.pem").write_text("CLAVE\n", encoding="utf-8")
    (host.repo / "nginx" / "certs").mkdir(parents=True)
    (host.repo / ".deploy").mkdir()
    (host.repo / ".deploy" / "current").write_text("v7\n", encoding="utf-8")

    resultado = host.correr(
        "cert-deploy-hook.sh",
        RENEWED_LINEAGE=linaje.as_posix(),
        FAKE_EXIGE_VERSION="1",
    )

    assert resultado.returncode == 0, resultado.stderr
    certs = host.repo / "nginx" / "certs"
    assert not (certs / "fullchain.pem").is_symlink()
    assert (certs / "fullchain.pem").read_text(encoding="utf-8") == "CADENA\n"
    assert (certs / "privkey.pem").read_text(encoding="utf-8") == "CLAVE\n"
    llamadas = host.llamadas()
    assert _hay(llamadas, r"compose exec -T nginx nginx -t")
    assert _hay(llamadas, r"compose exec -T nginx nginx -s reload")


def test_el_hook_de_certbot_sin_linaje_falla(host: Host) -> None:
    resultado = host.correr("cert-deploy-hook.sh")

    assert resultado.returncode != 0
    assert "RENEWED_LINEAGE" in resultado.stderr
