"""Host falso para probar los scripts de operacion (scripts/*.sh, Fase 0).

2026-09-24. Hasta aca no habia backup programado (el drill mensual nunca
corrio), ni rollback (imagenes sin version), ni quien reiniciara un contenedor
`unhealthy` (`restart: always` no actua sobre eso), ni quien mirara el reloj,
el certificado o el disco (R11-02, R11-03, R11-05, R11-17, R11-20).

Los scripts corren en el VPS, pero su logica se prueba aca: cada test levanta
el script REAL con `bash` y un PATH con binarios falsos (`docker`, `curl`,
`rclone`, `df`, `timedatectl`, `openssl`, `sleep`) que anotan cada llamada en
un archivo. Se afirma sobre el ORDEN y la presencia de esas llamadas: migrar
antes de recrear, no migrar en el rollback, no pasar de 3 reinicios por hora,
no marcar exito si la copia fuera del host fallo.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
DEPLOY = REPO_ROOT / "deploy"


def _bash() -> str | None:
    """El bash de Git en Windows (no el de WSL en System32); el del sistema en
    Linux."""
    sh = shutil.which("sh")
    if sh:
        hermano = Path(sh).with_name("bash.exe" if os.name == "nt" else "bash")
        if hermano.exists():
            return str(hermano)
    return shutil.which("bash")


BASH = _bash()
requiere_bash = pytest.mark.skipif(BASH is None, reason="hace falta bash")


# --- binarios falsos --------------------------------------------------------

_DOCKER = r"""#!/bin/sh
echo "docker $*" >> "$FAKE_DIR/calls"
ids_backend="$FAKE_DIR/backend_ids"
if [ "$1" = compose ]; then
  # docker-compose.prod.yml interpola ${APP_VERSION:?...}: sin la variable,
  # TODO comando de compose falla, no solo `up`.
  if [ -n "${FAKE_EXIGE_VERSION:-}" ] && [ -z "${APP_VERSION:-}" ]; then
    echo 'required variable APP_VERSION is missing a value' >&2
    exit 15
  fi
  # Directorio desde el que se hablo con compose (el proyecto sale de ahi).
  (pwd -W 2>/dev/null || pwd) > "$FAKE_DIR/cwd"
  shift
  case "$1" in
    version) echo "${FAKE_COMPOSE_VERSION:-2.29.1}"; exit 0 ;;
    config)
      if [ "$2" = --services ]; then
        for s in ${FAKE_SERVICES:-db redis_cache redis_state rabbitmq backend celery_worker celery_worker_interactive celery_beat frontend nginx}; do echo "$s"; done
        exit 0
      fi
      if [ "$2" = --images ]; then
        shift 2
        for s in "$@"; do
          case "$s" in
            nginx) echo "${FAKE_NGINX_IMAGE:-nginx:1.27.5-alpine}" ;;
            *) echo "ghcr.io/x/shifty-$s:$APP_VERSION" ;;
          esac
        done
        exit 0
      fi
      exit "${FAKE_CONFIG_EXIT:-0}" ;;
    ps)
      case "$*" in
        *" backend"*) cat "$ids_backend" 2>/dev/null; exit 0 ;;
        *" db"*) [ -n "${FAKE_DB_DOWN:-}" ] || echo dbid; exit 0 ;;
        *" nginx"*) echo nginxid; exit 0 ;;
        *) echo dbid; cat "$ids_backend" 2>/dev/null; echo nginxid; exit 0 ;;
      esac ;;
    pull) exit "${FAKE_PULL_EXIT:-0}" ;;
    run) exit "${FAKE_MIGRATE_EXIT:-0}" ;;
    up)
      escala=$(echo "$*" | sed -n 's/.*--scale backend=\([0-9]*\).*/\1/p')
      if [ -n "$escala" ]; then
        actuales=$(grep -c . "$ids_backend" 2>/dev/null || true)
        n=${actuales:-0}
        while [ "$n" -lt "$escala" ]; do
          n=$((n + 1)); echo "new$n-$APP_VERSION" >> "$ids_backend"
        done
        exit "${FAKE_UP_BACKEND_EXIT:-0}"
      fi
      exit "${FAKE_UP_EXIT:-0}" ;;
    exec)
      if [ "$3" = db ]; then
        # pg_dump escribe en /backups del contenedor = BACKUP_DIR del host.
        for ultimo in "$@"; do :; done
        destino="$BACKUP_DIR${ultimo#/backups}"
        mkdir -p "$destino"
        echo toc > "$destino/toc.dat"
        exit "${FAKE_PG_DUMP_EXIT:-0}"
      fi
      exit "${FAKE_NGINX_EXIT:-0}" ;;
    logs) cat "$FAKE_DIR/nginx.log" 2>/dev/null; exit 0 ;;
    *) exit 0 ;;
  esac
