"""Host falso para probar los scripts de operacion (scripts/*.sh, Fase 0).

2026-09-24. Hasta aca no habia backup programado (el drill mensual nunca
corrio), ni rollback (imagenes sin version), ni quien reiniciara un contenedor
`unhealthy` (`restart: always` no actua sobre eso), ni quien mirara el reloj,
el certificado o el disco (R11-02, R11-03, R11-05, R11-17, R11-20).

Los scripts corren en el VPS, pero su logica se prueba aca: cada test levanta
el script REAL con `bash` y un PATH con binarios falsos (`docker`, `curl`,
`rclone`, `df`, `timedatectl`, `openssl`, `sleep`, `sshd`, `ufw`, `apt-config`,
`fail2ban-client`) que anotan cada llamada en
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
#
# Los falsos anotan sus argumentos con `printf '%s\n'`, nunca con `echo`: en
# Linux `/bin/sh` es dash, cuyo `echo` interpreta `\n` y compania. El JSON de
# una alerta lleva `\n` escapado; con `echo` la llamada a curl quedaba partida
# en dos lineas de `calls` y el test del guard fallaba solo en CI (2026-09-26).
# En Git Bash `sh` es bash, que no interpreta: por eso pasaba en Windows.

_DOCKER = r"""#!/bin/sh
printf '%s\n' "docker $*" >> "$FAKE_DIR/calls"
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
            nginx) echo "${FAKE_NGINX_IMAGE:-nginx:1.30.5-alpine}" ;;
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
      escala=$(printf '%s\n' "$*" | sed -n 's/.*--scale backend=\([0-9]*\).*/\1/p')
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
        case "$*" in
          *pg_dumpall*)
            # Los globales salen por stdout; backup.sh los redirige al host.
            echo "CREATE ROLE shifty_app;"
            echo "ALTER ROLE shifty_app SET statement_timeout TO '30s';"
            exit "${FAKE_PG_DUMPALL_EXIT:-0}" ;;
        esac
        # pg_dump escribe en /backups del contenedor = BACKUP_DIR del host.
        for ultimo in "$@"; do :; done
        destino="$BACKUP_DIR${ultimo#/backups}"
        mkdir -p "$destino"
        echo toc > "$destino/toc.dat"
        exit "${FAKE_PG_DUMP_EXIT:-0}"
      fi
      if [ "$3" = redis_state ]; then
        # redis-cli INFO memory; checks.sh lee used_memory y maxmemory.
        cat "$FAKE_DIR/redis_info" 2>/dev/null
        exit "${FAKE_REDIS_EXIT:-0}"
      fi
      if [ "$3" = rabbitmq ]; then
        printf '%s
