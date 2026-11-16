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
# ALERT_EMAIL_RESERVED_PER_DAY (3) solo para claves CRITICAS (_alert_gravedad
# 0) que todavia no salieron por mail ese dia, para que un incidente nuevo
# llegue: un "reinicie X" o un tope no la gastan. Pasado el
# presupuesto el mail no sale: queda en stderr y syslog, y el proximo mail
# que salga dice cuantos se suprimieron. El webhook no gasta presupuesto. El
# sello del silencio se escribe antes de mandar: un envio que falla se anota
# y no se reintenta. El estado se toca con flock.
#
# Estado que no se puede escribir (revision del 2026-11-15: con / de solo
# lectura mandaba sin silencio ni presupuesto, un mail por minuto). Se decide
# creando y borrando un archivo de prueba, no con `[ -w ]` (con los inodos
# agotados o el disco lleno da bien y no se crea nada). Los sellos que fallan,
# los presupuestos ilegibles y los topes cuya supresion no se puede anotar no
# mandan igual:
# - pasa a $SHIFTY_RUN_DIR/alerts (tmpfs, /run/shifty), que sigue escribible
#   con / remontado de solo lectura; se pierde al reiniciar el host y lo anota
#   una vez por corrida.
# - Sin ningun estado escribible (modo sin estado) no hay silencio por clave
#   ni presupuesto diario: cada aviso queda en stderr y en syslog (crit los
#   criticos), y mail y webhook salen solo en una ventana del reloj: las horas
#   UTC multiplo de ALERT_STATELESS_EVERY_HOURS (3), en el minuto 00 para un
#   script que corre cada minuto (el guard), en cualquier minuto para los
#   demas. El guard manda a lo sumo un mensaje por ventana; los demas, uno por
#   llamada a alert() en la hora ventana: checks.sh uno por problema y
#   latency-check.sh (cada 5 minutos) hasta 12. Lo de entre ventanas queda
#   solo en syslog. El mensaje dice que es un envio degradado.
# - Si cualquier intento de estado en la ruta principal falla, un respaldo
#   saludable conserva el silencio por clave para stderr, syslog y webhook,
#   pero su presupuesto no autoriza SMTP: el respaldo podria desconocer mails
#   que ya salieron con el estado principal. El SMTP sigue la misma ventana
#   del modo sin estado (_alert_ventana): fuera de ella se suprime; adentro
#   sale un mail por corrida del guard o por llamada a alert() con TODO lo
#   encolado, silenciado o no (un sello del respaldo escrito entre ventanas
#   las salteaba todas), con "(estado principal no disponible)" en el asunto.
#   Un estado principal roto para siempre (/ de solo lectura, disco lleno,
#   registro con fecha futura) sigue avisando por mail, acotado por la ventana
#   y no por ningun registro: el guard a lo sumo 24/N por dia (8 con N=3), los
#   demas como en el modo sin estado, mas los ALERT_EMAIL_MAX_PER_DAY de las
#   corridas que todavia usen el estado principal. Sin hora legible, se
#   suprime.
# - Si tampoco hay estado utilizable en el respaldo, rige el modo sin estado:
#   SMTP y webhook solo en la ventana UTC documentada, sin presupuesto diario.
alert() {
  alert_add "$@"
  alert_flush
}

_ALERT_ASUNTOS=()
_ALERT_DETALLES=()
_ALERT_CLAVES=()
_ALERT_SILENCIOS=()
# 1 en un script que corre cada minuto (guard.sh): en modo sin estado manda
# solo en el minuto 00 de la ventana.
: "${_ALERT_CADA_MINUTO:=0}"

# shifty_run_dir: valida SHIFTY_RUN_DIR, el respaldo en tmpfs del estado (lock
# del guard y estado de alertas). Una ruta relativa cambia con el directorio
# actual: dos corridas tomarian locks distintos. Invalida, usa /run/shifty.
# La letra de unidad es solo para los tests en Git Bash.
shifty_run_dir() {
  local defecto=/run/shifty
  [ -z "${_SHIFTY_RUN_DIR_VALIDADO:-}" ] || return 0
  _SHIFTY_RUN_DIR_VALIDADO=1
  : "${SHIFTY_RUN_DIR:=$defecto}"
  if ! [[ "$SHIFTY_RUN_DIR" =~ ^([A-Za-z]:)?/[A-Za-z0-9._/-]*[A-Za-z0-9._-]$ ]] ||
    [[ "$SHIFTY_RUN_DIR" =~ (^|/)[.][.]?(/|$) ]]; then
    log "SHIFTY_RUN_DIR=$SHIFTY_RUN_DIR no es una ruta absoluta valida; uso $defecto"
    SHIFTY_RUN_DIR="$defecto"
  fi
}

