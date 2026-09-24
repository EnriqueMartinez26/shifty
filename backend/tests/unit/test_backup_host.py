"""scripts/backup.sh y scripts/backup-check.sh: backup diario (F0-20, 2026-09-24).

No habia ningun backup programado en el host y el drill mensual nunca corrio
(R11-17). Se corren los scripts REALES con binarios falsos
(tests/unit/host_falso.py): pg_dump dentro del contenedor con el rol dueno,
copia fuera del host antes de marcar exito, retencion por cantidad y alerta
pasadas 26 h.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.host_falso import (
    DEPLOY,
    Host,
    _backup_fresco,
    _hay,
    _indice,
    crear_host,
)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return crear_host(tmp_path)


def _correr_backup(host: Host, **extra: str) -> subprocess.CompletedProcess[str]:
    entorno = {"BACKUP_REMOTE": "r2:shifty-backups/prod", "BACKUP_WEEKLY_DAY": "0"}
    return host.correr("backup.sh", **{**entorno, **extra})


def test_backup_vuelca_con_pg_dump_directorio_y_copia_fuera_del_host(
    host: Host,
) -> None:
    resultado = _correr_backup(host)

    assert resultado.returncode == 0, resultado.stderr
    llamadas = host.llamadas()
    dump = _indice(
        llamadas,
        r"docker compose exec -T db sh -c .*pg_dump .*-Fd.*-j.*--compress",
    )
    copia = _indice(llamadas, r"rclone copy .* r2:shifty-backups/prod/daily/shifty-")
    poda = _indice(llamadas, r"rclone delete --min-age 7d r2:shifty-backups/prod/daily")
    assert dump < copia < poda
    assert _hay(llamadas, r"rclone delete --min-age 28d r2:shifty-backups/prod/weekly")
    # pg_dump usa las variables DEL CONTENEDOR (rol dueno por socket local):
    # el host no lee el .env ni una URL de la app.
    linea = llamadas[dump]
    assert "$POSTGRES_USER" in linea and "$POSTGRES_DB" in linea
    assert "DATABASE_URL" not in linea
    ultimo = (host.backups / "last-success").read_text().split()
    assert abs(int(ultimo[0]) - time.time()) < 120


def test_backup_escribe_el_sha256_de_cada_archivo(host: Host) -> None:
    _correr_backup(host)

    dumps = [d for d in (host.backups / "daily").glob("shifty-*") if d.is_dir()]
    assert len(dumps) == 1
    dump = dumps[0]
    esperado = hashlib.sha256((dump / "toc.dat").read_bytes()).hexdigest()
    lineas = (dump / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    # Una linea por archivo del dump, con su hash real; el propio SHA256SUMS
    # no se lista (su hash no puede estar adentro de si mismo). El separador
    # es "  " (modo texto, Linux) o " *" (modo binario, sha256sum de Windows):
    # `sha256sum -c` acepta los dos.
    assert len(lineas) == 1
    assert re.fullmatch(rf"{esperado} [ *]\./toc\.dat", lineas[0]), lineas


def test_backup_sin_destino_remoto_no_marca_exito(host: Host) -> None:
    resultado = host.correr("backup.sh", BACKUP_WEEKLY_DAY="0")

    assert resultado.returncode != 0
    assert "BACKUP_REMOTE" in resultado.stderr
    assert not (host.backups / "last-success").exists()


def test_backup_con_copia_remota_fallida_alerta_y_no_marca_exito(host: Host) -> None:
    resultado = _correr_backup(host, FAKE_RCLONE_EXIT="1")

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr
    assert not (host.backups / "last-success").exists()


def test_backup_con_pg_dump_fallido_no_copia_ni_marca_exito(host: Host) -> None:
    resultado = _correr_backup(host, FAKE_PG_DUMP_EXIT="1")

    assert resultado.returncode != 0
    assert not _hay(host.llamadas(), r"rclone")
    assert not (host.backups / "last-success").exists()
    # No queda un directorio a medias que la poda cuente como backup.
    assert not list((host.backups / "daily").glob("shifty-*"))


def test_backup_conserva_los_ultimos_siete_diarios(host: Host) -> None:
    daily = host.backups / "daily"
    daily.mkdir()
    for dia in range(1, 10):
        (daily / f"shifty-202609{dia:02d}T060000Z").mkdir()

    _correr_backup(host)

    restantes = sorted(p.name for p in daily.iterdir() if p.is_dir())
    assert len(restantes) == 7
    assert "shifty-20260901T060000Z" not in restantes
    assert "shifty-20260903T060000Z" not in restantes
    assert "shifty-20260904T060000Z" in restantes


def test_backup_el_dia_semanal_guarda_una_copia_semanal(host: Host) -> None:
    hoy = time.strftime("%u", time.gmtime())

    resultado = _correr_backup(host, BACKUP_WEEKLY_DAY=hoy)

    assert resultado.returncode == 0, resultado.stderr
    semanales = list((host.backups / "weekly").glob("shifty-*"))
    assert len(semanales) == 1
    assert _hay(host.llamadas(), r"rclone copy .*/weekly/shifty-")


# --- backup-check.sh --------------------------------------------------------


def test_backup_check_callado_con_un_backup_reciente(host: Host) -> None:
    _backup_fresco(host, horas=2)

    resultado = host.correr("backup-check.sh")

    assert resultado.returncode == 0
    assert "ALERTA" not in resultado.stderr


def test_backup_check_alerta_pasadas_26_horas(host: Host) -> None:
    _backup_fresco(host, horas=27)

    resultado = host.correr("backup-check.sh")

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr


def test_backup_check_alerta_si_nunca_hubo_backup(host: Host) -> None:
    resultado = host.correr("backup-check.sh")

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr


# --- systemd y configuracion del host ----------------------------------------


def test_timer_del_backup_a_las_tres_de_argentina() -> None:
    timer = (DEPLOY / "systemd" / "shifty-backup.timer").read_text(encoding="utf-8")
    servicio = (DEPLOY / "systemd" / "shifty-backup.service").read_text(
        encoding="utf-8"
    )
    # 03:00 America/Argentina/Buenos_Aires = 06:00 UTC (sin horario de verano).
    assert re.search(r"^OnCalendar=\*-\*-\* 06:00:00 UTC$", timer, re.MULTILINE)
    assert re.search(r"^Persistent=true$", timer, re.MULTILINE)
    assert re.search(r"^Type=oneshot$", servicio, re.MULTILINE)
    assert re.search(r"^ExecStart=/bin/bash \S+/scripts/backup\.sh$", servicio, re.M)


def test_el_ejemplo_de_ops_env_no_trae_secretos_reales() -> None:
    texto = (DEPLOY / "ops.env.example").read_text(encoding="utf-8")
    for clave in ("BACKUP_REMOTE", "ALERT_EMAIL", "ALERT_WEBHOOK_URL", "DOMAIN"):
        assert re.search(rf"^#?\s*{clave}=", texto, re.MULTILINE), clave
    assert not re.search(r"hooks\.slack\.com/services/T", texto)


def test_backup_usa_la_version_en_curso_para_hablar_con_compose(host: Host) -> None:
    """Desde cron no hay APP_VERSION y docker-compose.prod.yml la exige
    (${APP_VERSION:?}): sin tomarla de .deploy/current, `compose exec db`
    fallaria todas las noches."""
    (host.repo / ".deploy").mkdir()
    (host.repo / ".deploy" / "current").write_text("v7\n", encoding="utf-8")

    resultado = _correr_backup(host, FAKE_EXIGE_VERSION="1")

    assert resultado.returncode == 0, resultado.stderr


def test_backup_sin_version_en_curso_falla_con_alerta(host: Host) -> None:
    resultado = _correr_backup(host, FAKE_EXIGE_VERSION="1")

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr
