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
else
  # deploy.sh corre como el usuario `deploy`: con ops.env root 0600 (o
  # /etc/shifty root 0700, donde ni se ve si el archivo existe) se salteaba
  # en silencio y el deploy seguia sin DOMAIN, alertas ni token (primer
  # deploy, 2026-10-08). `log` todavia no existe: mismo formato.
  _ops_env_dir="${SHIFTY_OPS_ENV%/*}"
  _ops_env_aviso=""
  if [ -e "$SHIFTY_OPS_ENV" ]; then
    _ops_env_aviso="$SHIFTY_OPS_ENV existe pero no se puede leer"
  elif [ "$_ops_env_dir" != "$SHIFTY_OPS_ENV" ] && [ -d "$_ops_env_dir" ] && [ ! -x "$_ops_env_dir" ]; then
    _ops_env_aviso="no puedo entrar a $_ops_env_dir: no se sabe si $SHIFTY_OPS_ENV existe"
  fi
  if [ -n "$_ops_env_aviso" ]; then
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      "AVISO: $_ops_env_aviso (uid $(id -u)); sigo con los defaults. Permisos esperados: /etc/shifty root:deploy 0750, ops.env root:deploy 0640 (docs/DEPLOY_RUNBOOK.md §1)" >&2
  fi
  unset _ops_env_dir _ops_env_aviso
fi
# `set -a` exporta todo ops.env. El token de GitHub solo lo usa deploy.sh
# (quality_verde, por stdin de curl): queda como variable del shell, nunca en
# el entorno de docker, compose, rclone ni ningun otro hijo. Aca y no en cada
# script, para que un script nuevo que cargue common.sh nazca sin filtrarlo.
export -n DEPLOY_GITHUB_TOKEN

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
#
# Varios avisos de una misma corrida salen en UN mensaje: alert_add por cada
# problema y alert_flush al final (lo usa el guard). Cada aviso conserva su
# silencio por clave; si todos estan silenciados no sale nada. alert() es
# alert_add + alert_flush.
#
# Presupuesto de mails del host (incidente 2026-11-13: unos 33 mails del
# guard en dos horas a la misma cuenta de Brevo Free, 300 por dia, que usa la
# app; ningun presupuesto de la app los cuenta): a lo sumo
# ALERT_EMAIL_MAX_PER_DAY (12) por dia UTC, y los ultimos
# ALERT_EMAIL_RESERVED_PER_DAY (3) solo para claves que todavia no salieron
# por mail ese dia, para que un incidente nuevo llegue. Pasado el
# presupuesto el mail no sale: queda en stderr y syslog, y el proximo mail
# que salga dice cuantos se suprimieron. El webhook no gasta presupuesto. El
# sello del silencio se escribe antes de mandar: un envio que falla se anota
# y no se reintenta. El estado se toca con flock; si no se puede escribir,
# manda igual y lo anota.
alert() {
  alert_add "$@"
  alert_flush
}

_ALERT_ASUNTOS=()
_ALERT_DETALLES=()
_ALERT_CLAVES=()
_ALERT_SILENCIOS=()

# alert_add <asunto> <detalle> [clave] [minutos]: encola un aviso para el
# proximo alert_flush.
alert_add() {
  local subject="${1:-}"
  # Un asunto con CR/LF inyecta cabeceras en el mail (regla 19).
  subject="${subject//[$'\r\n']/ }"
  _ALERT_ASUNTOS+=("$subject")
  _ALERT_DETALLES+=("${2:-}")
  _ALERT_CLAVES+=("${3:-}")
  _ALERT_SILENCIOS+=("${4:-60}")
}