# crear_run_dir: crea SHIFTY_RUN_DIR solo para su duenio (umask y no
# `mkdir -m`: en Git Bash el chmod de -m falla y mkdir sale 1).
crear_run_dir() {
  (umask 077 && mkdir -p "$SHIFTY_RUN_DIR") 2>/dev/null
}

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
# su asunto y su detalle tal cual; con varios, una linea por aviso, el mas
# grave primero (_alert_gravedad), y de asunto el del mas grave con
# "(+N avisos)": "N avisos en esta corrida" escondia lo importante. El
# prefijo va delante solo si ese asunto no empieza ya con el.
alert_flush() {
  local prefijo="${1:-}" n="${#_ALERT_ASUNTOS[@]}" mail=1
  [ "$n" -gt 0 ] || return 0
  _ALERT_BLOQUEAR_EMAIL=0
  # _alert_con_estado y _alert_componer leen estas variables locales.
  local asuntos=("${_ALERT_ASUNTOS[@]}") detalles=("${_ALERT_DETALLES[@]}")
  local claves=("${_ALERT_CLAVES[@]}") silencios=("${_ALERT_SILENCIOS[@]}")
  _ALERT_ASUNTOS=()
  _ALERT_DETALLES=()
  _ALERT_CLAVES=()
  _ALERT_SILENCIOS=()

  # El estado vive en el primer directorio donde se puede crear un archivo y
  # donde se pudo escribir lo de este envio (sellos y registro del
  # presupuesto): $SHIFTY_STATE_DIR/alerts y despues $SHIFTY_RUN_DIR/alerts
  # (tmpfs). Si falla cualquier intento en la ruta primaria, un respaldo que
  # pueda guardar estado registra el aviso, pero su presupuesto no autoriza
  # SMTP (pudo haber uso previo que el respaldo no conoce): el mail sale solo
  # en la ventana UTC del modo sin estado. Si también falla el respaldo, se
  # aplica el modo sin estado, limitado a la misma ventana.
  local propio="$SHIFTY_STATE_DIR/alerts" dir estado=1 i
  dir="$propio"
  if ! _alert_intentar "$dir" "$prefijo"; then
    _ALERT_BLOQUEAR_EMAIL=1
    shifty_run_dir
    dir="$SHIFTY_RUN_DIR/alerts"
    if ! { crear_run_dir && _alert_intentar "$dir" "$prefijo"; }; then
      estado=0
    fi
  fi
  if [ "$dir" != "$propio" ] && [ -z "${_ALERT_AVISO_ESTADO:-}" ]; then
    _ALERT_AVISO_ESTADO=1
    if [ "$estado" = 1 ]; then
      log "alertas: no puedo escribir el estado de alertas en $propio; vive en $dir (tmpfs): se pierde al reiniciar el host"
    else
      log "alertas: no puedo escribir el estado de alertas en $propio ni en $dir; modo sin estado: sin silencio ni presupuesto, mail y webhook solo en la ventana de ALERT_STATELESS_EVERY_HOURS"
    fi
  fi
  if [ "$estado" = 0 ]; then
    _ALERT_IDX=()
    for ((i = 0; i < n; i++)); do _ALERT_IDX+=("$i"); done
    _alert_componer "$prefijo"
  fi
  # Estado principal roto con respaldo sano: el SMTP sale solo en la ventana
  # (ver alert()), aunque el respaldo haya silenciado todo.
  local degradado=0 ventana=0
  if [ "$estado" = 1 ] && [ "$_ALERT_BLOQUEAR_EMAIL" = 1 ] && [ -n "${ALERT_EMAIL:-}" ]; then
    _alert_ventana || ventana=$?
    if [ "$ventana" = 0 ]; then
      degradado=1
    elif [ "$ventana" = 2 ]; then
      log "alertas: estado principal no disponible y no pude leer la hora UTC; SMTP suprimido"
    fi
  fi
  [ "${#_ALERT_IDX[@]}" -gt 0 ] || [ "$degradado" = 1 ] || return 0
  local idx=() subject="" body=""
  if [ "${#_ALERT_IDX[@]}" -gt 0 ]; then
    idx=("${_ALERT_IDX[@]}")
    subject="$_ALERT_ASUNTO"
    body="$_ALERT_CUERPO"
  fi

  local prioridad
  for i in "${idx[@]}"; do
    log "ALERTA: ${asuntos[$i]}${detalles[$i]:+ | ${detalles[$i]}}"
    prioridad=user.warning
    if [ "$estado" = 0 ]; then
      _alert_gravedad "${claves[$i]}"
      if [ "$_ALERT_GRAVEDAD" = 0 ]; then prioridad=user.crit; fi
    fi
    if command -v logger >/dev/null 2>&1; then
      logger -t shifty -p "$prioridad" -- "${asuntos[$i]}${detalles[$i]:+ | ${detalles[$i]}}" || true
    fi
  done
  if [ "$estado" = 0 ]; then
    # Sin estado utilizable, se aplica el modo degradado acotado por ventana.
    # El bloqueo por lock/ledger incierto solo evita saltar a un respaldo sano.
    if [ -n "${ALERT_EMAIL:-}" ] && ! command -v timeout >/dev/null 2>&1; then mail=3; fi
    _alert_sin_estado "$subject" "$body" "${#idx[@]}" "$mail"
    return 0
  fi
  if [ "$degradado" = 1 ]; then
    # El webhook, con el silencio del respaldo; el mail, con todo lo encolado
    # y sin el presupuesto del respaldo.
    if [ "${#idx[@]}" -gt 0 ]; then _alert_mandar "$subject" "$body" 2 "" webhook; fi
    _ALERT_IDX=()
    for ((i = 0; i < n; i++)); do _ALERT_IDX+=("$i"); done
    _alert_componer "$prefijo"
    local nota="Envio degradado: no se pudo usar el estado de alertas principal ($propio) y el respaldo ($dir) no conoce los mails que ya salieron, asi que no protege el presupuesto diario. El mail sale solo en la ventana de ALERT_STATELESS_EVERY_HOURS (cada $_ALERT_CADA h UTC), con todos los avisos de la corrida aunque esten silenciados; lo de entre ventanas queda en syslog. Esta corrida tuvo $n alertas."
    _alert_mandar "$_ALERT_ASUNTO (estado principal no disponible)" "$nota"$'\n\n'"$_ALERT_CUERPO" 1 "" mail
    return 0
  fi
  if [ "$_ALERT_BLOQUEAR_EMAIL" = 1 ]; then mail=2; else mail="$_ALERT_MAIL_OK"; fi
  _alert_mandar "$subject" "$body" "$mail" "$_ALERT_NOTA"
  return 0
}