' "${FAKE_RABBIT_ALARMS:-[]}"
        exit "${FAKE_RABBIT_EXIT:-0}"
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
printf '%s\n' "{nombre} $*" >> "$FAKE_DIR/calls"
exit "${{{variable}:-0}}"
"""

# curl: la API de GitHub (deploy.sh pregunta si Quality paso para el sha)
# contesta lo que diga gh_runs, con su propio codigo de salida; el resto
# (compuerta, alertas) sale con FAKE_CURL_EXIT, como siempre.
_CURL = r"""#!/bin/sh
printf '%s\n' "curl $*" >> "$FAKE_DIR/calls"
case "$*" in
  *api.github.com/*/actions/workflows/*)
    cat "$FAKE_DIR/gh_runs" 2>/dev/null
    exit "${FAKE_GH_EXIT:-0}" ;;
esac
exit "${FAKE_CURL_EXIT:-0}"
"""

# Endurecimiento del host (scripts/host-hardening-check.sh). Cada falso
# devuelve el archivo homonimo de FAKE_DIR; crear_host deja el host sano.
_DESDE_ARCHIVO = r"""#!/bin/sh
printf '%s\n' "{nombre} $*" >> "$FAKE_DIR/calls"
cat "$FAKE_DIR/{archivo}" 2>/dev/null
exit "${{{variable}:-0}}"
"""

# `sshd -T` (minusculas, como lo imprime OpenSSH) del host endurecido.
SSHD_SANO = (
    "port 22\n"
    "permitrootlogin no\n"
    "pubkeyauthentication yes\n"
    "passwordauthentication no\n"
    "kbdinteractiveauthentication no\n"
)
# `ufw status verbose` con solo 22, 80 y 443 abiertos.
UFW_SANO = (
    "Status: active\n"
    "Logging: on (low)\n"
    "Default: deny (incoming), allow (outgoing), disabled (routed)\n"
    "New profiles: skip\n"
    "\n"
    "To                         Action      From\n"
    "--                         ------      ----\n"
    "22/tcp                     ALLOW IN    Anywhere\n"
    "80/tcp                     ALLOW IN    Anywhere\n"
    "443/tcp                    ALLOW IN    Anywhere\n"
    "22/tcp (v6)                ALLOW IN    Anywhere (v6)\n"
    "80/tcp (v6)                ALLOW IN    Anywhere (v6)\n"
    "443/tcp (v6)               ALLOW IN    Anywhere (v6)\n"
)
# `apt-config dump` (lo relevante) de un Ubuntu con unattended-upgrades de
# fabrica: solo el bolsillo de la version y los de seguridad.
APT_SANO = (
    'APT::Periodic::Update-Package-Lists "1";\n'
    'APT::Periodic::Unattended-Upgrade "1";\n'
    'Unattended-Upgrade::Allowed-Origins "";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}ESMApps:${distro_codename}-apps-security";\n'
    'Unattended-Upgrade::Automatic-Reboot "false";\n'
)


def escribir_redis_info(ruta: Path, *, usada: int, maxima: int = 48 * 1048576) -> None:
    """Lo que devuelve `redis-cli INFO memory` (lineas con CRLF, como Redis).
    Por defecto, el maxmemory de redis_state (48mb)."""
    ruta.write_bytes(
        (
            "# Memory\r\n"
            f"used_memory:{usada}\r\n"
            f"used_memory_human:{usada / 1048576:.2f}M\r\n"
            f"maxmemory:{maxima}\r\n"
            f"maxmemory_human:{maxima / 1048576:.2f}M\r\n"
            "maxmemory_policy:noeviction\r\n"
        ).encode()
    )


def escribir_corridas_de_quality(ruta: Path, *, verdes: int) -> None:
    """Respuesta de la API de GitHub a la busqueda de corridas verdes de
    Quality, indentada como la devuelve api.github.com."""
    corrida = (
        '    {\n      "conclusion": "success",\n      "head_branch": "main"\n    }\n'
    )
    ruta.write_text(
        f'{{\n  "total_count": {verdes},\n  "workflow_runs": [\n'
        f"{corrida if verdes else ''}  ]\n}}\n",
        encoding="utf-8",
        newline="\n",
    )


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


# --- flags que entiende Compose ---------------------------------------------
#
# 2026-10-02: `scripts/deploy.sh` migraba con `compose run ... --no-build`, un
# flag que `docker compose run` no tuvo nunca (solo `up`/`create`): Compose
# 5.5.1 frena con "unknown flag: --no-build" y el deploy muere al migrar. El
# `docker` falso aceptaba cualquier cosa y el test afirmaba ese mismo string,
# asi que no podia verlo. Ahora cada llamada a compose que hacen los scripts
# se valida contra los flags de la version MINIMA soportada (Compose 2.24.0,
# DEPLOY_MIN_COMPOSE): lo que entienda la minima lo entienden las siguientes.
# Fuente: docker/compose v2.24.0, cmd/compose/{up,create,run,exec,config,ps,
# pull,logs,version}.go. Un flag nuevo en un script va aca solo si existe en
# esa version (`--pull` de `run` aparecio recien en 2.33.0).
#
# Por subcomando: (flags booleanos, flags con valor). Largo y corto, sin guion.
_GLOBALES: tuple[set[str], set[str]] = ({"dry-run"}, set())
_FLAGS_COMPOSE_2_24: dict[str, tuple[set[str], set[str]]] = {
    "up": (
        {
            "detach",
            "d",
            "build",
            "no-build",
            "remove-orphans",
            "no-color",
            "no-log-prefix",
            "force-recreate",
            "no-recreate",
            "no-start",
            "abort-on-container-exit",
            "timestamps",
            "no-deps",
            "always-recreate-deps",
            "renew-anon-volumes",
            "V",
            "quiet-pull",
            "attach-dependencies",
            "wait",
        },
        {
            "pull",
            "scale",
            "exit-code-from",
            "timeout",
            "t",
            "attach",
            "no-attach",
            "wait-timeout",
        },
    ),
    "run": (
        {
            "detach",
            "d",
            "rm",
            "no-TTY",
            "T",
            "no-deps",
            "use-aliases",
            "service-ports",
            "P",
            "quiet-pull",
            "build",
            "remove-orphans",
            "interactive",
            "i",
            "tty",
            "t",
        },
        {
            "env",
            "e",
            "label",
            "l",
            "name",
            "user",
            "u",
            "workdir",
            "w",
            "entrypoint",
            "cap-add",
            "cap-drop",
            "volume",
            "v",
            "publish",
            "p",
        },
    ),
    "exec": (
        {"detach", "d", "privileged", "no-TTY", "T", "interactive", "i", "tty", "t"},
        {"env", "e", "index", "user", "u", "workdir", "w"},
    ),
    "config": (
        {
            "resolve-image-digests",
            "quiet",
            "q",
            "no-interpolate",
            "no-normalize",
            "no-path-resolution",
            "no-consistency",
            "services",
            "volumes",
            "profiles",
            "images",
        },
        {"format", "hash", "output", "o"},
    ),
    "ps": (
        {"quiet", "q", "services", "orphans", "all", "a", "no-trunc"},
        {"format", "filter", "status"},
    ),
    "pull": (
        {
            "quiet",
            "q",
            "include-deps",
            "parallel",
            "no-parallel",
            "ignore-pull-failures",
            "ignore-buildable",
        },
        {"policy"},
    ),
    "logs": (
        {"follow", "f", "no-color", "no-log-prefix", "timestamps", "t"},
        {"index", "since", "until", "tail", "n"},
    ),
    "version": ({"short"}, {"format", "f"}),
}
# `run` y `exec` cortan los flags en el primer argumento suelto (el servicio):
# lo que sigue es el comando del contenedor. El resto los acepta en cualquier
# lugar (por defecto cobra intercala flags y argumentos).
_SIN_INTERCALAR = {"run", "exec"}


def flags_rechazados_por_compose(argumentos: list[str]) -> list[str]:
    """Los flags de `docker compose <argumentos>` que Compose 2.24 rechaza.

    `argumentos` empieza en el subcomando (sin `docker compose`). Un
    subcomando que los scripts no usan no se valida."""
    if not argumentos or argumentos[0] not in _FLAGS_COMPOSE_2_24:
        return []
    subcomando, resto = argumentos[0], argumentos[1:]
    booleanos = _FLAGS_COMPOSE_2_24[subcomando][0] | _GLOBALES[0]
    con_valor = _FLAGS_COMPOSE_2_24[subcomando][1] | _GLOBALES[1]
    rechazados: list[str] = []
    i = 0
    while i < len(resto):
        arg = resto[i]
        i += 1
        if arg == "--":
            break
        if not arg.startswith("-") or arg == "-":
            if subcomando in _SIN_INTERCALAR:
                break
            continue
        if arg.startswith("--"):
            nombre, igual, _ = arg[2:].partition("=")
            if nombre in con_valor:
                i += 0 if igual else 1
            elif nombre not in booleanos:
                rechazados.append(f"{subcomando} --{nombre}")
            continue
        # Cortos, quiza juntos (`-dT`); uno con valor se come el resto.
        cortos = arg[1:]
        for j, letra in enumerate(cortos):
            if letra in con_valor:
                i += 0 if cortos[j + 1 :] else 1
                break
            if letra not in booleanos:
                rechazados.append(f"{subcomando} -{letra}")
    return rechazados


def _llamadas_con_flags_invalidos(llamadas: list[str]) -> list[str]:
    malas = []
    for llamada in llamadas:
        partes = llamada.split()
        if partes[:2] == ["docker", "compose"]:
            rechazados = flags_rechazados_por_compose(partes[2:])
            if rechazados:
                malas.append(f"{llamada}  <- {', '.join(rechazados)}")
    return malas


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
        """Como `correr`, pero con otro directorio actual.

        Falla si el script le paso a compose un flag que Compose 2.24 no
        entiende: el `docker` falso lo aceptaria y el real no."""
        assert BASH is not None
        resultado = subprocess.run(
            [BASH, str(SCRIPTS / script), *args],
            cwd=cwd,
            env={**self.env, **extra},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        malas = _llamadas_con_flags_invalidos(self.llamadas())
        assert not malas, "flags que `docker compose` 2.24 no acepta:\n" + "\n".join(
            malas
        )
        return resultado


def _ejecutable(ruta: Path, contenido: str) -> None:
    ruta.write_text(contenido, encoding="utf-8", newline="\n")
    ruta.chmod(0o755)


def escribir_meminfo(
    ruta: Path,
    *,
    total_mib: int = 7936,
    disponible_mib: int = 2048,
    swap_mib: int = 2048,
    swap_libre_mib: int = 2048,
) -> None:
    """Un /proc/meminfo con los campos que lee checks.sh (en kB, como el
    kernel). Por defecto, el VPS de 8 GB sano: 2 GiB disponibles y swap sin
    usar."""
    ruta.write_text(
        f"MemTotal:       {total_mib * 1024} kB\n"
        f"MemFree:        {disponible_mib * 512} kB\n"
        f"MemAvailable:   {disponible_mib * 1024} kB\n"
        f"SwapTotal:      {swap_mib * 1024} kB\n"
        f"SwapFree:       {swap_libre_mib * 1024} kB\n",
        encoding="utf-8",
        newline="\n",
    )


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
    _ejecutable(bin_dir / "curl", _CURL)
    for nombre, variable in (
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
    # checks.sh lee la memoria del host de aca, no del /proc/meminfo de la
    # maquina que corre los tests: un runner con poca memoria libre no puede
    # volver rojo un test.
    escribir_meminfo(fake / "meminfo")
    for nombre, archivo, variable, contenido in (
        ("sshd", "sshd_T", "FAKE_SSHD_EXIT", SSHD_SANO),
        ("ufw", "ufw_status", "FAKE_UFW_EXIT", UFW_SANO),
        ("apt-config", "apt_config", "FAKE_APT_EXIT", APT_SANO),
        ("fail2ban-client", "fail2ban", "FAKE_FAIL2BAN_EXIT", ""),
    ):
        _ejecutable(
            bin_dir / nombre,
            _DESDE_ARCHIVO.format(nombre=nombre, archivo=archivo, variable=variable),
        )
        (fake / archivo).write_text(contenido, encoding="utf-8", newline="\n")
    # redis_state al 20 % de sus 48 MB.
    escribir_redis_info(fake / "redis_info", usada=10 * 1048576)
    # El sha que se despliega paso Quality en main.
    escribir_corridas_de_quality(fake / "gh_runs", verdes=1)
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
        "HOST_MEMINFO": (fake / "meminfo").as_posix(),
        # El runner puede tener su propio /var/run/reboot-required.
        "HARDENING_REBOOT_FLAG": (fake / "reboot-required").as_posix(),
    }
    for variable in (
        "APP_VERSION",
        "DOMAIN",
        "ALERT_WEBHOOK_URL",
        "ALERT_EMAIL",
        "COMPOSE_FILE",
        "DEPLOY_SKIP_QUALITY_CHECK",
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