# alert_flush [prefijo]: manda lo encolado en un solo mensaje. Con un aviso,
# su asunto y su detalle tal cual; con varios, "<prefijo>: N avisos en esta
# corrida" y una linea por aviso.
alert_flush() {
  local prefijo="${1:-}" n="${#_ALERT_ASUNTOS[@]}"
  [ "$n" -gt 0 ] || return 0
  local asuntos=("${_ALERT_ASUNTOS[@]}") detalles=("${_ALERT_DETALLES[@]}")
  local claves=("${_ALERT_CLAVES[@]}") silencios=("${_ALERT_SILENCIOS[@]}")
  _ALERT_ASUNTOS=()
  _ALERT_DETALLES=()
  _ALERT_CLAVES=()
  _ALERT_SILENCIOS=()

  # Sello y presupuesto se leen y escriben bajo un lock: dos procesos a la
  # vez (corridas apiladas, guard y checks) no mandan dos veces lo mismo.
  local dir="$SHIFTY_STATE_DIR/alerts" estado=1 fd=""
  if ! mkdir -p "$dir" 2>/dev/null || ! [ -w "$dir" ]; then
    estado=0
    log "alertas: no puedo escribir el estado de alertas en $dir; mando sin silencio ni presupuesto"
  elif command -v flock >/dev/null 2>&1; then
    if { exec {fd}>>"$dir/.lock"; } 2>/dev/null; then
      flock -w 15 "$fd" || log "alertas: no pude tomar $dir/.lock en 15 s; sigo sin el"
    else
      fd=""
      log "alertas: no pude abrir $dir/.lock; sigo sin lock"
    fi
  fi

  local i clave stamp idx=() seguimiento=()
  for ((i = 0; i < n; i++)); do
    clave="${claves[$i]}"
    if [ -n "$clave" ] && [ "$estado" = 1 ]; then
      stamp="$dir/${clave//[^A-Za-z0-9_.-]/_}"
      if [ -f "$stamp" ] && [ -n "$(find "$stamp" -mmin "-${silencios[$i]}" 2>/dev/null)" ]; then
        log "alerta silenciada ($clave): ${asuntos[$i]}"
        continue
      fi
      touch "$stamp" 2>/dev/null || log "alertas: no pude escribir $stamp; esta alerta no queda silenciada"
    fi
    idx+=("$i")
    # Sin clave, el asunto identifica la alerta para la reserva del dia.
    clave="${clave:-asunto:${asuntos[$i]}}"
    seguimiento+=("${clave//[$'\r\n']/ }")
  done
  if [ "${#idx[@]}" -eq 0 ]; then
    if [ -n "$fd" ]; then exec {fd}>&-; fi
    return 0
  fi

  local subject body="" linea detalle
  if [ "${#idx[@]}" -eq 1 ]; then
    subject="${asuntos[${idx[0]}]}"
    body="${detalles[${idx[0]}]}"
  else
    subject="${prefijo:+$prefijo: }${#idx[@]} avisos en esta corrida"
    for i in "${idx[@]}"; do
      linea="- ${asuntos[$i]}"
      detalle="${detalles[$i]//[$'\r\n']/ }"
      if [ -n "$detalle" ]; then linea+=": $detalle"; fi
      if [ -n "$body" ]; then body+=$'\n'; fi
      body+="$linea"
    done
  fi

  local mail=0
  _ALERT_NOTA=""
  if [ -n "${ALERT_EMAIL:-}" ]; then
    mail=1
    if [ "$estado" = 1 ]; then
      _alert_presupuesto "$dir" "$subject" "${seguimiento[@]}"
      mail="$_ALERT_MAIL_OK"
    fi
  fi
  if [ -n "$fd" ]; then exec {fd}>&-; fi

  for i in "${idx[@]}"; do
    log "ALERTA: ${asuntos[$i]}${detalles[$i]:+ | ${detalles[$i]}}"
    if command -v logger >/dev/null 2>&1; then
      logger -t shifty -p user.warning -- "${asuntos[$i]}${detalles[$i]:+ | ${detalles[$i]}}" || true
    fi
  done
  _alert_mandar "$subject" "$body" "$mail" "$_ALERT_NOTA"
  return 0
}

# Estado del presupuesto, en $SHIFTY_STATE_DIR/alerts: `.mails-del-dia` (la
# fecha UTC, los mails de ese dia y una clave por linea) y `.mails-suprimidos`
# (una linea "<hora UTC> <asunto>" por mail suprimido desde el ultimo que
# salio). Se llama con el lock de alertas tomado. Deja en _ALERT_MAIL_OK si
# el mail sale (1) o no (0), y en _ALERT_NOTA la cuenta de suprimidos que
# viaja en el mail que sale. La cuenta se vacia al darle ese mail a msmtp,
# aunque msmtp falle: como el sello, no se reintenta.
_alert_presupuesto() {
  local dir="$1" subject="$2"
  shift 2
  local max="${ALERT_EMAIL_MAX_PER_DAY:-12}" reserva="${ALERT_EMAIL_RESERVED_PER_DAY:-3}"
  [[ "$max" =~ ^(0|[1-9][0-9]*)$ ]] || max=12
  [[ "$reserva" =~ ^(0|[1-9][0-9]*)$ ]] || reserva=3
  if [ "$reserva" -gt "$max" ]; then reserva="$max"; fi
  local registro="$dir/.mails-del-dia" suprimidos="$dir/.mails-suprimidos" hoy
  hoy="$(date -u +%Y-%m-%d)"

  local lineas=() usados=0 claves_hoy=()
  if [ -f "$registro" ]; then
    mapfile -t lineas <"$registro" 2>/dev/null || lineas=()
  fi
  # Otro dia o un registro ilegible arrancan de cero.
  if [ "${#lineas[@]}" -ge 2 ] && [ "${lineas[0]}" = "$hoy" ] &&
    [[ "${lineas[1]}" =~ ^(0|[1-9][0-9]*)$ ]]; then
    usados="${lineas[1]}"
    claves_hoy=("${lineas[@]:2}")
  fi

  local nueva=0 k
  for k in "$@"; do
    if ! _alert_en_lista "$k" "${claves_hoy[@]}"; then
      nueva=1
      break
    fi
  done

  _ALERT_MAIL_OK=1
  _ALERT_NOTA=""
  if [ "$usados" -ge "$max" ] || { [ "$usados" -ge $((max - reserva)) ] && [ "$nueva" = 0 ]; }; then
    if printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$subject" >>"$suprimidos" 2>/dev/null; then
      _ALERT_MAIL_OK=0
    else
      log "alertas: no pude anotar la alerta suprimida en $suprimidos; mando igual"
    fi
    return 0
  fi

  for k in "$@"; do
    _alert_en_lista "$k" "${claves_hoy[@]}" || claves_hoy+=("$k")
  done
  if ! { printf '%s\n' "$hoy" "$((usados + 1))" "${claves_hoy[@]}" >"$registro.tmp" &&
    mv -f "$registro.tmp" "$registro"; } 2>/dev/null; then
    log "alertas: no pude anotar el mail en $registro; mando igual"
  fi

  if [ -s "$suprimidos" ]; then
    local cuantas desde
    cuantas="$(grep -c . "$suprimidos" 2>/dev/null)" || cuantas=0
    desde="$(head -n 1 "$suprimidos" 2>/dev/null)" || desde=""
    desde="${desde%% *}"
    if [ "$cuantas" -gt 0 ]; then
      _ALERT_NOTA="$cuantas alertas suprimidas desde $desde por el presupuesto diario de mails del host (ALERT_EMAIL_MAX_PER_DAY=$max); estan en syslog y en /var/log/shifty."
    fi
    { : >"$suprimidos"; } 2>/dev/null || log "alertas: no pude vaciar $suprimidos"
  fi
  return 0
}