# _alert_escribible <dir>: <dir> existe o se crea y admite un archivo nuevo.
# Se prueba creandolo y borrandolo: con los inodos agotados o el disco lleno
# `[ -w ]` da bien y no se puede crear nada.
_alert_escribible() {
  local prueba="$1/.prueba-de-escritura.${BASHPID:-$$}"
  mkdir -p "$1" 2>/dev/null || return 1
  rm -f "$prueba" 2>/dev/null || true
  touch "$prueba" 2>/dev/null || return 1
  rm -f "$prueba" 2>/dev/null || true
}

# _alert_intentar <dir> <prefijo>: el envio con estado en <dir>. Sale 1 si en
# <dir> no se puede crear un archivo o si no se pudo escribir un sello o el
# registro del presupuesto (lo anota): el llamador prueba el respaldo y, si no
# tiene estado utilizable, aplica el modo sin estado con ventana UTC.
_alert_intentar() {
  _ALERT_FALLA=""
  if ! _alert_escribible "$1"; then
    _ALERT_FALLA="no pude completar la prueba de escritura en $1"
    log "alertas: no pude escribir el estado de alertas en $1 ($_ALERT_FALLA)"
    return 1
  fi
  _alert_con_estado "$1" "$2" && return 0
  log "alertas: no pude escribir el estado de alertas en $1 ($_ALERT_FALLA); no mando sin silencio ni presupuesto"
  return 1
}

