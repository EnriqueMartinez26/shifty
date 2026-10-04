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
# - Memoria del HOST (/proc/meminfo): aviso si MemAvailable baja de
#   HOST_MEM_MIN_AVAILABLE_PERCENT (10 %) de la RAM, si no hay swap o si el
#   swap pasa HOST_SWAP_MAX_PERCENT (50 %) de uso. En un VPS de 8 GB los
#   limites de los contenedores casi llenan la RAM (docs/DEPLOY_RUNBOOK.md
#   §1): el aviso por contenedor no ve que el host entero se queda sin nada.
# - redis_state (`INFO memory`): aviso si used_memory pasa
#   REDIS_STATE_MEM_MAX_PERCENT (80 %) de su maxmemory. Con noeviction, lleno
#   es 503 en auth, OTP y la reserva publica.
# - Endurecimiento del host (scripts/host-hardening-check.sh): sshd solo con
#   clave, ufw activo con 22/80/443, unattended-upgrades solo de seguridad y
#   sin reinicio automatico, fail2ban y reinicio pendiente.
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
: "${HOST_MEMINFO:=/proc/meminfo}"
: "${HOST_MEM_MIN_AVAILABLE_PERCENT:=10}"
: "${HOST_SWAP_MAX_PERCENT:=50}"
: "${REDIS_STATE_SERVICE:=redis_state}"
: "${REDIS_STATE_MEM_MAX_PERCENT:=80}"

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

chequear_memoria_host() {
  local valores total disponible swap_total swap_libre
  # kB, como los da el kernel. Un campo que falta queda en 0.
  if ! valores="$(awk '
    /^MemTotal:/ { t = $2 } /^MemAvailable:/ { a = $2 }
    /^SwapTotal:/ { st = $2 } /^SwapFree:/ { sf = $2 }
    END { print t + 0, a + 0, st + 0, sf + 0 }' "$HOST_MEMINFO" 2>/dev/null)"; then
    problema "memoria del host: no se pudo leer $HOST_MEMINFO" "" mem-host 360
    return
  fi
  read -r total disponible swap_total swap_libre <<<"$valores"
  if [ "$total" -le 0 ]; then
    problema "memoria del host: $HOST_MEMINFO no trae MemTotal" "" mem-host 360
    return
  fi

  local porcentaje=$((disponible * 100 / total))
  if [ "$porcentaje" -lt "$HOST_MEM_MIN_AVAILABLE_PERCENT" ]; then
    problema "memoria del host: quedan $((disponible / 1024)) MiB disponibles de $((total / 1024)) ($porcentaje %)" \
      "Aviso bajo $HOST_MEM_MIN_AVAILABLE_PERCENT %: el OOM killer del host esta cerca. Ver docker stats y $STATS_LOG." \
      mem-host 60
  else
    log "checks: memoria del host disponible $porcentaje %"
  fi

  if [ "$swap_total" -le 0 ]; then
    problema "swap: el host no tiene swap" \
      "docs/DEPLOY_RUNBOOK.md §1: swapfile de 2 GB con vm.swappiness=10" swap 360
    return
  fi
  local swap_usado=$(((swap_total - swap_libre) * 100 / swap_total))
  if [ "$swap_usado" -ge "$HOST_SWAP_MAX_PERCENT" ]; then
    problema "swap: el host usa el $swap_usado % de su swap" \
      "Con vm.swappiness=10 el swap solo crece bajo presion de memoria sostenida: revisar que contenedor crecio." \
      swap 360
  fi
}

# redis_state no desaloja (`noeviction`, maxmemory 48mb en docker-compose.yml):
# lleno, cada escritura falla y auth, OTP y la reserva publica responden 503
# (RATE_LIMIT_FAIL_CLOSED). El aviso de `docker stats` mira el limite del
# cgroup (96M), al que un maxmemory de 48 MB nunca llega: hay que preguntarle a
# Redis. redis_cache no se mira: un cache en su maxmemory es lo esperado
# (volatile-ttl desaloja), no un problema.
chequear_redis_state() {
  local salida
  # Compose toma el proyecto y COMPOSE_FILE del clon, y el compose de
  # produccion exige APP_VERSION hasta para `exec` (.deploy/current). En un
  # subshell: el cd y la version no se filtran al resto de los chequeos.
  if ! salida="$(cd "$SHIFTY_DIR" && usar_version_en_curso &&
    docker compose exec -T "$REDIS_STATE_SERVICE" redis-cli INFO memory 2>&1)"; then
    problema "redis_state: no se pudo leer INFO memory" \
      "docker compose exec -T $REDIS_STATE_SERVICE redis-cli INFO memory: ${salida:0:200}" \
      redis-state-mem 60
    return
  fi
  local usada maxima
  # redis-cli termina cada linea de INFO con CRLF. Un campo que falta sale
  # como `-`: no es lo mismo una respuesta ilegible que un maxmemory en 0.
  read -r usada maxima < <(printf '%s\n' "$salida" | awk -F: '
    { gsub("\r", "") }
    $1 == "used_memory" { u = $2 } $1 == "maxmemory" { m = $2 }
    END { print (u ~ /^[0-9]+$/ ? u : "-"), (m ~ /^[0-9]+$/ ? m : "-") }')
  if [ "$usada" = - ] || [ "$maxima" = - ]; then
    problema "redis_state: no se pudo leer INFO memory" \
      "Sin used_memory o maxmemory en la respuesta: ${salida:0:200}" \
      redis-state-mem 60
    return
  fi
  if [ "$maxima" -le 0 ]; then
    problema "redis_state: corre sin maxmemory" \
      "docker-compose.yml lo fija en 48mb con noeviction; sin tope crece hasta que el OOM killer lo mata" \
      redis-state-mem 360
    return
  fi
  local porcentaje=$((usada * 100 / maxima))
  if [ "$porcentaje" -ge "$REDIS_STATE_MEM_MAX_PERCENT" ]; then
    problema "redis_state: usa el $porcentaje % de su maxmemory ($((usada / 1048576)) de $((maxima / 1048576)) MiB)" \
      "Con noeviction, al 100 % auth, OTP y la reserva publica responden 503. Claves grandes: docker compose exec $REDIS_STATE_SERVICE redis-cli --bigkeys" \
      redis-state-mem 60
  else
    log "checks: redis_state al $porcentaje % de su maxmemory"
  fi
}

# Avisa por su cuenta (alertas con clave propia); aca solo cuenta si hubo
# problemas.
chequear_endurecimiento() {
  if ! "$BASH" "$(dirname "${BASH_SOURCE[0]}")/host-hardening-check.sh"; then
    problemas=$((problemas + 1))
  fi
}

chequear_ntp
chequear_certificado
chequear_disco
chequear_contenedores
chequear_memoria_host
chequear_redis_state
chequear_endurecimiento

if [ "$problemas" -gt 0 ]; then
  log "checks: $problemas problema(s)"
  exit 1
fi
log "checks: todo en orden"
