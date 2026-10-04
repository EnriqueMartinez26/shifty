"""scripts/host-hardening-check.sh: el endurecimiento del VPS sigue en pie.

2026-10-03. docs/DEPLOY_RUNBOOK.md §1 pide un usuario sudo sin root por SSH,
SSH solo con clave, ufw con 22/80/443, unattended-upgrades solo de seguridad y
sin reinicio automatico, y fail2ban para sshd. Son pasos a mano: nada avisaba
si despues alguien (o un drop-in de cloud-init) los deshacia. checks.sh corre
este script cada hora. Se prueba con binarios falsos (tests/unit/host_falso.py)
que devuelven la salida real de `sshd -T`, `ufw status verbose` y
`apt-config dump`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.host_falso import APT_SANO, SSHD_SANO, UFW_SANO, Host, crear_host

SCRIPT = "host-hardening-check.sh"


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return crear_host(tmp_path)


def _escribir(host: Host, archivo: str, contenido: str) -> None:
    (host.fake / archivo).write_text(contenido, encoding="utf-8", newline="\n")


def test_un_host_endurecido_no_avisa(host: Host) -> None:
    resultado = host.correr(SCRIPT)

    assert resultado.returncode == 0, resultado.stderr
    assert "ALERTA" not in resultado.stderr
    assert "endurecimiento: todo en orden" in resultado.stderr
    llamadas = host.llamadas()
    # La configuracion EFECTIVA de sshd, no el archivo: un drop-in de
    # /etc/ssh/sshd_config.d gana sobre sshd_config.
    assert "sshd -T" in llamadas
    assert "ufw status verbose" in llamadas
    assert "fail2ban-client status sshd" in llamadas


@pytest.mark.parametrize(
    ("archivo", "antes", "despues", "motivo"),
    [
        (
            "sshd_T",
            "passwordauthentication no",
            "passwordauthentication yes",
            "ssh: passwordauthentication es yes",
        ),
        (
            "sshd_T",
            "permitrootlogin no",
            "permitrootlogin prohibit-password",
            "ssh: permitrootlogin es prohibit-password",
        ),
        (
            "sshd_T",
            "kbdinteractiveauthentication no\n",
            "",
            "ssh: kbdinteractiveauthentication es ?",
        ),
        ("ufw_status", "Status: active", "Status: inactive", "ufw no esta activo"),
        (
            "ufw_status",
            "Default: deny (incoming)",
            "Default: allow (incoming)",
            "no deniega el trafico entrante",
        ),
        (
            "ufw_status",
            "443/tcp (v6)",
            "5432/tcp                   ALLOW IN    Anywhere\n443/tcp (v6)",
            "ufw abre mas que 22/tcp 80/tcp 443/tcp: 5432/tcp",
        ),
        (
            "apt_config",
            'APT::Periodic::Unattended-Upgrade "1";',
            'APT::Periodic::Unattended-Upgrade "0";',
            "unattended-upgrades no esta prendido",
        ),
        (
            "apt_config",
            'Automatic-Reboot "false"',
            'Automatic-Reboot "true"',
            "reinicia el host solo",
        ),
        (
            "apt_config",
            'Unattended-Upgrade::Automatic-Reboot "false";',
            'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-updates";\n'
            'Unattended-Upgrade::Automatic-Reboot "false";',
            "instala mas que parches de seguridad",
        ),
    ],
    ids=[
        "ssh-con-clave",
        "ssh-root-con-clave",
        "ssh-kbdinteractive-sin-valor",
        "ufw-inactivo",
        "ufw-entrante-permitido",
        "ufw-puerto-de-mas",
        "sin-unattended-upgrades",
        "reinicio-automatico",
        "origen-updates",
    ],
)
def test_avisa_cada_paso_deshecho(
    host: Host, archivo: str, antes: str, despues: str, motivo: str
) -> None:
    sano = {"sshd_T": SSHD_SANO, "ufw_status": UFW_SANO, "apt_config": APT_SANO}[
        archivo
    ]
    assert antes in sano
    _escribir(host, archivo, sano.replace(antes, despues))

    resultado = host.correr(SCRIPT)

    assert resultado.returncode != 0
    assert "ALERTA" in resultado.stderr
    assert motivo in resultado.stderr


def test_un_puerto_limitado_permitido_no_avisa(host: Host) -> None:
    """`ufw limit 22/tcp` es una forma valida de abrir SSH."""
    _escribir(
        host,
        "ufw_status",
        UFW_SANO.replace(
            "22/tcp                     ALLOW IN", "22/tcp                     LIMIT IN"
        ),
    )

    resultado = host.correr(SCRIPT)

    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize(
    ("variable", "motivo"),
    [
        ("FAKE_SSHD_EXIT", "ssh: sshd -T fallo"),
        ("FAKE_UFW_EXIT", "firewall: ufw status fallo"),
        ("FAKE_FAIL2BAN_EXIT", "fail2ban: la jail sshd no esta activa"),
    ],
    ids=["sshd-invalido", "ufw-falla", "fail2ban-sin-jail"],
)
def test_un_comando_que_falla_es_un_problema(
    host: Host, variable: str, motivo: str
) -> None:
    resultado = host.correr(SCRIPT, **{variable: "1"})

    assert resultado.returncode != 0
    assert motivo in resultado.stderr


def test_un_reinicio_pendiente_avisa_con_los_paquetes(host: Host) -> None:
    """unattended-upgrades no reinicia solo: alguien tiene que enterarse."""
    bandera = host.fake / "reboot-required"
    bandera.write_text("*** System restart required ***\n", encoding="utf-8")
    (host.fake / "reboot-required.pkgs").write_text(
        "linux-image-6.8.0-45-generic\nlibc6\n", encoding="utf-8", newline="\n"
    )

    resultado = host.correr(SCRIPT)

    assert resultado.returncode != 0
    assert "hay un reinicio pendiente" in resultado.stderr
    assert "linux-image-6.8.0-45-generic libc6" in resultado.stderr


def test_las_alertas_repetidas_se_silencian(host: Host) -> None:
    _escribir(
        host, "ufw_status", UFW_SANO.replace("Status: active", "Status: inactive")
    )

    primera = host.correr(SCRIPT)
    segunda = host.correr(SCRIPT)

    assert "ALERTA: firewall: ufw no esta activo" in primera.stderr
    assert "alerta silenciada (ufw)" in segunda.stderr
    # Silenciada no es resuelta: el script sigue saliendo con 1.
    assert segunda.returncode != 0
