#!/usr/bin/env bash
# Backup diario de Postgres (F0-20). Lo corre systemd a las 03:00 de Argentina
# (deploy/systemd/shifty-backup.timer), como root.
#
# 1. pg_dump DENTRO del contenedor `db`, con el rol dueno por el socket local
#    (las variables POSTGRES_USER/POSTGRES_DB son las del contenedor: el host
#    no lee el .env ni usa DATABASE_URL, que es el rol con RLS). Formato
#    directorio, 2 jobs, zstd:3.
# 2. El dump cae en /backups del contenedor, un volumen con nombre atado a
#    BACKUP_DIR del host (/var/backups/shifty). El YAML del volumen esta en
#    docs/BACKUP_RESTORE_RUNBOOK.md.
# 2b. globals.sql dentro del mismo directorio: pg_dumpall --globals-only
#    --no-role-passwords. Los roles son del cluster y el dump de la base no
#    los trae (ni shifty_app ni sus ALTER ROLE ... SET de timeouts); sin
#    contrasenas, que no salen del host. Drill 2026-09-24.
# 3. SHA256SUMS de cada archivo del dump (globals.sql incluido).
# 4. El dia BACKUP_WEEKLY_DAY (7 = domingo) se guarda ademas en weekly/.
# 5. rclone copy a BACKUP_REMOTE (bucket S3-compatible, fuera del host).
# 6. Retencion: 7 diarios y 4 semanales, en el host (por cantidad) y en el
#    bucket (rclone delete --min-age). Solo despues de un backup completo.
# 7. last-success: lo lee scripts/backup-check.sh (alerta pasadas 26 h) y el
#    preflight de scripts/deploy.sh (exige < 24 h).
#
# Sin BACKUP_REMOTE el dump local se hace igual, pero no cuenta como backup
# (RPO fuera del host) salvo BACKUP_ALLOW_LOCAL_ONLY=1 (staging).
set -Eeuo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${BACKUP_CONTAINER_DIR:=/backups}"
: "${BACKUP_REMOTE:=}"
: "${BACKUP_ALLOW_LOCAL_ONLY:=0}"
: "${BACKUP_KEEP_DAILY:=7}"
: "${BACKUP_KEEP_WEEKLY:=4}"
: "${BACKUP_WEEKLY_DAY:=7}"
: "${BACKUP_JOBS:=2}"
# zstd:3 verificado con postgres:16.14-alpine en el drill del 2026-09-24. Con
# otra imagen sin zstd compilado, usar gzip:6.
: "${BACKUP_COMPRESS:=zstd:3}"

nombre="shifty-$(date -u +%Y%m%dT%H%M%SZ)"
diarios="$BACKUP_DIR/daily"
semanales="$BACKUP_DIR/weekly"
a_medias=""

al_fallar() {
  local codigo=$? linea="$1"
  if [ -n "$a_medias" ]; then
    rm -rf -- "$a_medias"
  fi
  alert "backup: fallo (codigo $codigo, linea $linea de backup.sh)" \
    "No se registro exito. Ver: journalctl -u shifty-backup --since today" \
    backup-fallo 60
  exit "$codigo"
}
trap 'al_fallar $LINENO' ERR

# Conserva los <n> mas nuevos de <dir>: los nombres llevan la fecha UTC, asi
# que el orden del glob es el cronologico. Por CANTIDAD, no por edad: si los
# backups dejan de salir, los ultimos buenos no se borran solos.
podar_local() {
  local dir="$1" conservar="$2" items=() i
  shopt -s nullglob
  items=("$dir"/shifty-*/)
  shopt -u nullglob
  for ((i = 0; i < ${#items[@]} - conservar; i++)); do
    log "backup: borro ${items[i]%/}"
    rm -rf -- "${items[i]%/}"
  done
}

cd "$SHIFTY_DIR"
usar_version_en_curso
mkdir -p "$diarios" "$semanales"

a_medias="$diarios/$nombre"
log "backup: pg_dump -> $a_medias"
# Comillas simples: $POSTGRES_USER y $POSTGRES_DB los expande el shell del
# contenedor, con sus propias variables.
# shellcheck disable=SC2016
docker compose exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fd -j "$1" --compress="$2" -f "$3"' \
  sh "$BACKUP_JOBS" "$BACKUP_COMPRESS" "$BACKUP_CONTAINER_DIR/daily/$nombre"

if [ ! -f "$a_medias/toc.dat" ]; then
  log "backup: pg_dump termino pero $a_medias/toc.dat no existe"
  log "backup: el volumen /backups del servicio db no apunta a $BACKUP_DIR"
  false
fi

# Globales por stdout al directorio del dump: viajan con el en el mismo
# checksum y el mismo rclone copy. Si falla, el ERR borra el dump entero.
# shellcheck disable=SC2016
docker compose exec -T db sh -c \
  'pg_dumpall -U "$POSTGRES_USER" -l "$POSTGRES_DB" --globals-only --no-role-passwords' \
  >"$a_medias/globals.sql"

sumas="$diarios/.$nombre.sha256.tmp"
(cd "$a_medias" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"$sumas"
mv "$sumas" "$a_medias/SHA256SUMS"
a_medias=""
log "backup: dump completo ($(du -sh "$diarios/$nombre" | cut -f1))"

semanal=0
if [ "$(date -u +%u)" = "$BACKUP_WEEKLY_DAY" ]; then
  semanal=1
  # Hard links: la copia semanal no ocupa espacio extra en el mismo disco.
  if ! cp -al "$diarios/$nombre" "$semanales/$nombre" 2>/dev/null; then
    rm -rf -- "${semanales:?}/$nombre"
    cp -a "$diarios/$nombre" "$semanales/$nombre"
  fi
fi

if [ -n "$BACKUP_REMOTE" ]; then
  rclone copy "$diarios/$nombre" "$BACKUP_REMOTE/daily/$nombre"
  if [ "$semanal" = 1 ]; then
    rclone copy "$semanales/$nombre" "$BACKUP_REMOTE/weekly/$nombre"
  fi
  # Por edad en el bucket: solo corre despues de subir uno nuevo, asi que
  # siempre queda al menos el de hoy.
  rclone delete --min-age "${BACKUP_KEEP_DAILY}d" "$BACKUP_REMOTE/daily"
  rclone delete --min-age "$((BACKUP_KEEP_WEEKLY * 7))d" "$BACKUP_REMOTE/weekly"
  rclone rmdirs --leave-root "$BACKUP_REMOTE/daily" || true
  rclone rmdirs --leave-root "$BACKUP_REMOTE/weekly" || true
  log "backup: copiado a $BACKUP_REMOTE"
elif [ "$BACKUP_ALLOW_LOCAL_ONLY" != 1 ]; then
  alert "backup: sin copia fuera del host (falta BACKUP_REMOTE)" \
    "El dump $nombre quedo solo en $BACKUP_DIR. Definir BACKUP_REMOTE en $SHIFTY_OPS_ENV." \
    backup-sin-remoto 360
  exit 1
fi

podar_local "$diarios" "$BACKUP_KEEP_DAILY"
podar_local "$semanales" "$BACKUP_KEEP_WEEKLY"

printf '%s %s\n' "$(date -u +%s)" "$nombre" >"$BACKUP_DIR/last-success.tmp"
mv "$BACKUP_DIR/last-success.tmp" "$BACKUP_DIR/last-success"
log "backup: ok $nombre"