# _alert_con_estado <dir> <prefijo>: silencio por clave y presupuesto en
# <dir>, bajo su lock (dos procesos a la vez, corridas apiladas o guard y
# checks, no mandan dos veces lo mismo). Deja en _ALERT_IDX los avisos que
# salen, en _ALERT_ASUNTO y _ALERT_CUERPO el mensaje, y en _ALERT_MAIL_OK y
# _ALERT_NOTA lo del presupuesto. Sale 1, con el motivo en _ALERT_FALLA, si
# no pudo escribir un sello o el registro. Lee la cola de alert_flush.
_alert_con_estado() {
  local dir="$1" prefijo="$2" fd="" i clave stamp seguimiento=()
  _ALERT_IDX=()
  _ALERT_FALLA=""
  _ALERT_MAIL_OK=1
  _ALERT_NOTA=""
  if ! command -v flock >/dev/null 2>&1; then
    _ALERT_FALLA="el host no tiene flock para proteger el presupuesto en $dir"
    return 1
  fi
  if ! { exec {fd}>>"$dir/.lock"; } 2>/dev/null; then
    _ALERT_FALLA="no pude abrir $dir/.lock"
    return 1
  fi
  local lock_rc=0
  flock -w 15 "$fd" || lock_rc=$?
  if [ "$lock_rc" -ne 0 ]; then
    exec {fd}>&-
    _ALERT_FALLA="no pude tomar $dir/.lock (flock salio $lock_rc)"
    return 1
  fi

  for ((i = 0; i < n; i++)); do
    clave="${claves[$i]}"
    if [ -n "$clave" ]; then
      stamp="$dir/${clave//[^A-Za-z0-9_.-]/_}"
      if [ -f "$stamp" ] && [ -n "$(find "$stamp" -mmin "-${silencios[$i]}" 2>/dev/null)" ]; then
        log "alerta silenciada ($clave): ${asuntos[$i]}"
        continue
      fi
      if ! touch "$stamp" 2>/dev/null; then
        _ALERT_FALLA="no pude escribir el sello $stamp"
        if [ -n "$fd" ]; then exec {fd}>&-; fi
        return 1
      fi
    fi
    _ALERT_IDX+=("$i")
    # Sin clave, el asunto identifica la alerta para la reserva del dia.
    clave="${clave:-asunto:${asuntos[$i]}}"
    seguimiento+=("${clave//[$'\r\n']/ }")
  done

  local rc=0
  if [ "${#_ALERT_IDX[@]}" -gt 0 ]; then
    _alert_componer "$prefijo"
    if [ -n "${ALERT_EMAIL:-}" ]; then
      _alert_presupuesto "$dir" "$_ALERT_ASUNTO" "${seguimiento[@]}" || rc=1
    fi
  fi
  if [ -n "$fd" ]; then exec {fd}>&-; fi
  return "$rc"
}