_alert_en_lista() {
  local buscada="$1" elemento
  shift
  for elemento in "$@"; do
    if [ "$elemento" = "$buscada" ]; then return 0; fi
  done
  return 1
}

# _alert_mandar <asunto> <detalle> <mail 1|0> <nota>: un intento por canal,
# sin reintentos. Nunca afirma que el mail llego: solo que msmtp lo acepto.
_alert_mandar() {
  local subject="$1" body="$2" mail="$3" nota="$4"
  local host
  host="$(hostname 2>/dev/null || echo host)"

  local sent=0 suprimida=0
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
  if [ -n "${ALERT_EMAIL:-}" ] && [ "$mail" != 1 ]; then
    suprimida=1
    log "alerta suprimida por presupuesto diario del host: $subject"
    if command -v logger >/dev/null 2>&1; then
      logger -t shifty -p user.warning -- "alerta suprimida por presupuesto diario del host: $subject" || true
    fi
  elif [ -n "${ALERT_EMAIL:-}" ]; then
    local mailer="" cuerpo="$body"
    if [ -n "$nota" ]; then cuerpo="$nota"$'\n\n'"$body"; fi
    if command -v msmtp >/dev/null 2>&1; then
      mailer="msmtp"
    elif command -v sendmail >/dev/null 2>&1; then
      mailer="sendmail"
    fi
    if [ -n "$mailer" ]; then
      # Con DNS caido msmtp puede colgarse (13/11) y el guard espera con su
      # lock tomado: 30 s de tope.
      local con_tope=()
      if command -v timeout >/dev/null 2>&1; then con_tope=(timeout -k 5 30); fi
      if printf 'To: %s\nSubject: [shifty@%s] %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n' \
        "$ALERT_EMAIL" "$host" "$subject" "$cuerpo" | "${con_tope[@]}" "$mailer" -t; then
        sent=1
      else
        log "no se pudo mandar la alerta por mail ($mailer)"
      fi
    else
      log "ALERT_EMAIL definido pero el host no tiene msmtp ni sendmail"
    fi
  fi
  if [ "$sent" != 1 ] && [ "$suprimida" != 1 ]; then
    log "ninguna alerta salio del host: definir ALERT_WEBHOOK_URL o ALERT_EMAIL en $SHIFTY_OPS_ENV"
  fi
  return 0
}

# docker-compose.prod.yml interpola ${APP_VERSION:?}: sin la variable falla
# CUALQUIER comando de compose (exec, logs, ps), no solo `up`. Los scripts de
# cron no la reciben; toman la que dejo el ultimo deploy en .deploy/current.
# deploy.sh NO usa esto: un `make deploy` sin APP_VERSION tiene que fallar.
usar_version_en_curso() {
  if [ -z "${APP_VERSION:-}" ] && [ -s "$SHIFTY_DIR/.deploy/current" ]; then
    APP_VERSION="$(head -n 1 "$SHIFTY_DIR/.deploy/current")"
    export APP_VERSION
  fi
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
