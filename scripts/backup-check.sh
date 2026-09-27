#!/usr/bin/env bash
# Frescura del backup (F0-20): alerta si el ultimo backup EXITOSO (el que
# escribio scripts/backup.sh en $BACKUP_DIR/last-success, con copia fuera del
# host) tiene mas de BACKUP_MAX_AGE_HOURS (26 h: el diario mas 2 h de margen).
# Critico pasadas BACKUP_CRIT_AGE_HOURS (48 h). Lo corre cron cada hora.
#
# Es un chequeo aparte del backup a proposito: si el timer no corre (host
# reiniciado, unit deshabilitado) el backup no puede avisar que no corrio.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${BACKUP_MAX_AGE_HOURS:=26}"
: "${BACKUP_CRIT_AGE_HOURS:=48}"

registro="$BACKUP_DIR/last-success"
if [ ! -r "$registro" ]; then
  alert "backup: no hay ningun backup exitoso registrado" \
    "Falta $registro. Ver: systemctl status shifty-backup.timer" backup-viejo 360
  exit 1
fi

ultimo="$(awk 'NR == 1 { print $1 }' "$registro")"
case "$ultimo" in
  '' | *[!0-9]*)
    alert "backup: $registro es ilegible" "Contenido inesperado." backup-viejo 360
    exit 1
    ;;
esac

edad=$(($(date +%s) - ultimo))
horas=$((edad / 3600))
if [ "$edad" -ge $((BACKUP_CRIT_AGE_HOURS * 3600)) ]; then
  alert "backup CRITICO: el ultimo exitoso tiene $horas h" \
    "RPO de 24 h incumplido. Ver: journalctl -u shifty-backup" backup-viejo 180
  exit 1
fi
if [ "$edad" -ge $((BACKUP_MAX_AGE_HOURS * 3600)) ]; then
  alert "backup: el ultimo exitoso tiene $horas h" \
    "Aviso sobre $BACKUP_MAX_AGE_HOURS h. Ver: journalctl -u shifty-backup" backup-viejo 360
  exit 1
fi
log "backup-check: ultimo backup exitoso hace $horas h"
