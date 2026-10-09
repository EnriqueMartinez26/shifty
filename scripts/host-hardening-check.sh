#!/usr/bin/env bash
# Verifica el endurecimiento del VPS (docs/DEPLOY_RUNBOOK.md §1, "Host:
# hardening"). Lo llama scripts/checks.sh cada hora, como root; despues del
# setup se corre a mano para confirmarlo (`sudo bash
# scripts/host-hardening-check.sh`: `sshd -T`, `ufw status` y
# `fail2ban-client` necesitan root).
#
# - sshd EFECTIVO (`sshd -T`, tambien con `-C user=deploy` para Match):
#   passwordauthentication, permitrootlogin y kbdinteractiveauthentication
#   en `no`; pubkeyauthentication en `yes`. Se mira la
#   configuracion efectiva porque un drop-in de /etc/ssh/sshd_config.d (el
#   50-cloud-init.conf de algunas imagenes trae `PasswordAuthentication yes`)
#   gana sobre lo que diga sshd_config. Ademas, ningun bloque Match del
#   archivo (o de lo que incluye) reabre password, kbd-interactive ni root:
#   `sshd -T` no ve un Match de otro usuario, grupo o red.
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
: "${HARDENING_OS_RELEASE:=/etc/os-release}"
: "${HARDENING_SSHD_CONFIG:=/etc/ssh/sshd_config}"

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
  local efectiva contexto opcion actual esperado
  for contexto in general deploy; do
    if [ "$contexto" = deploy ]; then
      if ! efectiva="$(sshd -T -C user=deploy,host=localhost,addr=127.0.0.1 2>&1)"; then
        problema "ssh: sshd -T para deploy fallo (configuracion invalida o sin root)" "${efectiva:0:200}" ssh-config-deploy 360
        continue
      fi
    elif ! efectiva="$(sshd -T 2>&1)"; then
      problema "ssh: sshd -T fallo (configuracion invalida o sin root)" "${efectiva:0:200}" ssh-config 360
      continue
    fi
    for opcion in passwordauthentication permitrootlogin kbdinteractiveauthentication pubkeyauthentication; do
      esperado=no
      [ "$opcion" = pubkeyauthentication ] && esperado=yes
      actual="$(printf '%s\n' "$efectiva" | awk -v k="$opcion" '$1 == k { print $2; exit }')"
      if [ "$actual" != "$esperado" ]; then
        problema "ssh: $opcion es ${actual:-?}, tiene que ser $esperado ($contexto)" \
          "Revisar /etc/ssh/sshd_config.d/*.conf y /etc/ssh/sshd_config (gana el primero que la fija); docs/DEPLOY_RUNBOOK.md §1" \
          "ssh-$contexto-$opcion" 360
      fi
    done
  done
  chequear_sshd_match
}

# `sshd -T` evalua un solo contexto (con -C, el de deploy desde 127.0.0.1) y
# un Match que aplica pisa al valor global aunque el drop-in 00 lo fije antes.
# Un grupo, una red u otro usuario no se pueden enumerar con -C, asi que se
# leen los Match del archivo y de lo que incluye (un nivel, como Ubuntu):
# ninguno puede dejar password, kbd-interactive ni root en otro valor que no.
chequear_sshd_match() {
  if [ ! -r "$HARDENING_SSHD_CONFIG" ]; then
    problema "ssh: no se puede leer $HARDENING_SSHD_CONFIG para revisar sus Match" "" ssh-match-config 360
    return
  fi
  local dir patron archivo hallazgos
  local -a archivos=("$HARDENING_SSHD_CONFIG")
  dir="$(dirname "$HARDENING_SSHD_CONFIG")"
  while read -r patron; do
    case "$patron" in /*) ;; *) patron="$dir/$patron" ;; esac
    # Sin comillas a proposito: Include es un glob (sshd_config.d/*.conf).
    # shellcheck disable=SC2086
    for archivo in $patron; do
      [ -f "$archivo" ] && archivos+=("$archivo")
    done
  done < <(awk '{ sub(/^[ \t]+/, ""); sub(/[ \t]*=[ \t]*/, " ") }
    tolower($1) == "include" { for (i = 2; i <= NF; i++) print $i }' "$HARDENING_SSHD_CONFIG")
  # Un awk que falla no corta el script (set -e): el resto de los chequeos
  # tiene que correr igual.
  if ! hallazgos="$(awk '
    FNR == 1 { bloque = "" }
    {
      linea = $0
      sub(/^[ \t]+/, "", linea)
      sub(/^#.*/, "", linea)
      sub(/[ \t]#.*/, "", linea)
      sub(/[ \t]*=[ \t]*/, " ", linea)
      if (split(linea, f, /[ \t]+/) == 0) next
      clave = tolower(f[1])
    }
    clave == "match" { bloque = linea; next }
    bloque != "" && clave ~ /^(passwordauthentication|kbdinteractiveauthentication|challengeresponseauthentication|permitrootlogin)$/ && tolower(f[2]) != "no" {
      printf "%s: %s: %s %s\n", FILENAME, bloque, clave, tolower(f[2])
    }' "${archivos[@]}" 2>&1)"; then
    problema "ssh: no se pudieron leer los archivos de sshd para revisar sus Match" "${hallazgos:0:200}" ssh-match-config 360
  elif [ -n "$hallazgos" ]; then
    problema "ssh: un bloque Match reabre el acceso" \
      "$hallazgos; sacar esas lineas del Match (docs/DEPLOY_RUNBOOK.md §1)" ssh-match 360
  fi
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
  # Una politica deny sin estas aperturas tambien puede cortar SSH o la web.
  # Se exige la regla IPv4 publica; IPv6 puede estar deshabilitado en el VPS.
  local puerto
  for puerto in $HARDENING_UFW_ALLOWED; do
    if ! printf '%s\n' "$estado" | awk -v p="$puerto" '
      $1 == p && ($2 == "ALLOW" || $2 == "LIMIT") && $3 == "IN" && $4 == "Anywhere" { found = 1 }
      END { exit !found }'; then
      problema "firewall: falta permitir $puerto desde Anywhere" \
        "ufw allow $puerto; docs/DEPLOY_RUNBOOK.md §1" "ufw-falta-$puerto" 360
    fi
  done
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
  # El bolsillo ESMApps no reemplaza el de seguridad del sistema operativo.
  # apt acepta variables o el nombre explicito de la version instalada.
  # Esta comprobacion cubre el Allowed-Origins del runbook. Si se configura
  # Origins-Pattern personalizado, verificarlo a mano con
  # `unattended-upgrade --dry-run --debug` antes de aceptar esta alerta.
  local codename="" origen_variable origen_explicito=""
  origen_variable='Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";'
  if [ -r "$HARDENING_OS_RELEASE" ]; then
    codename="$(. "$HARDENING_OS_RELEASE"; printf '%s' "${VERSION_CODENAME:-}")"
    [ -z "$codename" ] || origen_explicito="Unattended-Upgrade::Allowed-Origins:: \"Ubuntu:${codename}-security\";"
  fi
  if ! grep -Fxq "$origen_variable" <<< "$config" &&
    { [ -z "$origen_explicito" ] || ! grep -Fxq "$origen_explicito" <<< "$config"; }; then
    problema "actualizaciones: no se pudo verificar origen de seguridad de Ubuntu en unattended-upgrades" \
      "Revisar /etc/apt/apt.conf.d/50unattended-upgrades y, si usa Origins-Pattern, correr unattended-upgrade --dry-run --debug (docs/DEPLOY_RUNBOOK.md §1)" apt-security 360
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
