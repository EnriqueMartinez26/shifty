"""scripts/guard.sh y scripts/checks.sh: guard y chequeos del host (F0-21, F0-23).

2026-09-24. `restart: always` no actua sobre un contenedor `unhealthy`, y nadie
miraba el reloj, el certificado ni el disco (R11-05, R11-20). Se corren los
scripts REALES con binarios falsos (tests/unit/host_falso.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.host_falso import (
    BASH,
    DEPLOY,
    SCRIPTS,
    SSHD_SANO,
    Host,
    _hay,
    _lineas_de_cron,
    con_hora_utc,
    crear_host,
    escribir_meminfo,
    escribir_redis_info,
    sin_espacio_para_crear,
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
    # El salto entre asunto y detalle viaja escapado: el JSON va en una linea.
    assert _hay(llamadas, r"curl .*guard: reinicie abc123 \(unhealthy\)\\nReinicio 1")


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


# --- incidente 2026-11-13: dockerd colgado y tormenta de alertas ---------------
# De 15:10 a 17:07 UTC dockerd no contestaba (healthchecks vencidos, KILL que
# fallaba). El guard corria cada minuto sin lock ni tope de tiempo: cada corrida
# quedaba colgada en `docker ps` y se apilaba (procesos 435 -> 764, load 68 en 2
# vCPU); al destrabarse reiniciaba sobre el host saturado y mandaba un mail por
# problema a la misma cuenta de Brevo Free (300 por dia) que usa la app.


def _tiene(binario: str) -> bool:
    ruta = str(Path(BASH).parent) if BASH else None
    return bool(shutil.which(binario, path=ruta) or shutil.which(binario))


def _requiere(binario: str) -> pytest.MarkDecorator:
    """flock (util-linux) no existe en Git Bash: esos tests corren en CI."""
    return pytest.mark.skipif(
        not _tiene(binario),
        reason=f"hace falta {binario} (util-linux/coreutils del host Linux)",
    )


def _avisos(host: Host) -> list[str]:
    return [ll for ll in host.llamadas() if ll.startswith(("curl ", "msmtp "))]


@_requiere("flock")
def test_guard_no_corre_si_otra_corrida_tiene_el_lock(host: Host) -> None:
    assert BASH is not None
    listo = host.raiz / "lock-tomado"
    duenio = subprocess.Popen(
        [
            BASH,
            "-c",
            'exec 9>"$0"; flock 9; : > "$1"; read -r _',
            (host.state / "guard.lock").as_posix(),
            listo.as_posix(),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        limite = time.time() + 20
        while not listo.exists():
            assert time.time() < limite, "el duenio del lock no arranco"
            time.sleep(0.05)

        resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")
    finally:
        duenio.communicate(b"\n", timeout=20)

    assert resultado.returncode == 0, resultado.stderr
    assert "otra corrida sigue en curso" in resultado.stderr
    assert not _hay(host.llamadas(), r"^docker ")


@_requiere("timeout")
def test_guard_con_docker_colgado_no_reinicia_y_avisa_una_vez(host: Host) -> None:
    extra = {
        "FAKE_UNHEALTHY_IDS": "abc123",
        "FAKE_DOCKER_CUELGA": "ps",
        "GUARD_DOCKER_TIMEOUT_SECONDS": "1",
        "ALERT_WEBHOOK_URL": "https://hook",
    }
    inicio = time.time()
    primera = host.correr("guard.sh", **extra)
    segunda = host.correr("guard.sh", **extra)

    assert time.time() - inicio < 25, "el tope de docker no corto la espera"
    assert primera.returncode == 0, primera.stderr
    assert segunda.returncode == 0, segunda.stderr
    assert _reinicios(host) == []
    avisos = _avisos(host)
    assert len(avisos) == 1, avisos
    assert "docker no responde" in avisos[0]


@_requiere("timeout")
def test_guard_con_docker_restart_colgado_no_sigue_reiniciando(host: Host) -> None:
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1 shifty-backend-2",
        FAKE_DOCKER_CUELGA="restart",
        GUARD_RESTART_TIMEOUT_SECONDS="1",
        ALERT_WEBHOOK_URL="https://hook",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert len(_reinicios(host)) == 1
    avisos = _avisos(host)
    assert len(avisos) == 1, avisos
    assert "docker no responde" in avisos[0]


def test_guard_con_el_host_saturado_no_reinicia_y_avisa_una_vez(host: Host) -> None:
    (host.fake / "loadavg").write_text(
        "99999.00 40.00 20.00 9/764 4242\n", encoding="utf-8", newline="\n"
    )
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-backend-1 shifty-backend-2",
        "ALERT_WEBHOOK_URL": "https://hook",
    }

    primera = host.correr("guard.sh", **extra)
    segunda = host.correr("guard.sh", **extra)

    assert primera.returncode == 0, primera.stderr
    assert segunda.returncode == 0, segunda.stderr
    assert _reinicios(host) == []
    avisos = _avisos(host)
    assert len(avisos) == 1, avisos
    assert "host saturado" in avisos[0]
    assert "99999.00" in avisos[0]
    # Lo que no se reinicio no gasta el tope de la hora.
    assert not (host.state / "guard" / "shifty-backend-1").exists()


def test_guard_con_carga_legible_no_saturada_reinicia_como_antes(host: Host) -> None:
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="abc123",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _hay(host.llamadas(), r"docker restart abc123")
    assert "no pude leer la carga" not in resultado.stderr


def test_guard_manda_un_solo_aviso_por_corrida(host: Host) -> None:
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-rabbitmq-1 shifty-backend-1 shifty-backend-2",
        "ALERT_EMAIL": "ops@example.com",
        "ALERT_WEBHOOK_URL": "https://hook",
    }

    resultado = host.correr("guard.sh", **extra)

    assert resultado.returncode == 0, resultado.stderr
    assert len(_reinicios(host)) == 2
    mails = host.mails()
    assert len(mails) == 1, mails
    assert len([ll for ll in host.llamadas() if ll.startswith("curl ")]) == 1
    assert _asunto(mails[0]).endswith(
        "] guard: shifty-rabbitmq-1 (rabbitmq) esta unhealthy; no se reinicia solo"
        " (+2 avisos)"
    )
    for linea in (
        "- guard: shifty-rabbitmq-1 (rabbitmq) esta unhealthy; no se reinicia solo",
        "- guard: reinicie shifty-backend-1 (unhealthy)",
        "- guard: reinicie shifty-backend-2 (unhealthy)",
    ):
        assert linea in mails[0]
    # Cada problema sigue en el log, aunque el mail sea uno.
    assert resultado.stderr.count("ALERTA: guard:") == 3

    # La corrida siguiente omite lo silenciado (rabbitmq, 60 min).
    otra = host.correr("guard.sh", **extra)
    assert otra.returncode == 0, otra.stderr
    mails = host.mails()
    assert len(mails) == 2
    assert _asunto(mails[1]).endswith(
        "] guard: reinicie shifty-backend-1 (unhealthy) (+1 aviso)"
    )
    assert "rabbitmq" not in mails[1]
    assert "alerta silenciada (guard-no-reinicia-shifty-rabbitmq-1)" in otra.stderr


# --- revision del 2026-11-15 sobre el arreglo del 13/11 -----------------------


def _sin_estado(host: Host) -> str:
    """Un SHIFTY_STATE_DIR que no se puede crear ni escribir (su padre es un
    archivo), como un / remontado de solo lectura tras errores de disco."""
    archivo = host.raiz / "un-archivo"
    archivo.write_text("no soy un directorio\n", encoding="utf-8")
    return (archivo / "estado").as_posix()


@pytest.mark.parametrize("servicio", ["db", "rabbitmq"])
def test_guard_sin_estado_escribible_avisa_igual(host: Host, servicio: str) -> None:
    """B1: abrir el lock (o crear el directorio de contadores) fallaba bajo
    `set -e` y el guard salia 1 SIN avisar, cuando antes avisaba."""
    con_hora_utc(host)
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS=f"shifty-{servicio}-1",
        SHIFTY_STATE_DIR=_sin_estado(host),
        ALERT_EMAIL="ops@example.com",
        FAKE_HORA_UTC="05:58",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    assert host.mails() == []
    assert f"shifty-{servicio}-1" in resultado.stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultado.stderr
    )
    if _tiene("flock"):
        assert "no pude abrir el lock" in resultado.stderr


@pytest.mark.skipif(
    os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="los permisos de solo lectura no frenan a root ni a Windows",
)
def test_guard_con_el_estado_de_solo_lectura_avisa_igual(host: Host) -> None:
    """B1 tal cual: el directorio existe pero no se puede escribir."""
    (host.state / "guard").mkdir()
    con_hora_utc(host)
    for d in (host.state / "guard", host.state):
        d.chmod(0o555)
    try:
        resultado = host.correr(
            "guard.sh",
            FAKE_UNHEALTHY_IDS="shifty-db-1 shifty-rabbitmq-1",
            ALERT_EMAIL="ops@example.com",
            FAKE_HORA_UTC="05:58",
        )
    finally:
        for d in (host.state, host.state / "guard"):
            d.chmod(0o755)

    assert resultado.returncode == 0, resultado.stderr
    assert host.mails() == []
    assert "ALERTA: guard: db esta unhealthy" in resultado.stderr


def _flock_que_falla(host: Host) -> str:
    """Un PATH con un flock que falla sin que haya conflicto (sale 1): un
    error de flock, no otra corrida con el lock."""
    directorio = host.raiz / "flock-roto"
    directorio.mkdir()
    falso = directorio / "flock"
    falso.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "flock $*" >> "$FAKE_DIR/calls"\nexit 1\n',
        encoding="utf-8",
        newline="\n",
    )
    falso.chmod(0o755)
    return os.pathsep.join([str(directorio), host.env["PATH"]])


def _flock_que_falla_una_vez(host: Host) -> str:
    """Falla el lock primario y permite tomar el lock del respaldo."""
    directorio = host.raiz / "flock-falla-una-vez"
    directorio.mkdir()
    falso = directorio / "flock"
    falso.write_text(
        "#!/bin/sh\n"
        'if [ ! -e "$FAKE_DIR/flock-ya-fallo" ]; then\n'
        '  : > "$FAKE_DIR/flock-ya-fallo"\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    falso.chmod(0o755)
    return os.pathsep.join([str(directorio), host.env["PATH"]])


def test_guard_que_muere_a_mitad_de_corrida_manda_lo_encolado(host: Host) -> None:
    """A1: un error bajo `set -e` entre alert_add y alert_flush perdia lo
    encolado. Aca el aviso de sin exclusividad se encola antes de `docker
    ps` y la corrida muere en un `docker inspect` que falla."""
    con_hora_utc(host)
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1",
        FAKE_INSPECT_EXIT="1",
        ALERT_EMAIL="ops@example.com",
        FAKE_HORA_UTC="06:00",
        PATH=_flock_que_falla(host),
    )

    assert resultado.returncode != 0
    assert _reinicios(host) == []
    assert "ALERTA: guard: sin exclusividad" in resultado.stderr
    mails = host.mails()
    assert len(mails) == 1, resultado.stderr
    assert "guard: sin exclusividad" in _asunto(mails[0])
    assert _asunto(mails[0]).endswith("(sin estado)")


# --- exclusividad (revision del 2026-11-15) -----------------------------------
# El guard reinicia SOLO con el lock de una sola corrida. Sin flock, sin un
# lock que se pueda abrir o con un error de flock que no es un conflicto, corre
# en modo observacion: todos los chequeos y avisos, ningun reinicio.

_EXCLUSIVIDAD = ["flock-que-falla", "sin-flock"]


def _path_sin_exclusividad(host: Host, como: str) -> str:
    if como == "sin-flock":
        if os.name == "nt":
            pytest.skip("arma un PATH de symlinks (Linux)")
        return _path_sin(host, "flock")
    return _flock_que_falla(host)


@pytest.mark.parametrize("como", _EXCLUSIVIDAD)
def test_guard_sin_exclusividad_observa_avisa_y_no_reinicia(
    host: Host, como: str
) -> None:
    path = _path_sin_exclusividad(host, como)
    con_hora_utc(host)
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-backend-1 shifty-rabbitmq-1 shifty-backend-2",
        "ALERT_EMAIL": "ops@example.com",
        "FAKE_HORA_UTC": "06:00",
        "PATH": os.pathsep.join([(host.raiz / "hora").as_posix(), path]),
    }

    resultado = host.correr("guard.sh", **extra)

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    mails = host.mails()
    assert len(mails) == 1, mails
    assert "guard: sin exclusividad" in _asunto(mails[0])
    assert _asunto(mails[0]).endswith("(sin estado)")
    motivo = "el host no tiene flock" if como == "sin-flock" else "flock"
    assert "guard: sin exclusividad (" in resultado.stderr
    assert motivo in resultado.stderr
    for linea in (
        "shifty-rabbitmq-1 (rabbitmq) esta unhealthy; no se reinicia solo",
        "no reinicio shifty-backend-1: sin exclusividad (",
        "no reinicio shifty-backend-2: sin exclusividad (",
    ):
        assert linea in resultado.stderr, resultado.stderr
    # Lo que no se reinicio no gasta el tope.
    assert not (host.state / "guard" / "shifty-backend-1").exists()

    # Sin estado, el minuto siguiente queda fuera de la ventana de envio.
    otra = host.correr("guard.sh", **{**extra, "FAKE_HORA_UTC": "06:01"})
    assert otra.returncode == 0, otra.stderr
    assert _reinicios(host) == []
    assert len(host.mails()) == 1


@pytest.mark.parametrize("como", _EXCLUSIVIDAD)
def test_dos_guards_a_la_vez_sin_exclusividad_no_reinician(
    host: Host, como: str
) -> None:
    assert BASH is not None
    env = {
        **host.env,
        "FAKE_UNHEALTHY_IDS": "shifty-backend-1 shifty-backend-2",
        "PATH": _path_sin_exclusividad(host, como),
    }
    procesos = [
        subprocess.Popen(
            [BASH, str(SCRIPTS / "guard.sh")],
            cwd=host.repo,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    salidas = [p.communicate(timeout=60)[1] for p in procesos]

    assert [p.returncode for p in procesos] == [0, 0], salidas
    assert _reinicios(host) == []
    for salida in salidas:
        assert "modo observacion" in salida, salida


def test_guard_sin_ningun_lock_que_se_pueda_abrir_observa(host: Host) -> None:
    con_hora_utc(host)
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1",
        ALERT_EMAIL="ops@example.com",
        SHIFTY_STATE_DIR=_sin_estado(host),
        SHIFTY_RUN_DIR=(host.raiz / "un-archivo" / "run").as_posix(),
        FAKE_HORA_UTC="06:00",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    mails = host.mails()
    assert len(mails) == 1, resultado.stderr
    assert "guard: sin exclusividad (no pude abrir " in _asunto(mails[0])


@_requiere("flock")
def test_guard_no_corre_si_otra_corrida_tiene_el_lock_de_respaldo(
    host: Host,
) -> None:
    """Una corrida que solo pudo tomar el lock de /run (el estado no se podia
    escribir) tambien excluye a las demas."""
    assert BASH is not None
    run = host.raiz / "run"
    run.mkdir()
    listo = host.raiz / "lock-tomado"
    duenio = subprocess.Popen(
        [
            BASH,
            "-c",
            'exec 9>"$0"; flock 9; : > "$1"; read -r _',
            (run / "guard.lock").as_posix(),
            listo.as_posix(),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        limite = time.time() + 20
        while not listo.exists():
            assert time.time() < limite, "el duenio del lock no arranco"
            time.sleep(0.05)

        resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")
    finally:
        duenio.communicate(b"\n", timeout=20)

    assert resultado.returncode == 0, resultado.stderr
    assert "otra corrida sigue en curso" in resultado.stderr
    assert not _hay(host.llamadas(), r"^docker ")


@_requiere("flock")
@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 0)() == 0,
    reason="los permisos de solo lectura no frenan a root",
)
def test_un_lock_de_solo_lectura_sigue_excluyendo(host: Host) -> None:
    """Con el estado remontado de solo lectura otra corrida puede seguir con el
    lock: si este guard no pudiera abrirlo tomaria solo el de /run y los dos
    reiniciarian a la vez. flock no necesita escribir: lo abre para leer."""
    assert BASH is not None
    lock = host.state / "guard.lock"
    lock.write_text("", encoding="utf-8")
    listo = host.raiz / "lock-tomado"
    duenio = subprocess.Popen(
        [
            BASH,
            "-c",
            'exec 9<"$0"; flock 9; : > "$1"; read -r _',
            lock.as_posix(),
            listo.as_posix(),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        limite = time.time() + 20
        while not listo.exists():
            assert time.time() < limite, "el duenio del lock no arranco"
            time.sleep(0.05)
        lock.chmod(0o444)
        host.state.chmod(0o555)
        try:
            resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS="abc123")
        finally:
            host.state.chmod(0o755)
    finally:
        duenio.communicate(b"\n", timeout=20)

    assert resultado.returncode == 0, resultado.stderr
    assert "otra corrida sigue en curso" in resultado.stderr
    assert not _hay(host.llamadas(), r"^docker ")


# --- contadores de reinicio (revision del 2026-11-15) ---------------------------


def test_guard_con_un_contador_ilegible_no_reinicia_y_sigue_avisando(
    host: Host,
) -> None:
    """El `printf` al contador moria bajo `set -e` y se perdian los avisos que
    venian despues (rabbitmq). Aca el contador de shifty-backend-1 es un
    directorio."""
    (host.state / "guard" / "shifty-backend-1").mkdir(parents=True)

    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1 shifty-rabbitmq-1 shifty-backend-2",
        ALERT_EMAIL="ops@example.com",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    mails = host.mails()
    assert len(mails) == 1, resultado.stderr
    for linea in (
        "- guard: shifty-rabbitmq-1 (rabbitmq) esta unhealthy; no se reinicia solo",
        "- guard: no reinicio shifty-backend-1: no puedo leer el contador",
        "- guard: no reinicio shifty-backend-2: no puedo leer el contador",
    ):
        assert linea in mails[0], mails[0]


_NO_ROOT = pytest.mark.skipif(
    os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="los permisos no frenan a root ni a Windows",
)


@_NO_ROOT
def test_guard_sin_poder_anotar_el_contador_no_reinicia(host: Host) -> None:
    (host.state / "guard").mkdir()
    (host.state / "guard").chmod(0o555)
    try:
        resultado = host.correr(
            "guard.sh",
            FAKE_UNHEALTHY_IDS="shifty-backend-1 shifty-rabbitmq-1",
            ALERT_EMAIL="ops@example.com",
        )
    finally:
        (host.state / "guard").chmod(0o755)

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    mails = host.mails()
    assert len(mails) == 1, resultado.stderr
    assert (
        "- guard: no reinicio shifty-backend-1: no puedo anotar el contador"
        in (mails[0])
    )
    assert "shifty-rabbitmq-1 (rabbitmq) esta unhealthy" in mails[0]


@_NO_ROOT
@pytest.mark.parametrize(
    ("contador", "marcas"), [("shifty-backend-1", 3), ("_global", 6)]
)
def test_un_contador_que_no_se_lee_no_saltea_el_tope(
    host: Host, contador: str, marcas: int
) -> None:
    """Un contador que se podia escribir pero no leer se tomaba por vacio: cada
    corrida reiniciaba y el tope de 3 (o de 6) no frenaba nunca."""
    ahora = int(time.time())
    archivo = host.state / "guard" / contador
    archivo.parent.mkdir(parents=True)
    archivo.write_text(f"{ahora}\n" * marcas, encoding="utf-8", newline="\n")
    archivo.chmod(0o200)

    for _ in range(4):
        resultado = host.correr("guard.sh", FAKE_UNHEALTHY_IDS="shifty-backend-1")
        assert resultado.returncode == 0, resultado.stderr

    assert _reinicios(host) == []
    assert "no puedo leer el contador" in resultado.stderr


def test_guard_tras_un_restart_fallido_no_reinicia_nada_mas(host: Host) -> None:
    """A2: el 13/11 dockerd devolvia errores ("context deadline exceeded"), no
    se colgaba: el guard probaba cada contenedor con hasta 120 s cada uno."""
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1 shifty-backend-2 shifty-backend-3",
        FAKE_RESTART_EXIT="1",
        ALERT_WEBHOOK_URL="https://hook",
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == ["docker restart shifty-backend-1"]
    avisos = _avisos(host)
    assert len(avisos) == 1, avisos
    assert "fallo docker restart shifty-backend-1" in avisos[0]
    assert "no reinicio shifty-backend-2" in resultado.stderr
    # Lo que no se intento no gasta el tope de la hora.
    assert not (host.state / "guard" / "shifty-backend-2").exists()


@pytest.mark.parametrize("como", ["cuelga", "falla"])
def test_tras_un_restart_fallido_sigue_avisando_lo_demas(host: Host, como: str) -> None:
    """2026-11-15 (A-ADV3): un restart colgado cortaba la corrida y el aviso de
    rabbitmq, que venia despues en `docker ps`, esperaba unos 6 minutos (hasta
    agotar el tope global). Sin otro restart, la corrida sigue para encolar los
    avisos del resto."""
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-backend-1 shifty-backend-2 shifty-rabbitmq-1",
        "ALERT_EMAIL": "ops@example.com",
    }
    if como == "cuelga":
        if not _tiene("timeout"):
            pytest.skip("hace falta timeout (coreutils)")
        extra.update(FAKE_DOCKER_CUELGA="restart", GUARD_RESTART_TIMEOUT_SECONDS="1")
        primero = "docker no responde (docker restart shifty-backend-1 no termino"
    else:
        extra["FAKE_RESTART_EXIT"] = "1"
        primero = "fallo docker restart shifty-backend-1"

    resultado = host.correr("guard.sh", **extra)

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == ["docker restart shifty-backend-1"]
    mails = host.mails()
    assert len(mails) == 1, resultado.stderr
    for linea in (
        "- guard: shifty-rabbitmq-1 (rabbitmq) esta unhealthy; no se reinicia solo",
        f"- guard: {primero}",
        "- guard: no reinicio shifty-backend-2: ya fallo un restart en esta corrida",
    ):
        assert linea in mails[0], mails[0]
    assert not (host.state / "guard" / "shifty-backend-2").exists()


def test_guard_con_docker_ps_que_falla_avisa_que_docker_no_responde(
    host: Host,
) -> None:
    """A2: con el daemon caido `docker ps` falla enseguida (no vence el tope) y
    el guard salia sin avisar."""
    extra = {
        "FAKE_UNHEALTHY_IDS": "abc123",
        "FAKE_PS_EXIT": "1",
        "ALERT_WEBHOOK_URL": "https://hook",
    }

    primera = host.correr("guard.sh", **extra)
    segunda = host.correr("guard.sh", **extra)

    assert primera.returncode == 0, primera.stderr
    assert segunda.returncode == 0, segunda.stderr
    assert _reinicios(host) == []
    avisos = _avisos(host)
    assert len(avisos) == 1, avisos
    assert "docker no responde (docker ps fallo con codigo 1)" in avisos[0]
    assert "alerta silenciada (guard-docker-no-responde)" in segunda.stderr


def test_los_avisos_de_reinicio_no_gastan_la_reserva_de_un_incidente(
    host: Host,
) -> None:
    """A3: cada "reinicie X" no tiene clave, asi que contaba como incidente
    nuevo y se comia la reserva; despues la base caida no llegaba."""
    p = _presupuesto(3, 1)
    for n in (1, 2, 3):
        resultado = host.correr(
            "guard.sh", FAKE_UNHEALTHY_IDS=f"shifty-backend-{n}", **p
        )
        assert resultado.returncode == 0, resultado.stderr
    assert len(_reinicios(host)) == 3
    assert len(host.mails()) == 2

    resultado = host.correr(
        "guard.sh", FAKE_UNHEALTHY_IDS="shifty-db-1 shifty-backend-4", **p
    )

    assert resultado.returncode == 0, resultado.stderr
    mails = host.mails()
    assert len(mails) == 3, resultado.stderr
    assert _asunto(mails[2]).endswith(
        "] guard: db esta unhealthy (shifty-db-1); no reinicio nada"
    )
    assert "1 alertas suprimidas desde" in mails[2]


@pytest.mark.parametrize("tope", ["abc", "0", "-1", "4,5"])
def test_guard_con_un_tope_de_carga_invalido_usa_el_de_siempre(
    host: Host, tope: str
) -> None:
    """A4: awk comparaba la carga contra "abc" como texto y reiniciaba igual."""
    (host.fake / "loadavg").write_text(
        "99999.00 40.00 20.00 9/764 4242\n", encoding="utf-8", newline="\n"
    )

    resultado = host.correr(
        "guard.sh", FAKE_UNHEALTHY_IDS="abc123", GUARD_MAX_LOAD_PER_CPU=tope
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    assert f"GUARD_MAX_LOAD_PER_CPU={tope} no es un numero positivo; uso 4" in (
        resultado.stderr
    )
    assert "host saturado" in resultado.stderr


def test_guard_con_carga_ilegible_no_reinicia(host: Host) -> None:
    """Sin medir la carga, reiniciar podria agravar la saturacion del host."""
    faltante = (host.raiz / "loadavg-inexistente").as_posix()

    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1",
        GUARD_LOADAVG_FILE=faltante,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    assert "no pude leer la carga del host" in resultado.stderr
    assert "no reinicio nada" in resultado.stderr
    assert not (host.state / "guard" / "shifty-backend-1").exists()


def _path_sin(host: Host, *excluidos: str) -> str:
    """Un PATH con los binarios falsos y symlinks a los del sistema, menos
    `excluidos`. Solo Linux: Windows no crea symlinks sin privilegios."""
    fake_bin = host.env["PATH"].split(os.pathsep)[0]
    sin = host.raiz / ("sin-" + "-".join(excluidos))
    sin.mkdir()
    assert BASH is not None
    for directorio in (Path(BASH).parent, *map(Path, ("/usr/bin", "/bin"))):
        if not directorio.is_dir():
            continue
        for binario in directorio.iterdir():
            destino = sin / binario.name
            # lexists y no exists: exists() sigue el symlink, y en un Ubuntu con
            # /usr fusionado /bin y /usr/bin son el mismo directorio. Un symlink
            # roto (/usr/bin/grub-ntldr-img del runner de CI, 2026-11-15) pasaba
            # el chequeo la segunda vez y symlink_to fallaba con FileExistsError.
            if binario.name not in excluidos and not os.path.lexists(destino):
                destino.symlink_to(binario)
    path = os.pathsep.join([fake_bin, sin.as_posix()])
    for excluido in excluidos:
        assert shutil.which(excluido, path=path) is None, excluido
    return path


@pytest.mark.skipif(os.name == "nt", reason="arma un PATH de symlinks (Linux)")
def test_guard_sin_timeout_lo_anota_una_vez(host: Host) -> None:
    """A5: sin `timeout` no se inicia Docker ni se intenta SMTP ilimitado."""
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="shifty-backend-1 shifty-backend-2",
        ALERT_EMAIL="ops@example.com",
        PATH=_path_sin(host, "timeout"),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _reinicios(host) == []
    assert not any(call.startswith("docker ") for call in host.llamadas())
    assert "el host no tiene timeout" in resultado.stderr
    assert "alerta SMTP suprimida: no hay timeout" in resultado.stderr
    assert host.mails() == []


def test_el_aviso_agrupado_empieza_por_el_mas_grave(host: Host) -> None:
    """A6: "guard: N avisos en esta corrida" escondia lo mas grave."""
    ahora = int(time.time())
    (host.state / "guard").mkdir(parents=True)
    (host.state / "guard" / "shifty-backend-2").write_text(
        f"{ahora}\n{ahora}\n{ahora}\n", encoding="utf-8", newline="\n"
    )

    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS=(
            "shifty-backend-1 shifty-backend-2 shifty-backend-3 shifty-rabbitmq-1"
        ),
        FAKE_RESTART_FALLA="shifty-backend-3",
        ALERT_EMAIL="ops@example.com",
    )

    assert resultado.returncode == 0, resultado.stderr
    mails = host.mails()
    assert len(mails) == 1, mails
    assert _asunto(mails[0]).endswith(
        "] guard: shifty-rabbitmq-1 (rabbitmq) esta unhealthy; no se reinicia solo"
        " (+3 avisos)"
    )
    cuerpo = mails[0].split("\n\n", 1)[1]
    orden = [
        cuerpo.index(f"- guard: {texto}")
        for texto in (
            "shifty-rabbitmq-1 (rabbitmq) esta unhealthy",
            "fallo docker restart shifty-backend-3",
            "shifty-backend-2 sigue unhealthy",
            "reinicie shifty-backend-1",
        )
    ]
    assert orden == sorted(orden), cuerpo


# --- alert() de scripts/lib/common.sh: silencio y presupuesto de mails --------


def test_alerta_repetida_con_clave_sale_una_vez(host: Host) -> None:
    primera = host.alertar("disco: / al 85 %", "", "disco", "60", ALERT_EMAIL="o@x")
    segunda = host.alertar("disco: / al 85 %", "", "disco", "60", ALERT_EMAIL="o@x")

    assert primera.returncode == 0 and segunda.returncode == 0
    assert len(host.mails()) == 1
    assert "alerta silenciada (disco)" in segunda.stderr


def test_alertas_con_claves_distintas_salen_las_dos(host: Host) -> None:
    host.alertar("disco: / al 85 %", "", "disco", "60", ALERT_EMAIL="o@x")
    host.alertar("swap: el host no tiene swap", "", "swap", "60", ALERT_EMAIL="o@x")

    mails = host.mails()
    assert len(mails) == 2
    assert "disco: / al 85 %" in mails[0] and "swap: el host" in mails[1]


@_requiere("flock")
def test_dos_alertas_a_la_vez_con_la_misma_clave_salen_una_vez(host: Host) -> None:
    """Sin lock, varios procesos pasaban el chequeo del sello antes de que
    alguno lo tocara."""
    assert BASH is not None
    largada = host.raiz / "largada"
    procesos = [
        subprocess.Popen(
            [
                BASH,
                "-c",
                'set -euo pipefail; while [ ! -e "$1" ]; do :; done; . "$0"; '
                'alert "db caida" "" db-caida 60',
                (SCRIPTS / "lib" / "common.sh").as_posix(),
                largada.as_posix(),
            ],
            cwd=host.repo,
            env={**host.env, "ALERT_EMAIL": "o@x"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(6)
    ]
    time.sleep(0.5)
    largada.write_text("ya\n", encoding="utf-8")
    for proceso in procesos:
        assert proceso.wait(timeout=60) == 0

    assert len(host.mails()) == 1, host.mails()


def _presupuesto(maximo: int, reserva: int) -> dict[str, str]:
    return {
        "ALERT_EMAIL": "o@x",
        "ALERT_EMAIL_MAX_PER_DAY": str(maximo),
        "ALERT_EMAIL_RESERVED_PER_DAY": str(reserva),
    }


def _asunto(mail: str) -> str:
    return mail.split("Subject: ", 1)[1].splitlines()[0]


def test_alerta_sin_lock_usa_modo_sin_estado_en_ventana(host: Host) -> None:
    con_hora_utc(host)
    resultado = host.alertar(
        "a: aviso",
        "",
        "a",
        "0",
        FAKE_HORA_UTC="06:00",
        PATH=_flock_que_falla(host),
        **_presupuesto(1, 0),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "no pude tomar" in resultado.stderr
    mails = host.mails()
    assert len(mails) == 1, resultado.stderr
    assert _asunto(mails[0]).endswith("a: aviso (sin estado)")


def test_alerta_lock_primario_fallido_no_manda_email_con_respaldo_sano(
    host: Host,
) -> None:
    con_hora_utc(host)
    resultado = host.alertar(
        "a: aviso",
        "",
        "a",
        "0",
        FAKE_HORA_UTC="07:30",
        PATH=_flock_que_falla_una_vez(host),
        **_presupuesto(1, 0),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert host.mails() == []
    assert "no pude tomar" in resultado.stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultado.stderr
    )
    registro_respaldo = host.raiz / "run" / "alerts" / ".mails-del-dia"
    assert registro_respaldo.read_text(encoding="utf-8").splitlines()[:2] == [
        time.strftime("%Y-%m-%d", time.gmtime()),
        "1",
    ]


def test_alerta_con_registro_de_presupuesto_corrupto_falla_cerrado(host: Host) -> None:
    con_hora_utc(host)
    hoy = time.strftime("%Y-%m-%d", time.gmtime())
    alertas = host.state / "alerts"
    alertas.mkdir(parents=True, exist_ok=True)
    (alertas / ".mails-del-dia").write_text(
        f"{hoy}\nno-es-un-conteo\n", encoding="utf-8", newline="\n"
    )

    resultado = host.alertar(
        "a: aviso",
        "",
        "a",
        "0",
        FAKE_HORA_UTC="07:30",
        **_presupuesto(1, 0),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert host.mails() == []
    assert "registro de presupuesto invalido para hoy" in resultado.stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultado.stderr
    )


@pytest.mark.parametrize("fecha", ["2026-99-99", "2999-01-01"])
def test_alerta_con_fecha_de_presupuesto_invalida_o_futura_falla_cerrado(
    host: Host, fecha: str
) -> None:
    con_hora_utc(host)
    alertas = host.state / "alerts"
    alertas.mkdir(parents=True, exist_ok=True)
    (alertas / ".mails-del-dia").write_text(
        f"{fecha}\n0\n", encoding="utf-8", newline="\n"
    )

    resultado = host.alertar(
        "a: aviso",
        "",
        "a",
        "0",
        FAKE_HORA_UTC="07:30",
        **_presupuesto(1, 0),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert host.mails() == []
    assert "registro de presupuesto invalido" in resultado.stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultado.stderr
    )


def test_el_presupuesto_diario_guarda_lugar_para_un_incidente_nuevo(
    host: Host,
) -> None:
    """Cada alert() es un proceso nuevo: el contador vive en el estado del
    host, no en memoria. Silencio 0: ninguna clave queda silenciada."""
    p = _presupuesto(3, 1)
    host.alertar("a: uno", "", "guard-host-saturado", "0", **p)
    host.alertar("b: dos", "", "b", "0", **p)
    # La reserva es solo para claves CRITICAS que todavia no salieron hoy
    # (revision del 2026-11-15): ni una critica repetida ni una nueva comun.
    repetida = host.alertar("a: uno otra vez", "", "guard-host-saturado", "0", **p)
    comun = host.alertar("x: aviso nuevo comun", "", "x", "0", **p)
    nueva = host.alertar("c: incidente nuevo", "", "guard-dependencia-db", "0", **p)
    agotada = host.alertar("d: otro nuevo", "", "backup-fallo", "0", **p)

    asuntos = [_asunto(m) for m in host.mails()]
    assert len(asuntos) == 3, asuntos
    assert asuntos[2].endswith("c: incidente nuevo")
    assert nueva.returncode == 0, nueva.stderr
    for resultado, asunto in (
        (repetida, "a: uno otra vez"),
        (comun, "x: aviso nuevo comun"),
        (agotada, "d: otro nuevo"),
    ):
        assert resultado.returncode == 0
        assert (
            f"alerta suprimida por presupuesto diario del host: {asunto}"
            in resultado.stderr
        )
    assert _hay(
        host.llamadas(),
        r"^logger .*alerta suprimida por presupuesto diario del host: d: otro nuevo",
    )


def test_el_cambio_de_dia_utc_renueva_el_presupuesto_y_cuenta_las_suprimidas(
    host: Host,
) -> None:
    p = _presupuesto(1, 0)
    host.alertar("a: uno", "", "a", "0", **p)
    host.alertar("b: dos", "", "b", "0", **p)
    host.alertar("c: tres", "", "c", "0", **p)
    assert len(host.mails()) == 1

    # El mismo registro, pero de ayer (UTC): el dia nuevo arranca de cero.
    registro = host.state / "alerts" / ".mails-del-dia"
    lineas = registro.read_text(encoding="utf-8").splitlines()
    ayer = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    registro.write_text(
        "\n".join([ayer, *lineas[1:]]) + "\n", encoding="utf-8", newline="\n"
    )

    resultado = host.alertar("d: cuatro", "detalle", "d", "0", **p)

    assert resultado.returncode == 0, resultado.stderr
    mails = host.mails()
    assert len(mails) == 2
    assert _asunto(mails[1]).endswith("d: cuatro")
    assert "2 alertas suprimidas desde 20" in mails[1]
    # Se cuentan una vez: el mail siguiente ya no las repite.
    registro.write_text(ayer + "\n0\n", encoding="utf-8", newline="\n")
    host.alertar("e: cinco", "", "e", "0", **p)
    assert "suprimidas" not in host.mails()[2]


def test_un_msmtp_que_falla_se_anota_y_no_se_reintenta(host: Host) -> None:
    resultados = [
        host.alertar(
            "db caida", "", "db-caida", "60", ALERT_EMAIL="o@x", FAKE_MSMTP_EXIT="75"
        )
        for _ in range(2)
    ]

    assert all(r.returncode == 0 for r in resultados)
    assert len([ll for ll in host.llamadas() if ll.startswith("msmtp ")]) == 1
    assert "no se pudo mandar la alerta por mail (msmtp)" in resultados[0].stderr
    assert "alerta silenciada (db-caida)" in resultados[1].stderr


def test_el_webhook_no_gasta_presupuesto_y_su_falla_se_anota(host: Host) -> None:
    p = {**_presupuesto(1, 0), "ALERT_WEBHOOK_URL": "https://hook"}
    host.alertar("a: uno", "", "a", "0", **p)
    resultado = host.alertar("b: dos", "", "b", "0", FAKE_CURL_EXIT="22", **p)

    curls = [ll for ll in host.llamadas() if ll.startswith("curl ")]
    assert len(curls) == 2
    assert len(host.mails()) == 1
    assert "no se pudo mandar la alerta al webhook" in resultado.stderr
    assert (
        "alerta suprimida por presupuesto diario del host: b: dos" in resultado.stderr
    )


# --- estado de alertas que no se puede escribir (revision del 2026-11-15) ------
# Antes alert_flush mandaba sin silencio ni presupuesto: con / remontado de solo
# lectura, un mail por minuto a la cuenta de Brevo que usa la app.


def test_sin_estado_escribible_la_alerta_usa_el_respaldo_en_tmpfs(host: Host) -> None:
    con_hora_utc(host)
    sin_estado = {
        "SHIFTY_STATE_DIR": _sin_estado(host),
        "FAKE_HORA_UTC": "07:30",
        **_presupuesto(1, 0),
    }

    primera = host.alertar("db caida", "", "db-caida", "60", **sin_estado)
    segunda = host.alertar("db caida", "", "db-caida", "60", **sin_estado)

    assert primera.returncode == 0 and segunda.returncode == 0
    assert host.mails() == []
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        primera.stderr
    )
    assert "alerta silenciada (db-caida)" in segunda.stderr
    run = (host.raiz / "run" / "alerts").as_posix()
    assert "no puedo escribir el estado de alertas en" in primera.stderr
    assert f"vive en {run} (tmpfs): se pierde al reiniciar el host" in (primera.stderr)


def test_guard_con_el_estado_de_solo_lectura_no_manda_un_mail_por_minuto(
    host: Host,
) -> None:
    con_hora_utc(host)
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-rabbitmq-1",
        "ALERT_EMAIL": "ops@example.com",
        "SHIFTY_STATE_DIR": _sin_estado(host),
    }

    resultados = [
        host.correr("guard.sh", FAKE_HORA_UTC=hora, **extra)
        for hora in ("05:58", "05:59", "06:01")
    ]

    assert [r.returncode for r in resultados] == [0, 0, 0], resultados[0].stderr
    assert host.mails() == []
    # El lock de /run alcanza: no es el modo observacion.
    assert "sin exclusividad" not in resultados[0].stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultados[0].stderr
    )
    assert resultados[0].stderr.count("se pierde al reiniciar el host") == 1


def _sin_ningun_estado(host: Host) -> dict[str, str]:
    archivo = host.raiz / "un-archivo"
    archivo.write_text("no soy un directorio\n", encoding="utf-8")
    return {
        "SHIFTY_STATE_DIR": (archivo / "estado").as_posix(),
        "SHIFTY_RUN_DIR": (archivo / "run").as_posix(),
    }


def test_sin_ningun_estado_avisa_por_syslog_y_manda_solo_en_la_ventana(
    host: Host,
) -> None:
    """Sin estado ni en el disco ni en tmpfs no hay silencio ni presupuesto:
    cada aviso queda en stderr y syslog, y el mail y el webhook salen solo en
    el minuto 00 de las horas UTC multiplo de ALERT_STATELESS_EVERY_HOURS (3)."""
    con_hora_utc(host)
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-rabbitmq-1",
        "ALERT_EMAIL": "ops@example.com",
        "ALERT_WEBHOOK_URL": "https://hook",
        **_sin_ningun_estado(host),
    }

    fuera = [
        host.correr("guard.sh", FAKE_HORA_UTC=hora, **extra)
        for hora in ("05:00", "05:01", "06:01")
    ]

    for resultado in fuera:
        assert resultado.returncode == 0, resultado.stderr
        assert "ALERTA: guard: shifty-rabbitmq-1 (rabbitmq) esta unhealthy" in (
            resultado.stderr
        )
        assert "fuera de la ventana" in resultado.stderr
    assert _avisos(host) == []
    assert _hay(
        host.llamadas(),
        r"^logger -t shifty -p user\.crit -- guard: shifty-rabbitmq-1 \(rabbitmq\)",
    )

    en_ventana = host.correr("guard.sh", FAKE_HORA_UTC="06:00", **extra)

    assert en_ventana.returncode == 0, en_ventana.stderr
    mails = host.mails()
    assert len(mails) == 1, en_ventana.stderr
    assert len([ll for ll in host.llamadas() if ll.startswith("curl ")]) == 1
    assert _asunto(mails[0]).endswith("(+1 aviso) (sin estado)")
    assert "Envio degradado sin estado" in mails[0]
    assert "Esta corrida tuvo 2 alertas." in mails[0]
    assert "guard: sin exclusividad" in mails[0]
    assert "rabbitmq" in mails[0]


@pytest.mark.parametrize(
    ("hora", "cada", "sale"),
    [("06:07", "", True), ("05:07", "", False), ("10:07", "5", True)],
)
def test_sin_ningun_estado_un_script_de_cada_hora_avisa_en_su_hora_de_ventana(
    host: Host, hora: str, cada: str, sale: bool
) -> None:
    """checks.sh y backup-check.sh corren una vez por hora (minuto 7 y 17): su
    aviso sale en cualquier minuto de una hora de ventana."""
    con_hora_utc(host)
    extra = {"ALERT_EMAIL": "o@x", "FAKE_HORA_UTC": hora, **_sin_ningun_estado(host)}
    if cada:
        extra["ALERT_STATELESS_EVERY_HOURS"] = cada

    resultado = host.alertar("backup: viejo", "", "backup-viejo", "60", **extra)

    assert resultado.returncode == 0, resultado.stderr
    assert len(host.mails()) == (1 if sale else 0), resultado.stderr


@pytest.mark.parametrize("cada", ["abc", "0", "25", "-1"])
def test_un_intervalo_sin_estado_invalido_usa_tres_horas(host: Host, cada: str) -> None:
    con_hora_utc(host)
    resultado = host.alertar(
        "backup: viejo",
        "",
        "backup-viejo",
        "60",
        ALERT_EMAIL="o@x",
        ALERT_STATELESS_EVERY_HOURS=cada,
        FAKE_HORA_UTC="03:07",
        **_sin_ningun_estado(host),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert f"ALERT_STATELESS_EVERY_HOURS={cada} no es un numero de horas" in (
        resultado.stderr
    )
    assert len(host.mails()) == 1


# 2026-11-15 (A-ADV1): con los inodos agotados o el disco lleno el directorio de
# alertas pasa `[ -w ]` pero no admite archivos nuevos. Sin sello ni registro,
# alert() mandaba igual: un mail y un webhook por minuto del guard.


def test_un_estado_que_no_admite_archivos_nuevos_usa_el_respaldo(host: Host) -> None:
    sin_espacio_para_crear(host, f"{host.state.as_posix()}/alerts/*")
    con_hora_utc(host)
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-rabbitmq-1",
        "ALERT_EMAIL": "ops@example.com",
        "ALERT_WEBHOOK_URL": "https://hook",
    }

    resultados = [
        host.correr("guard.sh", FAKE_HORA_UTC=hora, **extra)
        for hora in ("05:58", "05:59", "06:01")
    ]

    assert [r.returncode for r in resultados] == [0, 0, 0], resultados[0].stderr
    assert host.mails() == []
    assert len([ll for ll in host.llamadas() if ll.startswith("curl ")]) == 1
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultados[0].stderr
    )
    run = (host.raiz / "run" / "alerts").as_posix()
    assert f"vive en {run} (tmpfs)" in resultados[0].stderr
    registro_respaldo = host.raiz / "run" / "alerts" / ".mails-del-dia"
    assert registro_respaldo.read_text(encoding="utf-8").splitlines()[:2] == [
        time.strftime("%Y-%m-%d", time.gmtime()),
        "1",
    ]


@pytest.mark.parametrize("donde", ["estado", "estado-y-respaldo"])
def test_un_sello_que_no_se_escribe_no_manda_un_mail_por_minuto(
    host: Host, donde: str
) -> None:
    """La prueba de escritura pasa, pero el sello del silencio no se puede crear
    al mandar: baja al respaldo y, sin respaldo, al modo sin estado."""
    raiz = host.state.as_posix() if donde == "estado" else "*"
    sin_espacio_para_crear(host, f"{raiz}/alerts/guard-*")
    con_hora_utc(host)
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-rabbitmq-1",
        "ALERT_EMAIL": "ops@example.com",
        "ALERT_WEBHOOK_URL": "https://hook",
    }

    resultados = []
    for hora in ("05:58", "05:59", "06:00", "06:01", "06:02"):
        resultado = host.correr("guard.sh", FAKE_HORA_UTC=hora, **extra)
        resultados.append(resultado)
        assert resultado.returncode == 0, resultado.stderr

    mails = host.mails()
    if donde == "estado":
        # El sello principal falla en cada corrida: fuera de la ventana el SMTP
        # sigue suprimido, y en el minuto 00 de las 06 sale un mail degradado.
        assert len(mails) == 1, resultados[2].stderr
        assert "rabbitmq" in _asunto(mails[0])
        assert _asunto(mails[0]).endswith("(estado principal no disponible)")
        assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
            resultados[0].stderr
        )
        assert "alerta silenciada" in resultado.stderr
    else:
        assert len(mails) == 1, resultado.stderr
        assert "rabbitmq" in _asunto(mails[0])
        assert _asunto(mails[0]).endswith("(sin estado)")
        assert "fuera de la ventana" in resultado.stderr
    assert len([ll for ll in host.llamadas() if ll.startswith("curl ")]) == 1


def test_falla_al_reservar_ledger_primario_no_manda_smtp_con_respaldo_sano(
    host: Host,
) -> None:
    """El respaldo conserva el contador, pero no manda si falla el estado primario."""
    (host.state / "alerts" / ".mails-del-dia.tmp").mkdir(parents=True)
    con_hora_utc(host)
    p = {"FAKE_HORA_UTC": "07:30", **_presupuesto(1, 0)}

    resultados = [
        host.alertar(f"{clave}: aviso", "", clave, "0", **p) for clave in "abc"
    ]

    assert [r.returncode for r in resultados] == [0, 0, 0]
    assert host.mails() == []
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultados[0].stderr
    )
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultados[2].stderr
    )
    registro_respaldo = host.raiz / "run" / "alerts" / ".mails-del-dia"
    assert registro_respaldo.read_text(encoding="utf-8").splitlines()[:2] == [
        time.strftime("%Y-%m-%d", time.gmtime()),
        "1",
    ]


def test_uso_previo_primario_no_se_pierde_si_falla_la_siguiente_escritura(
    host: Host,
) -> None:
    hoy = time.strftime("%Y-%m-%d", time.gmtime())
    alertas = host.state / "alerts"
    alertas.mkdir(parents=True, exist_ok=True)
    (alertas / ".mails-del-dia").write_text(
        f"{hoy}\n1\na\n", encoding="utf-8", newline="\n"
    )
    (alertas / ".mails-del-dia.tmp").mkdir()
    con_hora_utc(host)

    resultado = host.alertar(
        "b: aviso",
        "",
        "b",
        "0",
        FAKE_HORA_UTC="07:30",
        **_presupuesto(3, 0),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert host.mails() == []
    assert "registro de presupuesto con uso previo (1)" in resultado.stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultado.stderr
    )
    registro_respaldo = host.raiz / "run" / "alerts" / ".mails-del-dia"
    assert registro_respaldo.read_text(encoding="utf-8").splitlines()[:2] == [
        hoy,
        "1",
    ]


def test_presupuesto_primario_al_tope_no_se_puede_saltar_con_respaldo_vacio(
    host: Host,
) -> None:
    con_hora_utc(host)
    hoy = time.strftime("%Y-%m-%d", time.gmtime())
    alertas = host.state / "alerts"
    alertas.mkdir(parents=True, exist_ok=True)
    (alertas / ".mails-del-dia").write_text(
        f"{hoy}\n1\na\n", encoding="utf-8", newline="\n"
    )
    (alertas / ".mails-suprimidos").mkdir()

    resultado = host.alertar(
        "b: aviso",
        "",
        "b",
        "0",
        FAKE_HORA_UTC="07:30",
        **_presupuesto(1, 0),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert host.mails() == []
    assert "no pude anotar la alerta suprimida" in resultado.stderr
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultado.stderr
    )
    registro_respaldo = host.raiz / "run" / "alerts" / ".mails-del-dia"
    assert registro_respaldo.read_text(encoding="utf-8").splitlines()[:2] == [
        hoy,
        "1",
    ]


# 2026-11-15 (PR #316): con el estado principal roto de forma persistente (/
# de solo lectura, disco lleno, registro con fecha futura) y el respaldo sano,
# el SMTP se suprimia en TODAS las corridas. ops.env.example trae el webhook
# comentado: el incidente entero no mandaba ningun aviso fuera del host.


def test_guard_con_el_estado_principal_roto_avisa_por_mail_en_la_ventana(
    host: Host,
) -> None:
    con_hora_utc(host)
    extra = {
        "FAKE_UNHEALTHY_IDS": "shifty-rabbitmq-1",
        "ALERT_EMAIL": "ops@example.com",
        "SHIFTY_STATE_DIR": _sin_estado(host),
    }

    mails_por_hora: dict[str, int] = {}
    resultados: dict[str, subprocess.CompletedProcess[str]] = {}
    for hora in ("05:58", "05:59", "06:00", "06:01", "07:00", "09:00"):
        resultados[hora] = host.correr("guard.sh", FAKE_HORA_UTC=hora, **extra)
        assert resultados[hora].returncode == 0, resultados[hora].stderr
        mails_por_hora[hora] = len(host.mails())

    # Fuera de la ventana sigue el SMTP suprimido y el silencio del respaldo.
    assert "alerta SMTP suprimida: no se pudo proteger el presupuesto diario" in (
        resultados["05:58"].stderr
    )
    assert "alerta silenciada (guard-no-reinicia-shifty-rabbitmq-1)" in (
        resultados["05:59"].stderr
    )
    assert mails_por_hora == {
        "05:58": 0,
        "05:59": 0,
        "06:00": 1,
        "06:01": 1,
        "07:00": 1,
        "09:00": 2,
    }, resultados["06:00"].stderr
    for mail in host.mails():
        assert "rabbitmq" in _asunto(mail)
        assert _asunto(mail).endswith("(estado principal no disponible)")
        assert "Envio degradado: no se pudo usar el estado de alertas" in mail


def test_un_script_de_cada_hora_con_el_estado_principal_roto_avisa_en_su_ventana(
    host: Host,
) -> None:
    """checks.sh y backup-check.sh: en cualquier minuto de la hora ventana,
    aunque el sello del respaldo (de una corrida fuera de la ventana) lo
    silencie."""
    con_hora_utc(host)
    extra = {"SHIFTY_STATE_DIR": _sin_estado(host), "ALERT_EMAIL": "o@x"}

    fuera = host.alertar(
        "backup: viejo", "", "backup-viejo", "360", FAKE_HORA_UTC="05:07", **extra
    )
    assert fuera.returncode == 0, fuera.stderr
    assert host.mails() == []

    dentro = host.alertar(
        "backup: viejo", "", "backup-viejo", "360", FAKE_HORA_UTC="06:07", **extra
    )
    assert dentro.returncode == 0, dentro.stderr
    assert "alerta silenciada (backup-viejo)" in dentro.stderr
    mails = host.mails()
    assert len(mails) == 1, dentro.stderr
    assert _asunto(mails[0]).endswith("backup: viejo (estado principal no disponible)")


def test_sin_registro_en_ningun_estado_manda_solo_en_la_ventana(host: Host) -> None:
    for raiz in (host.state, host.raiz / "run"):
        (raiz / "alerts" / ".mails-del-dia.tmp").mkdir(parents=True)
    con_hora_utc(host)

    fuera = host.alertar(
        "b: aviso", "", "b", "0", FAKE_HORA_UTC="05:07", ALERT_EMAIL="o@x"
    )
    assert fuera.returncode == 0, fuera.stderr
    assert host.mails() == []
    assert "fuera de la ventana" in fuera.stderr

    dentro = host.alertar(
        "b: aviso", "", "b", "0", FAKE_HORA_UTC="06:07", ALERT_EMAIL="o@x"
    )
    assert dentro.returncode == 0, dentro.stderr
    mails = host.mails()
    assert len(mails) == 1
    assert _asunto(mails[0]).endswith("b: aviso (sin estado)")


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


# 2026-10-02: con 8 GB los limites de los contenedores casi llenan la RAM y el
# aviso por contenedor no ve que el HOST se queda sin memoria, ni que falta el
# swap que pide docs/DEPLOY_RUNBOOK.md §1.
@pytest.mark.parametrize(
    ("meminfo", "motivo"),
    [
        ({"disponible_mib": 500}, "quedan 500 MiB disponibles"),
        ({"swap_mib": 0, "swap_libre_mib": 0}, "no tiene swap"),
        ({"swap_libre_mib": 900}, "usa el 56 % de su swap"),
    ],
    ids=["poca-memoria-disponible", "sin-swap", "swap-en-uso"],
)
def test_checks_alerta_la_memoria_del_host(
    host: Host, meminfo: dict[str, int], motivo: str
) -> None:
    escribir_meminfo(host.fake / "meminfo", **meminfo)

    resultado = host.correr(
        "checks.sh",
        DOMAIN="shifty.example.com",
        FAKE_CERT_END=_fecha_en(60),
        STATS_LOG=(host.raiz / "stats.log").as_posix(),
    )

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr
    assert motivo in resultado.stderr


def test_checks_sin_meminfo_legible_avisa(host: Host) -> None:
    resultado = host.correr(
        "checks.sh",
        DOMAIN="shifty.example.com",
        FAKE_CERT_END=_fecha_en(60),
        STATS_LOG=(host.raiz / "stats.log").as_posix(),
        HOST_MEMINFO=(host.raiz / "no-existe").as_posix(),
    )

    assert resultado.returncode != 0
    assert "no se pudo leer" in resultado.stderr


# --- redis_state ---------------------------------------------------------------
#
# 2026-10-03: redis_state corre con `maxmemory 48mb` y `noeviction`; lleno,
# cada escritura falla y auth, OTP y la reserva publica responden 503. El aviso
# por contenedor mira el limite del cgroup (96M), que un maxmemory de 48 MB
# nunca alcanza: hay que preguntarle a Redis.

MIB = 1048576


def _correr_checks(host: Host, **extra: str) -> subprocess.CompletedProcess[str]:
    return host.correr(
        "checks.sh",
        DOMAIN="shifty.example.com",
        FAKE_CERT_END=_fecha_en(60),
        STATS_LOG=(host.raiz / "stats.log").as_posix(),
        **extra,
    )


@pytest.mark.parametrize(
    ("usada_mib", "avisa"),
    [(38, False), (39, True), (48, True)],
    ids=["79-por-ciento", "81-por-ciento", "llena"],
)
def test_checks_avisa_cuando_redis_state_pasa_el_80_por_ciento(
    host: Host, usada_mib: int, avisa: bool
) -> None:
    escribir_redis_info(host.fake / "redis_info", usada=usada_mib * MIB)

    resultado = _correr_checks(host)

    assert _hay(
        host.llamadas(), r"docker compose exec -T redis_state redis-cli INFO memory"
    )
    if avisa:
        assert resultado.returncode != 0
        assert "ALERTA: redis_state: usa el" in resultado.stderr
        assert f"({usada_mib} de 48 MiB)" in resultado.stderr
    else:
        assert resultado.returncode == 0, resultado.stderr
        assert "ALERTA" not in resultado.stderr
        assert "redis_state al 79 %" in resultado.stderr


def test_checks_avisa_si_no_puede_leer_redis_state(host: Host) -> None:
    resultado = _correr_checks(host, FAKE_REDIS_EXIT="1")

    assert resultado.returncode != 0
    assert "redis_state: no se pudo leer INFO memory" in resultado.stderr


def test_una_respuesta_ilegible_de_redis_no_pasa_por_maxmemory_en_cero(
    host: Host,
) -> None:
    (host.fake / "redis_info").write_text(
        "NOAUTH Authentication required.\n", encoding="utf-8"
    )

    resultado = _correr_checks(host)

    assert resultado.returncode != 0
    assert "redis_state: no se pudo leer INFO memory" in resultado.stderr
    assert "sin maxmemory" not in resultado.stderr


def test_checks_avisa_si_redis_state_corre_sin_maxmemory(host: Host) -> None:
    escribir_redis_info(host.fake / "redis_info", usada=10 * MIB, maxima=0)

    resultado = _correr_checks(host)

    assert resultado.returncode != 0
    assert "redis_state: corre sin maxmemory" in resultado.stderr


def test_checks_le_pregunta_a_redis_desde_el_clon_con_la_version_en_curso(
    host: Host, tmp_path: Path
) -> None:
    """El compose de produccion exige APP_VERSION hasta para `exec`, y el
    proyecto sale del directorio: cron no da ninguna de las dos."""
    (host.repo / ".deploy").mkdir()
    (host.repo / ".deploy" / "current").write_text("v7\n", encoding="utf-8")
    otro = tmp_path / "otro"
    otro.mkdir()

    resultado = host.correr_desde(
        otro,
        "checks.sh",
        DOMAIN="shifty.example.com",
        FAKE_CERT_END=_fecha_en(60),
        STATS_LOG=(host.raiz / "stats.log").as_posix(),
        FAKE_EXIGE_VERSION="1",
    )

    assert resultado.returncode == 0, resultado.stderr
    cwd = (host.fake / "cwd").read_text(encoding="utf-8").strip()
    assert Path(cwd).resolve() == host.repo.resolve()


def test_checks_avisa_alarma_de_rabbitmq_sin_reiniciarlo(host: Host) -> None:
    resultado = _correr_checks(
        host,
        FAKE_RABBIT_ALARMS=(
            '{"alarms":[{"resource":"memory"}],"node":"rabbit@rabbitmq","result":"ok"}'
        ),
    )

    assert resultado.returncode != 0
    assert "rabbitmq: hay alarmas activas" in resultado.stderr
    assert _hay(
        host.llamadas(),
        r"docker compose exec -T rabbitmq rabbitmq-diagnostics -q alarms --formatter json",
    )
    assert not _hay(host.llamadas(), r"docker restart .*rabbitmq")


def test_checks_avisa_si_no_puede_consultar_alarmas_de_rabbitmq(host: Host) -> None:
    resultado = _correr_checks(host, FAKE_RABBIT_EXIT="1")

    assert resultado.returncode != 0
    assert "rabbitmq: no se pudieron consultar las alarmas" in resultado.stderr


def test_checks_avisa_respuesta_ilegible_de_alarmas_de_rabbitmq(host: Host) -> None:
    resultado = _correr_checks(host, FAKE_RABBIT_ALARMS="unexpected output")

    assert resultado.returncode != 0
    assert "rabbitmq: hay alarmas activas o una respuesta ilegible" in resultado.stderr


def test_checks_corre_el_chequeo_de_endurecimiento(host: Host) -> None:
    (host.fake / "sshd_T").write_text(
        SSHD_SANO.replace("passwordauthentication no", "passwordauthentication yes"),
        encoding="utf-8",
        newline="\n",
    )

    resultado = _correr_checks(host)

    assert resultado.returncode != 0
    assert "ssh: passwordauthentication es yes" in resultado.stderr


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
