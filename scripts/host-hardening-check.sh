#!/usr/bin/env bash
# Verifica el endurecimiento del VPS (docs/DEPLOY_RUNBOOK.md §1, "Host:
# hardening"). Lo llama scripts/checks.sh cada hora, como root; despues del
# setup se corre a mano para confirmarlo (`sudo bash
# scripts/host-hardening-check.sh`: `sshd -T`, `ufw status` y
# `fail2ban-client` necesitan root).
#
# - sshd EFECTIVO (`sshd -T`, no el archivo): passwordauthentication,
#   permitrootlogin y kbdinteractiveauthentication en `no`. Se mira la
#   configuracion efectiva porque un drop-in de /etc/ssh/sshd_config.d (el
#   50-cloud-init.conf de algunas imagenes trae `PasswordAuthentication yes`)
#   gana sobre lo que diga sshd_config.
# - ufw activo, entrante denegado por defecto y sin otra regla de entrada que
#   HARDENING_UFW_ALLOWED (22/tcp 80/tcp 443/tcp). Docker publica por fuera de
#   ufw (cadena DOCKER-USER); eso lo cubre que en produccion solo nginx
#   publique puertos (test_en_produccion_solo_nginx_publica_puertos).
# - unattended-upgrades prendido, solo con origenes de seguridad y sin
#   reinicio automatico.
# - fail2ban con la jail sshd activa.
# - Reinicio pendiente (/var/run/reboot-required): avisa una vez por dia; el
#   reinicio es manual, en una ventana (runbook §1).
#
# Cada problema avisa con su clave (silencio de 6 h) y el script sale con 1 si
# hubo alguno.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${HARDENING_UFW_ALLOWED:=22/tcp 80/tcp 443/tcp}"
: "${HARDENING_REBOOT_FLAG:=/var/run/reboot-required}"

problemas=0
problema() {
  problemas=$((problemas + 1))
  alert "$@"
}

chequear_sshd() {
  if ! command -v sshd >/dev/null 2>&1; then
    problema "ssh: no se puede verificar (el host no tiene sshd en el PATH)" "" ssh-sin-sshd 360
    return
  fi
  local efectiva
  if ! efectiva="$(sshd -T 2>&1)"; then
    problema "ssh: sshd -T fallo (configuracion invalida o sin root)" "${efectiva:0:200}" ssh-config 360
    return
  fi
  local opcion actual
  for opcion in passwordauthentication permitrootlogin kbdinteractiveauthentication; do
    actual="$(printf '%s\n' "$efectiva" | awk -v k="$opcion" '$1 == k { print $2; exit }')"
    if [ "$actual" != no ]; then
      problema "ssh: $opcion es ${actual:-?}, tiene que ser no" \
        "Revisar /etc/ssh/sshd_config.d/*.conf y /etc/ssh/sshd_config (gana el primero que la fija); docs/DEPLOY_RUNBOOK.md §1" \
        "ssh-$opcion" 360
    fi
  done
}

chequear_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    problema "firewall: el host no tiene ufw" "docs/DEPLOY_RUNBOOK.md §1" ufw 360
    return
  fi
  local estado
  # En C: ufw traduce su salida ("Estado: activo") y aca se la parsea.
  if ! estado="$(LC_ALL=C ufw status verbose 2>&1)"; then
    problema "firewall: ufw status fallo" "${estado:0:200}" ufw 360
    return
  fi
  case "$estado" in
    "Status: active"*) ;;
    *)
      problema "firewall: ufw no esta activo" "docs/DEPLOY_RUNBOOK.md §1: ufw enable" ufw 360
      return
      ;;
  esac
  if ! printf '%s\n' "$estado" | grep -q '^Default: deny (incoming)'; then
    problema "firewall: ufw no deniega el trafico entrante por defecto" \
      "ufw default deny incoming" ufw-default 360
  fi
  # Reglas de entrada (ALLOW IN / LIMIT IN); la de v6 repite el puerto.
  local extra
  extra="$(printf '%s\n' "$estado" | awk -v ok=" $HARDENING_UFW_ALLOWED " '
    / (ALLOW|LIMIT) IN / && index(ok, " " $1 " ") == 0 { print $1 }' | sort -u | tr '\n' ' ')"
  if [ -n "${extra// /}" ]; then
    problema "firewall: ufw abre mas que $HARDENING_UFW_ALLOWED: ${extra% }" \
      "ufw status numbered; ufw delete <n>" ufw-reglas 360
  fi
}

chequear_actualizaciones() {
  if ! command -v apt-config >/dev/null 2>&1; then
    problema "actualizaciones: no se puede verificar (el host no tiene apt-config)" "" apt 360
    return
  fi
  local config
  config="$(apt-config dump 2>/dev/null || true)"
  if ! printf '%s\n' "$config" | grep -q '^APT::Periodic::Unattended-Upgrade "1";'; then
    problema "actualizaciones: unattended-upgrades no esta prendido" \
      "/etc/apt/apt.conf.d/20auto-upgrades (docs/DEPLOY_RUNBOOK.md §1)" apt-auto 360
  fi
  if printf '%s\n' "$config" | grep -q '^Unattended-Upgrade::Automatic-Reboot "true";'; then
    problema "actualizaciones: unattended-upgrades reinicia el host solo" \
      "El reinicio es manual, en una ventana: Unattended-Upgrade::Automatic-Reboot \"false\"" apt-reboot 360
  fi
  # Solo seguridad: -updates, -proposed o -backports traen cambios que no son
  # parches y se instalarian sin que nadie mire.
  local origenes
  origenes="$(printf '%s\n' "$config" |
    grep -E '^Unattended-Upgrade::(Allowed-Origins|Origins-Pattern)::' |
    grep -E -- '-(updates|proposed|backports)' || true)"
  if [ -n "$origenes" ]; then
    problema "actualizaciones: unattended-upgrades instala mas que parches de seguridad" \
      "$origenes" apt-origenes 360
  fi
}

chequear_fail2ban() {
  if ! command -v fail2ban-client >/dev/null 2>&1; then
    problema "fail2ban: no esta instalado" "docs/DEPLOY_RUNBOOK.md §1" fail2ban 360
    return
  fi
  if ! fail2ban-client status sshd >/dev/null 2>&1; then
    problema "fail2ban: la jail sshd no esta activa" \
      "systemctl status fail2ban; fail2ban-client status sshd" fail2ban 360
  fi
}

chequear_reinicio_pendiente() {
  [ -e "$HARDENING_REBOOT_FLAG" ] || return 0
  local paquetes
  paquetes="$(tr '\n' ' ' 2>/dev/null <"$HARDENING_REBOOT_FLAG.pkgs" || true)"
  paquetes="${paquetes% }"
  problema "host: hay un reinicio pendiente por actualizaciones" \
    "Reiniciar a mano en una ventana (docs/DEPLOY_RUNBOOK.md §1).${paquetes:+ Paquetes: $paquetes}" \
    reinicio-pendiente 1440
}

chequear_sshd
chequear_ufw
chequear_actualizaciones
chequear_fail2ban
chequear_reinicio_pendiente

if [ "$problemas" -gt 0 ]; then
  log "endurecimiento: $problemas problema(s)"
  exit 1
fi
log "endurecimiento: todo en orden"
