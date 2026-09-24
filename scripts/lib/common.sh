# shellcheck shell=bash
# Funciones comunes de los scripts de operacion del host (deploy, backup,
# guard, chequeos). Se carga con:
#
#   . "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
#
# Corre en el VPS, como root (cron/systemd) o como el usuario del deploy. No
# usa sudo ni toca docker.sock: todo pasa por el CLI de docker.

# Configuracion del host: FUERA del repo y FUERA del .env de la app (ese lleva
# los secretos de la aplicacion y lo lee compose). Plantilla en
# deploy/ops.env.example.
SHIFTY_OPS_ENV="${SHIFTY_OPS_ENV:-/etc/shifty/ops.env}"
if [ -r "$SHIFTY_OPS_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$SHIFTY_OPS_ENV"
  set +a
fi

# Clon del repo en el servidor: ahi estan el compose, el .env (con
# COMPOSE_FILE y COMPOSE_PROJECT_NAME) y .deploy/. Por defecto, el clon del
# que sale el script: asi el de staging (otro clon, otro proyecto de compose)
# nunca actua sobre produccion. No fijarlo en ops.env si ese archivo se
# comparte entre los dos.
: "${SHIFTY_DIR:=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# Estado de los scripts (contadores del guard, silencios de alertas).
: "${SHIFTY_STATE_DIR:=/var/lib/shifty}"
# Directorio del host montado como volumen en /backups del servicio db.
: "${BACKUP_DIR:=/var/backups/shifty}"
# Proyecto de compose (label com.docker.compose.project). Tiene que coincidir
# con COMPOSE_PROJECT_NAME del .env del servidor.
: "${COMPOSE_PROJECT_NAME:=shifty}"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

# Escapa un texto para meterlo entre comillas en un JSON.
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\r'/}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

# alert <asunto> <detalle> [clave] [minutos]
#
# Avisa por webhook (ALERT_WEBHOOK_URL: Slack/Discord/cualquier receptor de
# JSON) y/o por mail (ALERT_EMAIL, con msmtp o sendmail del host), y siempre
# deja la linea en stderr y en syslog. Con <clave>, la misma alerta no se
# repite durante <minutos> (60 por defecto): un chequeo por minuto no manda
# 60 mails por hora. Nunca falla: una alerta que no sale no tumba el script
# que la llama.
alert() {
  local subject="$1" body="${2:-}" key="${3:-}" quiet="${4:-60}"
  # Un asunto con CR/LF inyecta cabeceras en el mail (regla 19).
  subject="${subject//[$'\r\n']/ }"

  if [ -n "$key" ]; then
    local stamp_dir="$SHIFTY_STATE_DIR/alerts" stamp
    stamp="$stamp_dir/${key//[^A-Za-z0-9_.-]/_}"
    if [ -f "$stamp" ] && [ -n "$(find "$stamp" -mmin "-$quiet" 2>/dev/null)" ]; then
      log "alerta silenciada ($key): $subject"
      return 0
    fi
    mkdir -p "$stamp_dir" 2>/dev/null || true
    touch "$stamp" 2>/dev/null || true
  fi

  local host
  host="$(hostname 2>/dev/null || echo host)"
  log "ALERTA: $subject${body:+ | $body}"
  if command -v logger >/dev/null 2>&1; then
    logger -t shifty -p user.warning -- "$subject${body:+ | $body}" || true
  fi

  local sent=0
  if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
    local text
    text="$(json_escape "[shifty@$host] $subject${body:+
$body}")"
    # `text` lo lee Slack; `content`, Discord.
    if curl -fsS -m 10 -H 'Content-Type: application/json' \
      --data "{\"text\":\"$text\",\"content\":\"$text\"}" \
      "$ALERT_WEBHOOK_URL" >/dev/null 2>&1; then
      sent=1
    else
      log "no se pudo mandar la alerta al webhook"
    fi
  fi
  if [ -n "${ALERT_EMAIL:-}" ]; then
    local mailer=""
    if command -v msmtp >/dev/null 2>&1; then
      mailer="msmtp"
    elif command -v sendmail >/dev/null 2>&1; then
      mailer="sendmail"
    fi
    if [ -n "$mailer" ]; then
      if printf 'To: %s\nSubject: [shifty@%s] %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n' \
        "$ALERT_EMAIL" "$host" "$subject" "$body" | "$mailer" -t; then
        sent=1
      else
        log "no se pudo mandar la alerta por mail ($mailer)"
      fi
    else
      log "ALERT_EMAIL definido pero el host no tiene msmtp ni sendmail"
    fi
  fi
  if [ "$sent" != 1 ]; then
    log "ninguna alerta salio del host: definir ALERT_WEBHOOK_URL o ALERT_EMAIL en $SHIFTY_OPS_ENV"
  fi
  return 0
}

# Hay un deploy en curso si existe su lock y es reciente (un deploy colgado o
# matado con -9 no bloquea al guard para siempre).
deploy_in_progress() {
  local lock="$SHIFTY_DIR/.deploy/lock"
  [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin -"${DEPLOY_LOCK_MAX_MINUTES:-30}" 2>/dev/null)" ]
}

# Porcentaje de uso del filesystem que contiene <ruta> (sin el %).
disk_use_percent() {
  df -P "$1" | awk 'NR == 2 { sub("%", "", $5); print $5 }'
}