# _alert_componer <prefijo>: ordena _ALERT_IDX del mas grave al menos grave
# (a igual gravedad, en el orden en que se encolaron) y deja el mensaje en
# _ALERT_ASUNTO y _ALERT_CUERPO. Lee la cola de alert_flush.
_alert_componer() {
  local prefijo="$1" g i ordenados=()
  for g in 0 1 2 3; do
    for i in "${_ALERT_IDX[@]}"; do
      _alert_gravedad "${claves[$i]}"
      if [ "$_ALERT_GRAVEDAD" = "$g" ]; then ordenados+=("$i"); fi
    done
  done
  _ALERT_IDX=("${ordenados[@]}")

  local subject body="" linea detalle resto
  if [ "${#_ALERT_IDX[@]}" -eq 1 ]; then
    subject="${asuntos[${_ALERT_IDX[0]}]}"
    body="${detalles[${_ALERT_IDX[0]}]}"
  else
    subject="${asuntos[${_ALERT_IDX[0]}]}"
    if [ -n "$prefijo" ] && [[ "$subject" != "$prefijo:"* ]]; then
      subject="$prefijo: $subject"
    fi
    resto=$((${#_ALERT_IDX[@]} - 1))
    if [ "$resto" -eq 1 ]; then
      subject+=" (+1 aviso)"
    else
      subject+=" (+$resto avisos)"
    fi
    for i in "${_ALERT_IDX[@]}"; do
      linea="- ${asuntos[$i]}"
      detalle="${detalles[$i]//[$'\r\n']/ }"
      if [ -n "$detalle" ]; then linea+=": $detalle"; fi
      if [ -n "$body" ]; then body+=$'\n'; fi
      body+="$linea"
    done
  fi
  _ALERT_ASUNTO="$subject"
  _ALERT_CUERPO="$body"
}

# _alert_ventana: sale 0 si la hora UTC cae en la ventana del envio degradado
# (ver alert(): horas multiplo de ALERT_STATELESS_EVERY_HOURS, en el minuto 00
# si _ALERT_CADA_MINUTO=1), 1 si no y 2 si no pudo leer la hora. Deja en
# _ALERT_CADA las horas entre ventanas. La usan el modo sin estado y el SMTP
# con el estado principal roto.
_alert_ventana() {
  local cada="${ALERT_STATELESS_EVERY_HOURS:-3}" hm h m
  if ! [[ "$cada" =~ ^[1-9][0-9]*$ ]] || [ "$cada" -gt 24 ]; then
    log "alertas: ALERT_STATELESS_EVERY_HOURS=$cada no es un numero de horas entre 1 y 24; uso 3"
    cada=3
  fi
  _ALERT_CADA="$cada"
  hm="$(date -u +%H:%M 2>/dev/null)" || hm=""
  [[ "$hm" =~ ^([0-9][0-9]):([0-9][0-9])$ ]] || return 2
  h=$((10#${BASH_REMATCH[1]}))
  m=$((10#${BASH_REMATCH[2]}))
  if [ $((h % cada)) -ne 0 ] || { [ "$_ALERT_CADA_MINUTO" = 1 ] && [ "$m" -ne 0 ]; }; then
    return 1
  fi
  return 0
}

# _alert_sin_estado <asunto> <detalle> <alertas> [mail]: envio degradado sin estado.
# Los avisos ya quedaron en stderr y en syslog; mail y webhook salen solo en
# la ventana del reloj (ver alert()), sin presupuesto.
_alert_sin_estado() {
  local subject="$1" body="$2" n="$3" mail="${4:-1}" ventana=0
  _alert_ventana || ventana=$?
  if [ "$ventana" = 1 ]; then
    log "alertas: modo sin estado, fuera de la ventana (cada $_ALERT_CADA h UTC): $n alertas solo en stderr y syslog, sin mail ni webhook"
    return 0
  elif [ "$ventana" = 2 ]; then
    # Sin reloj legible no hay ventana: avisar importa mas.
    log "alertas: modo sin estado y no pude leer la hora UTC; mando igual"
  fi
  local nota="Envio degradado sin estado: no hay estado de alertas escribible ($SHIFTY_STATE_DIR/alerts ni $SHIFTY_RUN_DIR/alerts). Sin silencio por clave ni presupuesto diario; sale a lo sumo un mensaje cada $_ALERT_CADA h UTC y lo de entre ventanas queda solo en syslog. Esta corrida tuvo $n alertas."
  _alert_mandar "$subject (sin estado)" "$nota"$'\n\n'"$body" "$mail" ""
}

# Estado del presupuesto, en $SHIFTY_STATE_DIR/alerts: `.mails-del-dia` (la
# fecha UTC, los mails de ese dia y una clave por linea) y `.mails-suprimidos`
# (una linea "<hora UTC> <asunto>" por mail suprimido desde el ultimo que
# salio). Se llama con el lock de alertas tomado. Deja en _ALERT_MAIL_OK si
# el mail sale (1) o no (0), y en _ALERT_NOTA la cuenta de suprimidos que
# viaja en el mail que sale. La cuenta se vacia al darle ese mail a msmtp,
# aunque msmtp falle: como el sello, no se reintenta. Sale 1, con el motivo
# en _ALERT_FALLA, si no pudo anotar el mail o la suprimida: sin registro
# el presupuesto no cuenta nada (revision del 2026-11-15).
_alert_presupuesto() {
  local dir="$1" subject="$2"
  shift 2
  _ALERT_MAIL_OK=1
  _ALERT_NOTA=""
  if [ -n "${ALERT_EMAIL:-}" ] && ! command -v timeout >/dev/null 2>&1; then
    _ALERT_MAIL_OK=3
    return 0
  fi
  local max="${ALERT_EMAIL_MAX_PER_DAY:-12}" reserva="${ALERT_EMAIL_RESERVED_PER_DAY:-3}"
  [[ "$max" =~ ^(0|[1-9][0-9]*)$ ]] || max=12
  [[ "$reserva" =~ ^(0|[1-9][0-9]*)$ ]] || reserva=3
  if [ "$reserva" -gt "$max" ]; then reserva="$max"; fi
  local registro="$dir/.mails-del-dia" suprimidos="$dir/.mails-suprimidos" hoy
  hoy="$(date -u +%Y-%m-%d)"

  local lineas=() usados=0 claves_hoy=()
  if [ -e "$registro" ] || [ -L "$registro" ]; then
    if [ ! -f "$registro" ] || ! mapfile -t lineas <"$registro" 2>/dev/null; then
      _ALERT_FALLA="no pude leer el registro de presupuesto $registro"
      return 1
    fi
    local fecha_registro="${lineas[0]:-}" fecha_calendario=""
    if ! [[ "$fecha_registro" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] ||
      ! fecha_calendario="$(date -u -d "$fecha_registro" +%F 2>/dev/null)" ||
      [ "$fecha_calendario" != "$fecha_registro" ] || [[ "$fecha_registro" > "$hoy" ]]; then
      _ALERT_FALLA="registro de presupuesto invalido en $registro"
      return 1
    fi
    if [ "${lineas[0]}" = "$hoy" ]; then
      if [ "${#lineas[@]}" -lt 2 ] || ! [[ "${lineas[1]}" =~ ^(0|[1-9][0-9]*)$ ]]; then
        _ALERT_FALLA="registro de presupuesto invalido para hoy en $registro"
        return 1
      fi
      usados="${lineas[1]}"
      claves_hoy=("${lineas[@]:2}")
    fi
  fi

  # La reserva la usa solo un mensaje con una clave critica que no salio hoy.
  local nueva_critica=0 k
  for k in "$@"; do
    _alert_gravedad "$k"
    if [ "$_ALERT_GRAVEDAD" = 0 ] && ! _alert_en_lista "$k" "${claves_hoy[@]}"; then
      nueva_critica=1
      break
    fi
  done

  _ALERT_MAIL_OK=1
  _ALERT_NOTA=""
  if [ "$usados" -ge "$max" ] || { [ "$usados" -ge $((max - reserva)) ] && [ "$nueva_critica" = 0 ]; }; then
    if printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$subject" >>"$suprimidos" 2>/dev/null; then
      _ALERT_MAIL_OK=0
    else
      _ALERT_FALLA="no pude anotar la alerta suprimida en el registro de presupuesto $suprimidos"
      return 1
    fi
    return 0
  fi

  for k in "$@"; do
    _alert_en_lista "$k" "${claves_hoy[@]}" || claves_hoy+=("$k")
  done
  if ! { printf '%s\n' "$hoy" "$((usados + 1))" "${claves_hoy[@]}" >"$registro.tmp" &&
    mv -f "$registro.tmp" "$registro"; } 2>/dev/null; then
    rm -f "$registro.tmp" 2>/dev/null || true
    if [ "$usados" -gt 0 ]; then
      _ALERT_FALLA="registro de presupuesto con uso previo ($usados): no pude anotar el mail en $registro"
    else
      _ALERT_FALLA="no pude anotar el primer mail en un registro de presupuesto vacio ($registro)"
    fi
    return 1
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

# _alert_gravedad <clave>: deja en _ALERT_GRAVEDAD de 0 (la mayor) a 3. Las
# de gravedad 0 son las CRITICAS, las unicas que usan la reserva del
# presupuesto diario: algo caido que necesita una persona (dependencia,
# db/rabbitmq, docker, host saturado, un guard sin exclusividad que no
# reinicia nada) o el backup. Despues un restart que fallo o que no se hizo
# por no poder anotar el contador, un tope alcanzado y el resto (un "reinicie
# X" no tiene clave).
_alert_gravedad() {
  case "$1" in
    guard-dependencia-* | guard-no-reinicia-* | guard-docker-no-responde | guard-host-saturado | guard-sin-exclusividad | guard-sin-timeout | guard-carga-desconocida | backup-*)
      _ALERT_GRAVEDAD=0
      ;;
    guard-fallo-* | guard-sin-contador-*) _ALERT_GRAVEDAD=1 ;;
    guard-tope-*) _ALERT_GRAVEDAD=2 ;;
    *) _ALERT_GRAVEDAD=3 ;;
  esac
}

_alert_en_lista() {
  local buscada="$1" elemento
  shift
  for elemento in "$@"; do
    if [ "$elemento" = "$buscada" ]; then return 0; fi
  done
  return 1
}

# _alert_mandar <asunto> <detalle> <mail 1|0|2|3> <nota> [ambos|webhook|mail]:
# un intento por canal, sin reintentos. Nunca afirma que el mail llego: solo
# que msmtp lo acepto. Con un solo canal no anota que ninguna alerta salio.
_alert_mandar() {
  local subject="$1" body="$2" mail="$3" nota="$4" canales="${5:-ambos}"
  local host webhook="${ALERT_WEBHOOK_URL:-}" email="${ALERT_EMAIL:-}"
  host="$(hostname 2>/dev/null || echo host)"
  if [ "$canales" = mail ]; then webhook=""; fi
  if [ "$canales" = webhook ]; then email=""; fi

  local sent=0 suprimida=0
  if [ -n "$webhook" ]; then
    local text
    text="$(json_escape "[shifty@$host] $subject${body:+
$body}")"
    # `text` lo lee Slack; `content`, Discord.
    if curl -fsS -m 10 -H 'Content-Type: application/json' \
      --data "{\"text\":\"$text\",\"content\":\"$text\"}" \
      "$webhook" >/dev/null 2>&1; then
      sent=1
    else
      log "no se pudo mandar la alerta al webhook"
    fi
  fi
  if [ -n "$email" ] && [ "$mail" = 2 ]; then
    suprimida=1
    log "alerta SMTP suprimida: no se pudo proteger el presupuesto diario del host"
  elif [ -n "$email" ] && [ "$mail" = 3 ]; then
    suprimida=1
    log "alerta SMTP suprimida: no hay timeout para limitar el envio"
  elif [ -n "$email" ] && [ "$mail" != 1 ]; then
    suprimida=1
    log "alerta suprimida por presupuesto diario del host: $subject"
    if command -v logger >/dev/null 2>&1; then
      logger -t shifty -p user.warning -- "alerta suprimida por presupuesto diario del host: $subject" || true
    fi
  elif [ -n "$email" ]; then
    local mailer="" cuerpo="$body"
    if [ -n "$nota" ]; then cuerpo="$nota"$'\n\n'"$body"; fi
    if command -v msmtp >/dev/null 2>&1; then
      mailer="msmtp"
    elif command -v sendmail >/dev/null 2>&1; then
      mailer="sendmail"
    fi
    if [ -n "$mailer" ]; then
      if ! command -v timeout >/dev/null 2>&1; then
        suprimida=1
        log "alerta SMTP suprimida: no hay timeout para limitar $mailer"
      else
        # Con DNS caido msmtp puede colgarse (13/11): 30 s de tope.
        if printf 'To: %s\nSubject: [shifty@%s] %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n' \
          "$ALERT_EMAIL" "$host" "$subject" "$cuerpo" | timeout -k 5 30 "$mailer" -t; then
          sent=1
        else
          log "no se pudo mandar la alerta por mail ($mailer)"
        fi
      fi
    else
      log "ALERT_EMAIL definido pero el host no tiene msmtp ni sendmail"
    fi
  fi
  if [ "$canales" = ambos ] && [ "$sent" != 1 ] && [ "$suprimida" != 1 ]; then
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