fi
case "$1" in
  ps) for id in ${FAKE_UNHEALTHY_IDS:-}; do echo "$id"; done ;;
  image)
    # docker image inspect [-f FORMATO] IMAGEN
    for imagen in "$@"; do :; done
    if [ -n "${FAKE_MISSING_TAG:-}" ] && [ "${imagen##*:}" = "$FAKE_MISSING_TAG" ]; then
      echo "Error: No such image: $imagen" >&2
      exit 1
    fi
    case "$*" in *.Id*) echo "${FAKE_IMAGE_ID:-sha256:igual}" ;; esac ;;
  inspect)
    formato="$3"; shift 3
    for id in "$@"; do
      # Servicio por convencion de nombre: shifty-<servicio>-<n>.
      svc="${id%-[0-9]*}"; svc="${svc#shifty-}"
      case "$formato" in
        *Config.Image*) echo "ghcr.io/x/shifty-backend:${FAKE_RUNNING_VERSION:-}" ;;
        *compose.service*) echo "/$id $svc" ;;
        *Health*) echo "/$id ${FAKE_HEALTH:-healthy}" ;;
        *.Image*) echo "${FAKE_RUNNING_IMAGE_ID:-sha256:igual}" ;;
        *) echo "/$id" ;;
      esac
    done ;;
  rm)
    shift
    for id in "$@"; do
      [ "$id" = -f ] && continue
      grep -v -x "$id" "$ids_backend" > "$ids_backend.tmp" 2>/dev/null || true
      mv "$ids_backend.tmp" "$ids_backend"
    done ;;
  restart) exit "${FAKE_RESTART_EXIT:-0}" ;;
  stats) printf 'shifty-backend-1\t1.5%%\t120MiB / 512MiB\t%s\t1kB / 2kB\t0B / 0B\t12\n' "${FAKE_MEM_PERC:-23.4%}" ;;
esac
exit 0
"""

_REGISTRA = r"""#!/bin/sh
echo "{nombre} $*" >> "$FAKE_DIR/calls"
exit "${{{variable}:-0}}"
"""

_DF = r"""#!/bin/sh
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/sda1 100 50 50 ${FAKE_DISK_USE:-42}% /"
"""

_TIMEDATECTL = r"""#!/bin/sh
echo "${FAKE_NTP:-yes}"
"""

_OPENSSL = r"""#!/bin/sh
case "$1" in
  s_client) cat > /dev/null; echo "-----BEGIN CERTIFICATE-----" ;;
  x509) cat > /dev/null; [ -n "${FAKE_CERT_END:-}" ] && echo "notAfter=$FAKE_CERT_END" ;;
