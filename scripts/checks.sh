#!/usr/bin/env bash
# Chequeos horarios del host (F0-21, F0-23, F5-01). Los corre cron cada hora
# (deploy/cron/shifty-guard), como root.
#
# - NTP sincronizado (`timedatectl`): con el reloj corrido fallan los tokens,
#   los webhooks de MP (ventana de antiguedad) y los vencimientos.
# - Certificado TLS de DOMAIN: aviso si vence en menos de CERT_MIN_DAYS (20).
#   Se lee el que sirve nginx, no el archivo: detecta tambien un reload que no
#   ocurrio despues de renovar.
# - Disco: aviso sobre DISK_MAX_PERCENT (80 %), critico sobre 90 %.
# - `docker stats` de todos los contenedores, anotado en STATS_LOG (lo rota
#   deploy/logrotate/shifty); aviso si un contenedor pasa STATS_MEM_MAX_PERCENT
#   (90 %) de su limite de memoria.
#
# Cada problema avisa (con silencio de unas horas para no repetir) y el script
# sale con 1 si hubo alguno.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${DOMAIN:=}"
: "${CERT_MIN_DAYS:=20}"
: "${DISK_PATHS:=/ /var/lib/docker $BACKUP_DIR}"
: "${DISK_MAX_PERCENT:=80}"
: "${DISK_CRIT_PERCENT:=90}"
: "${STATS_LOG:=/var/log/shifty/stats.log}"
: "${STATS_MEM_MAX_PERCENT:=90}"

problemas=0
problema() {
  problemas=$((problemas + 1))
  alert "$@"
}

chequear_ntp() {
  if ! command -v timedatectl >/dev/null 2>&1; then
    problema "NTP: no se puede verificar (el host no tiene timedatectl)" "" ntp 360
    return
  fi
  local sincronizado
  sincronizado="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
  if [ "$sincronizado" != yes ]; then
    problema "NTP: el reloj del host no esta sincronizado (NTPSynchronized=${sincronizado:-?})" \
      "Revisar systemd-timesyncd o chrony: timedatectl timesync-status" ntp 360
  fi
}

chequear_certificado() {
  if [ -z "$DOMAIN" ]; then
    log "checks: sin DOMAIN, no se mira el certificado"
    return
  fi
  local fin
  fin="$(echo | timeout 15 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null |
    openssl x509 -noout -enddate 2>/dev/null | sed -n 's/^notAfter=//p')" || true
  if [ -z "$fin" ]; then
    problema "certificado: no se pudo leer el que sirve $DOMAIN:443" "" cert 360
    return
  fi
  local dias
  dias=$((($(date -d "$fin" +%s) - $(date +%s)) / 86400))
  if [ "$dias" -lt "$CERT_MIN_DAYS" ]; then
    problema "certificado: el de $DOMAIN vence en $dias dias ($fin)" \
      "certbot renueva a los 30 dias del vencimiento: revisar 'certbot renew --dry-run' y el deploy hook que recarga nginx" \
      cert 360
  else
    log "checks: certificado de $DOMAIN vence en $dias dias"
  fi
}

chequear_disco() {
  local ruta uso
  for ruta in $DISK_PATHS; do
    [ -e "$ruta" ] || continue
    uso="$(disk_use_percent "$ruta")"
    case "$uso" in '' | *[!0-9]*) continue ;; esac
    if [ "$uso" -ge "$DISK_CRIT_PERCENT" ]; then
      problema "disco CRITICO: $ruta al $uso %" "docker system df; journalctl --vacuum-size; backups viejos en $BACKUP_DIR" "disco-$ruta" 60
    elif [ "$uso" -ge "$DISK_MAX_PERCENT" ]; then
      problema "disco: $ruta al $uso %" "Aviso sobre $DISK_MAX_PERCENT %." "disco-$ruta" 360
    fi
  done
}

chequear_contenedores() {
  local salida
  if ! salida="$(docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}')"; then
    problema "docker stats fallo: el daemon no responde" "" docker-stats 60
    return
  fi
  mkdir -p "$(dirname "$STATS_LOG")"
  local marca
  marca="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\n' "$salida" | sed "s/^/$marca\t/" >>"$STATS_LOG"

  local nombre porcentaje
  while IFS=$'\t' read -r nombre porcentaje; do
    [ -n "$nombre" ] || continue
    problema "memoria: $nombre al $porcentaje % de su limite" \
      "Aviso sobre $STATS_MEM_MAX_PERCENT %: cerca del OOM killer." "mem-$nombre" 60
  done < <(printf '%s\n' "$salida" |
    awk -F'\t' -v tope="$STATS_MEM_MAX_PERCENT" '{ p = $4; sub("%", "", p); if (p + 0 >= tope) print $1 "\t" p }')
}

chequear_ntp
chequear_certificado
chequear_disco
chequear_contenedores

if [ "$problemas" -gt 0 ]; then
  log "checks: $problemas problema(s)"
  exit 1
fi
log "checks: todo en orden"
