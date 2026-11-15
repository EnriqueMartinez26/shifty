"""scripts/guard.sh y scripts/checks.sh: guard y chequeos del host (F0-21, F0-23).

2026-09-24. `restart: always` no actua sobre un contenedor `unhealthy`, y nadie
miraba el reloj, el certificado ni el disco (R11-05, R11-20). Se corren los
scripts REALES con binarios falsos (tests/unit/host_falso.py).
"""

from __future__ import annotations

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
    crear_host,
    escribir_meminfo,
    escribir_redis_info,
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


def _requiere(binario: str) -> pytest.MarkDecorator:
    """flock (util-linux) no existe en Git Bash: esos tests corren en CI."""
    ruta = str(Path(BASH).parent) if BASH else None
    return pytest.mark.skipif(
        shutil.which(binario, path=ruta) is None and shutil.which(binario) is None,
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


def test_guard_sin_carga_legible_reinicia_como_antes(host: Host) -> None:
    resultado = host.correr(
        "guard.sh",
        FAKE_UNHEALTHY_IDS="abc123",
        GUARD_LOADAVG_FILE=(host.raiz / "no-existe").as_posix(),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert _hay(host.llamadas(), r"docker restart abc123")
    assert "no pude leer la carga" in resultado.stderr


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
    assert "Subject: [shifty@" in mails[0] and "guard: 3 avisos" in mails[0]
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
    assert "guard: 2 avisos" in mails[1]
    assert "rabbitmq" not in mails[1]
    assert "alerta silenciada (guard-no-reinicia-shifty-rabbitmq-1)" in otra.stderr


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


def test_el_presupuesto_diario_guarda_lugar_para_un_incidente_nuevo(
    host: Host,
) -> None:
    """Cada alert() es un proceso nuevo: el contador vive en el estado del
    host, no en memoria. Silencio 0: ninguna clave queda silenciada."""
    p = _presupuesto(3, 1)
    host.alertar("a: uno", "", "a", "0", **p)
    host.alertar("b: dos", "", "b", "0", **p)
    # La reserva es solo para claves que todavia no salieron hoy.
    repetida = host.alertar("a: uno otra vez", "", "a", "0", **p)
    nueva = host.alertar("c: incidente nuevo", "", "c", "0", **p)
    agotada = host.alertar("d: otro nuevo", "", "d", "0", **p)

    asuntos = [_asunto(m) for m in host.mails()]
    assert len(asuntos) == 3, asuntos
    assert asuntos[2].endswith("c: incidente nuevo")
    assert nueva.returncode == 0, nueva.stderr
    for resultado, asunto in (
        (repetida, "a: uno otra vez"),
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
    registro.write_text("\n".join([ayer, *lineas[1:]]) + "\n", encoding="utf-8")

    resultado = host.alertar("d: cuatro", "detalle", "d", "0", **p)

    assert resultado.returncode == 0, resultado.stderr
    mails = host.mails()
    assert len(mails) == 2
    assert _asunto(mails[1]).endswith("d: cuatro")
    assert "2 alertas suprimidas desde 20" in mails[1]
    # Se cuentan una vez: el mail siguiente ya no las repite.
    registro.write_text(ayer + "\n0\n", encoding="utf-8")
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


def test_sin_estado_escribible_la_alerta_sale_igual(host: Host) -> None:
    archivo = host.raiz / "un-archivo"
    archivo.write_text("no soy un directorio\n", encoding="utf-8")
    sin_estado = {
        "SHIFTY_STATE_DIR": (archivo / "estado").as_posix(),
        **_presupuesto(1, 0),
    }

    primera = host.alertar("db caida", "", "db-caida", "60", **sin_estado)
    segunda = host.alertar("db caida", "", "db-caida", "60", **sin_estado)

    assert primera.returncode == 0 and segunda.returncode == 0
    assert len(host.mails()) == 2
    assert "no puedo escribir el estado de alertas" in primera.stderr


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