esac
exit 0
"""


@dataclass
class Host:
    raiz: Path
    fake: Path
    repo: Path
    state: Path
    backups: Path
    env: dict[str, str]

    def llamadas(self) -> list[str]:
        archivo = self.fake / "calls"
        if not archivo.exists():
            return []
        return archivo.read_text(encoding="utf-8").splitlines()

    def correr(
        self, script: str, *args: str, **extra: str
    ) -> subprocess.CompletedProcess[str]:
        return self.correr_desde(self.repo, script, *args, **extra)

    def correr_desde(
        self, cwd: Path, script: str, *args: str, **extra: str
    ) -> subprocess.CompletedProcess[str]:
        """Como `correr`, pero con otro directorio actual."""
        assert BASH is not None
        return subprocess.run(
            [BASH, str(SCRIPTS / script), *args],
            cwd=cwd,
            env={**self.env, **extra},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


def _ejecutable(ruta: Path, contenido: str) -> None:
    ruta.write_text(contenido, encoding="utf-8", newline="\n")
    ruta.chmod(0o755)


def crear_host(tmp_path: Path) -> Host:
    """Arma el host falso; cada archivo de tests lo expone como fixture `host`."""
    if BASH is None:
        pytest.skip("hace falta bash")
    fake = tmp_path / "fake"
    bin_dir = tmp_path / "bin"
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    backups = tmp_path / "backups"
    for d in (fake, bin_dir, repo, state, backups):
        d.mkdir()
    _ejecutable(bin_dir / "docker", _DOCKER)
    for nombre, variable in (
        ("curl", "FAKE_CURL_EXIT"),
        ("rclone", "FAKE_RCLONE_EXIT"),
        ("sleep", "FAKE_SLEEP_EXIT"),
        ("logger", "FAKE_LOGGER_EXIT"),
    ):
        _ejecutable(
            bin_dir / nombre, _REGISTRA.format(nombre=nombre, variable=variable)
        )
    _ejecutable(bin_dir / "df", _DF)
    _ejecutable(bin_dir / "timedatectl", _TIMEDATECTL)
    _ejecutable(bin_dir / "openssl", _OPENSSL)
    # Git Bash en Windows: /usr/bin (find, sort, sha256sum de GNU) antes que
    # System32, donde `find` es otro programa.
    herramientas = str(Path(BASH).parent)
    env = {
        **os.environ,
        "PATH": os.pathsep.join(
            [str(bin_dir), herramientas, os.environ.get("PATH", "")]
        ),
        "FAKE_DIR": fake.as_posix(),
        "SHIFTY_OPS_ENV": (tmp_path / "no-existe.env").as_posix(),
        "SHIFTY_DIR": repo.as_posix(),
        "SHIFTY_STATE_DIR": state.as_posix(),
        "BACKUP_DIR": backups.as_posix(),
        "COMPOSE_PROJECT_NAME": "shifty",
    }
    for variable in (
        "APP_VERSION",
        "DOMAIN",
        "ALERT_WEBHOOK_URL",
        "ALERT_EMAIL",
        "COMPOSE_FILE",
    ):
        env.pop(variable, None)
    return Host(tmp_path, fake, repo, state, backups, env)


def _indice(llamadas: list[str], patron: str) -> int:
    for i, llamada in enumerate(llamadas):
        if re.search(patron, llamada):
            return i
    raise AssertionError(
        f"no hubo llamada que matchee {patron!r}:\n" + "\n".join(llamadas)
    )


def _ultimo_indice(llamadas: list[str], patron: str) -> int:
    return len(llamadas) - 1 - _indice(list(reversed(llamadas)), patron)


def _hay(llamadas: list[str], patron: str) -> bool:
    return any(re.search(patron, llamada) for llamada in llamadas)


def _backup_fresco(host: Host, horas: float = 1) -> None:
    host.backups.mkdir(exist_ok=True)
    epoch = int(time.time() - horas * 3600)
    (host.backups / "last-success").write_text(f"{epoch} prueba\n", encoding="utf-8")


def _lineas_de_cron(nombre: str) -> list[str]:
    texto = (DEPLOY / "cron" / nombre).read_text(encoding="utf-8")
    assert "\r" not in texto
    assert texto.endswith("\n"), "cron ignora la ultima linea sin salto"
    return [
        linea
        for linea in texto.splitlines()
        if linea.strip() and not linea.startswith("#") and "=" not in linea.split()[0]
    ]
