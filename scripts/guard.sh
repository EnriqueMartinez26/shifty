#!/usr/bin/env bash
# Guard del host (F0-21): reinicia los contenedores `unhealthy` del proyecto.
#
# `restart: always` solo actua cuando el proceso MUERE; un contenedor vivo
# pero `unhealthy` (API colgada, worker que dejo de consumir) queda asi para
# siempre. Esto lo corre cron cada minuto (deploy/cron/shifty-guard), como
# root, con el CLI de docker: sin autoheal ni docker.sock montado en un
# contenedor (plan §7, decision 25).
#
# Lo que NO hace:
# - No toca contenedores efimeros (`compose run`, la migracion del deploy):
#   filtra com.docker.compose.oneoff=False.
# - No reinicia GUARD_NO_RESTART (db, rabbitmq): reiniciarlos en caliente
#   corta todas las conexiones; avisa y lo decide una persona.
# - Si una de GUARD_DEPENDENCIES (db, redis_state) esta unhealthy no reinicia
#   NADA: el resto cae por arrastre y reiniciarlo en bucle no arregla nada.
# - Tope por contenedor: GUARD_MAX_RESTARTS (3) en GUARD_WINDOW_SECONDS (1 h).
#   Tope global: GUARD_MAX_TOTAL_RESTARTS (6) en la misma ventana. Pasado un
#   tope avisa y no reinicia mas.
# - Durante un deploy (lock en .deploy/lock) no hace nada.
#
# Incidente 2026-11-13 (dockerd colgado de 15:10 a 17:07 UTC):
# - Una sola corrida a la vez: `flock -n` sobre $SHIFTY_STATE_DIR/guard.lock y
#   $SHIFTY_RUN_DIR/guard.lock. Cron la lanza cada minuto y cada corrida
#   quedaba colgada en `docker ps`: se apilaban (procesos 435 -> 764, load 68
#   en 2 vCPU).
# - Reinicia SOLO con exclusividad (revision del 2026-11-15). Sin flock, sin
#   ningun lock que se pueda abrir o con un error de flock que no es otra
#   corrida, corre en modo observacion: todos los chequeos y avisos, ningun
#   reinicio, y un aviso critico (guard-sin-exclusividad) que lo dice.
# - Sin poder leer o anotar un contador no reinicia ese contenedor ni los que
#   siguen en la corrida, y sigue avisando: un contador que no se lee dejaba
#   pasar el tope (revision del 2026-11-15).
# - Toda llamada a docker tiene tope: GUARD_DOCKER_TIMEOUT_SECONDS (30) para
#   ps/inspect y GUARD_RESTART_TIMEOUT_SECONDS (120) para restart, que espera
#   el stop_grace_period del contenedor (60 s el de celery_worker). Si docker
#   no contesta o `docker ps` falla, esa corrida no reinicia nada y avisa una
#   vez. Tras un `docker restart` que falla o se cuelga no reinicia nada mas
#   en la corrida (el 13/11 dockerd devolvia errores, no se colgaba), pero
#   sigue con los demas contenedores para encolar sus avisos (rabbitmq, topes,
#   "no reinicio X"). Sin el binario `timeout` corre sin tope y lo anota una
#   vez por corrida.
# - Con el host saturado (load de 1 minuto por CPU sobre
#   GUARD_MAX_LOAD_PER_CPU, 4) no reinicia: reiniciar bajo saturacion
#   empeoro el 13/11. Sin carga legible reinicia como antes; un tope que no
#   es un numero positivo usa 4.
# - Una corrida manda a lo sumo UN aviso con todos sus problemas (alert_add +
#   alert_flush de lib/common.sh), el mas grave primero; cada problema
#   conserva su silencio y queda en el log. Lo encolado sale aunque la
#   corrida muera a mitad (trap EXIT). El presupuesto diario de mails del
#   host vive en alert().
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# Un error bajo `set -e` entre alert_add y alert_flush perdia lo encolado.
# alert_flush vacia la cola: los flush explicitos de abajo no mandan dos veces.
trap 'alert_flush guard' EXIT
# Corre cada minuto: en el modo sin estado de alert() manda solo en el minuto
# 00 de la ventana.
_ALERT_CADA_MINUTO=1

: "${GUARD_MAX_RESTARTS:=3}"
: "${GUARD_MAX_TOTAL_RESTARTS:=6}"
: "${GUARD_WINDOW_SECONDS:=3600}"
: "${GUARD_NO_RESTART:=db rabbitmq}"
: "${GUARD_DEPENDENCIES:=db redis_state}"
# Proyectos de compose que vigila; por defecto, el de este clon.
: "${GUARD_PROJECTS:=$COMPOSE_PROJECT_NAME}"
: "${GUARD_DOCKER_TIMEOUT_SECONDS:=30}"
: "${GUARD_RESTART_TIMEOUT_SECONDS:=120}"
: "${GUARD_MAX_LOAD_PER_CPU:=4}"
: "${GUARD_LOADAVG_FILE:=/proc/loadavg}"

# awk compara contra un texto como texto: con "abc" reiniciaba siempre.
if ! [[ "$GUARD_MAX_LOAD_PER_CPU" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
  ! [[ "$GUARD_MAX_LOAD_PER_CPU" =~ [1-9] ]]; then
  log "guard: GUARD_MAX_LOAD_PER_CPU=$GUARD_MAX_LOAD_PER_CPU no es un numero positivo; uso 4"
  GUARD_MAX_LOAD_PER_CPU=4
fi

if deploy_in_progress; then
  log "guard: hay un deploy en curso, no se reinicia nada"
  exit 0
fi

estado="$SHIFTY_STATE_DIR/guard"
# Sin estado escribible (/ remontado de solo lectura) sigue: los avisos salen
# igual; un reinicio, que necesita anotar su contador, no.
mkdir -p "$estado" 2>/dev/null || log "guard: no pude crear $estado; sigo para avisar"
ahora="$(date +%s)"
global="$estado/_global"

# abrir_lock <8|9> <archivo>: abre el fd del lock. Con el estado de solo
# lectura un lock que ya existe se abre para leer: flock no necesita escribir.
abrir_lock() {
  case "$1" in
    8) { exec 8>>"$2"; } 2>/dev/null || { exec 8<"$2"; } 2>/dev/null ;;
    9) { exec 9>>"$2"; } 2>/dev/null || { exec 9<"$2"; } 2>/dev/null ;;
  esac
}

# Exclusividad. Dos locks: $SHIFTY_STATE_DIR/guard.lock (fd 9) y
# $SHIFTY_RUN_DIR/guard.lock (fd 8, tmpfs: sigue escribible con / remontado
# de solo lectura). Toma todos los que puede abrir y, si otra corrida tiene
# cualquiera de los dos, sale: dos corridas que reinician comparten al menos
# un lock, salvo que a cada una le falle abrir uno distinto. Los locks duran
# lo que dura el proceso: un guard matado los suelta. `flock -E` da su propio
# codigo al conflicto: un error de flock no pasa por otra corrida.
# `sin_exclusividad`: vacio con exclusividad; si no, por que no la hay.
shifty_run_dir
conflicto_flock=99
sin_exclusividad=""
if command -v flock >/dev/null 2>&1; then
  tomados=0
  fallas=""
  for fd in 9 8; do
    if [ "$fd" = 9 ]; then
      lock="$SHIFTY_STATE_DIR/guard.lock"
    else
      lock="$SHIFTY_RUN_DIR/guard.lock"
      # El mismo archivo dos veces: el segundo flock chocaria con el primero.
      if [ "$lock" -ef "$SHIFTY_STATE_DIR/guard.lock" ]; then continue; fi
      crear_run_dir || true
    fi
    if ! abrir_lock "$fd" "$lock"; then
      log "guard: no pude abrir el lock ($lock)"
      fallas+="${fallas:+; }no pude abrir $lock"
      continue
    fi
    rc=0
    flock -n -E "$conflicto_flock" "$fd" || rc=$?
    if [ "$rc" -eq 0 ]; then
      tomados=$((tomados + 1))
    elif [ "$rc" -eq "$conflicto_flock" ]; then
      log "guard: otra corrida sigue en curso ($lock); salgo sin hacer nada"
      exit 0
    else
      log "guard: flock salio con codigo $rc sobre $lock"
      fallas+="${fallas:+; }flock salio $rc sobre $lock"
    fi
  done
  if [ "$tomados" -eq 0 ]; then sin_exclusividad="$fallas"; fi
else
  sin_exclusividad="el host no tiene flock"
fi
if [ -n "$sin_exclusividad" ]; then
  log "guard: sin exclusividad ($sin_exclusividad); modo observacion: chequeo y aviso, no reinicio nada"
  alert_add "guard: sin exclusividad ($sin_exclusividad); no reinicio ningun contenedor" \
    "Sin el lock de una sola corrida dos guards podrian reiniciar a la vez. Los chequeos y avisos siguen; los reinicios vuelven cuando el lock ande (flock y $SHIFTY_STATE_DIR o $SHIFTY_RUN_DIR escribibles)." \
    guard-sin-exclusividad 180
fi
if ! command -v timeout >/dev/null 2>&1; then
  log "guard: el host no tiene timeout; docker y el mail de alerta corren sin tope"
fi

enfermos=()

# docker <args> con tope de <segundos>. Sale 124 (137 si hubo que matarlo) si
# docker no contesta. El hijo no hereda los fds de los locks: un docker
# colgado que sobreviva al guard no bloquea a las corridas siguientes.
docker_con_tope() {
  local tope="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout -k 5 "$tope" docker "$@" 9>&- 8>&-
  else
    docker "$@" 9>&- 8>&-
  fi
}

es_tope_vencido() {
  [ "$1" -eq 124 ] || [ "$1" -eq 137 ]
}

# aviso_docker_no_responde <que paso>: encola el aviso de que docker no
# contesto o fallo. Una clave fija, no una por contenedor ni por corrida.
aviso_docker_no_responde() {
  alert_add "guard: docker no responde ($1); no reinicio nada" \
    "Mirar: systemctl status docker; journalctl -u docker --since -30min. Unhealthy: ${enfermos[*]:-sin listar}" \
    guard-docker-no-responde 60
}

# docker_no_responde <que paso>: `docker ps` o `inspect` no contestaron o
# fallaron. Sin la lista de contenedores la corrida termina aca.
docker_no_responde() {
  aviso_docker_no_responde "$1"
  alert_flush guard
  exit 0
}

# Load de 1 minuto por CPU sobre GUARD_MAX_LOAD_PER_CPU. Deja las cifras en
# `carga_texto`. Sin load o CPUs legibles no frena (sale 1) y lo anota.
carga_texto=""
host_saturado() {
  local carga="" cpus=""
  carga="$(awk '{ print $1; exit }' "$GUARD_LOADAVG_FILE" 2>/dev/null)" || carga=""
  cpus="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null)" || cpus=""
  if ! [[ "$carga" =~ ^[0-9]+([.][0-9]+)?$ ]] || ! [[ "$cpus" =~ ^[1-9][0-9]*$ ]]; then
    log "guard: no pude leer la carga del host ($GUARD_LOADAVG_FILE, nproc); reinicio igual"
    return 1
  fi
  carga_texto="load de 1 minuto $carga con $cpus CPU, tope $GUARD_MAX_LOAD_PER_CPU por CPU"
  awk -v c="$carga" -v n="$cpus" -v t="$GUARD_MAX_LOAD_PER_CPU" 'BEGIN { exit !(c / n > t) }'
}

# Marcas de <archivo> dentro de la ventana, una por linea.
recientes() {
  local archivo="$1" marca
  [ -f "$archivo" ] || return 0
  while read -r marca; do
    case "$marca" in '' | *[!0-9]*) continue ;; esac
    if [ $((ahora - marca)) -lt "$GUARD_WINDOW_SECONDS" ]; then
      printf '%s\n' "$marca"
    fi
  done <"$archivo"
}

# contador_legible <archivo>: todavia no existe (cero reinicios) o es un
# archivo que se puede abrir. Uno que no se lee se tomaba por vacio y el tope
# dejaba de contar.
contador_legible() {
  if [ ! -e "$1" ] && [ ! -L "$1" ]; then return 0; fi
  [ -f "$1" ] && { : <"$1"; } 2>/dev/null
}

# anotar <archivo> <marcas...>: reescribe el contador por tmp + mv (-T: nunca
# adentro de un directorio). Si falla, el contador viejo queda entero.
anotar() {
  local archivo="$1"
  shift
  if { printf '%s\n' "$@" >"$archivo.tmp" && mv -fT "$archivo.tmp" "$archivo"; } 2>/dev/null; then
    return 0
  fi
  rm -f "$archivo.tmp" 2>/dev/null || true
  return 1
}

# sin_contador <nombre> <motivo>: no reinicia <nombre> y, en esta corrida,
# tampoco a los que siguen (`contador_roto`).
contador_roto=""
sin_contador() {
  contador_roto="$2"
  alert_add "guard: no reinicio $1: $2" \
    "El tope de reinicios necesita el contador: en esta corrida no reinicio nada mas. Mirar: ls -l $estado; df -h $estado" \
    "guard-sin-contador-$1" 60
}

en_lista() {
  case " $2 " in *" $1 "*) return 0 ;; esac
  return 1
}

# "<nombre> <servicio>" de cada contenedor unhealthy de los proyectos vigilados.
for proyecto in $GUARD_PROJECTS; do
  rc=0
  ids="$(docker_con_tope "$GUARD_DOCKER_TIMEOUT_SECONDS" ps -q --filter health=unhealthy \
    --filter "label=com.docker.compose.project=$proyecto" \
    --filter label=com.docker.compose.oneoff=False)" || rc=$?
  if es_tope_vencido "$rc"; then
    docker_no_responde "docker ps no termino en $GUARD_DOCKER_TIMEOUT_SECONDS s"
  elif [ "$rc" -ne 0 ]; then
    # Daemon caido: `docker ps` falla enseguida, sin vencer el tope.
    docker_no_responde "docker ps fallo con codigo $rc"
  fi
  for id in $ids; do
    rc=0
    linea="$(docker_con_tope "$GUARD_DOCKER_TIMEOUT_SECONDS" inspect \
      -f '{{.Name}} {{index .Config.Labels "com.docker.compose.service"}}' "$id")" || rc=$?
    if es_tope_vencido "$rc"; then
      docker_no_responde "docker inspect no termino en $GUARD_DOCKER_TIMEOUT_SECONDS s"
    fi
    [ "$rc" -eq 0 ] || exit "$rc"
    enfermos+=("${linea#/}")
  done
done
[ "${#enfermos[@]}" -gt 0 ] || exit 0

for entrada in "${enfermos[@]}"; do
  servicio="${entrada#* }"
  if en_lista "$servicio" "$GUARD_DEPENDENCIES"; then
    alert_add "guard: $servicio esta unhealthy (${entrada%% *}); no reinicio nada" \
      "Con una dependencia caida el resto falla por arrastre. Unhealthy: ${enfermos[*]}" \
      "guard-dependencia-$servicio" 30
    alert_flush guard
    exit 0
  fi
done

# La carga se mide una vez, antes del primer reinicio: "" sin medir, 1
# saturado, 0 no. `restart_fallido`: el contenedor cuyo restart fallo o se
# colgo.
saturado=""
restart_fallido=""
for entrada in "${enfermos[@]}"; do
  nombre="${entrada%% *}"
  servicio="${entrada#* }"

  if en_lista "$servicio" "$GUARD_NO_RESTART"; then
    alert_add "guard: $nombre ($servicio) esta unhealthy; no se reinicia solo" \
      "Mirar: docker logs --tail 200 $nombre" "guard-no-reinicia-$nombre" 60
    continue
  fi

  if [ -n "$contador_roto" ]; then
    sin_contador "$nombre" "$contador_roto"
    continue
  fi
  archivo="$estado/$nombre"
  if ! contador_legible "$archivo"; then
    sin_contador "$nombre" "no puedo leer el contador $archivo"
    continue
  fi
  if ! contador_legible "$global"; then
    sin_contador "$nombre" "no puedo leer el contador $global"
    continue
  fi
  mapfile -t propios < <(recientes "$archivo")
  mapfile -t todos < <(recientes "$global")

  if [ "${#propios[@]}" -ge "$GUARD_MAX_RESTARTS" ]; then
    alert_add "guard: $nombre sigue unhealthy y ya se reinicio ${#propios[@]} veces en la ultima hora" \
      "No se reinicia mas hasta que baje el contador. Mirar: docker logs --tail 200 $nombre" \
      "guard-tope-$nombre" 60
    continue
  fi
  if [ "${#todos[@]}" -ge "$GUARD_MAX_TOTAL_RESTARTS" ]; then
    alert_add "guard: tope global de $GUARD_MAX_TOTAL_RESTARTS reinicios por hora alcanzado; $nombre sigue unhealthy" \
      "Demasiados contenedores cayendo a la vez: hace falta una persona." \
      "guard-tope-global" 60
    continue
  fi

  if [ -z "$saturado" ]; then
    saturado=0
    if host_saturado; then
      saturado=1
      alert_add "guard: host saturado ($carga_texto); no reinicio nada" \
        "Reiniciar con el host saturado lo empeora (13/11). Unhealthy: ${enfermos[*]}" \
        guard-host-saturado 60
    fi
  fi
  [ "$saturado" = 0 ] || continue
  # Tras un restart que fallo o se colgo no llama mas a docker, pero sigue
  # con el resto: un rabbitmq que venia despues esperaba al tope global.
  if [ -n "$restart_fallido" ]; then
    alert_add "guard: no reinicio $nombre: ya fallo un restart en esta corrida" \
      "El docker restart de $restart_fallido fallo; $nombre sigue unhealthy. Mirar: docker logs --tail 200 $nombre" \
      "guard-sin-reinicio-$nombre" 60
    continue
  fi
  if [ -n "$sin_exclusividad" ]; then
    alert_add "guard: no reinicio $nombre: sin exclusividad ($sin_exclusividad)" \
      "Sigue unhealthy. Mirar: docker logs --tail 200 $nombre" "guard-sin-reinicio-$nombre" 60
    continue
  fi

  # El contador se anota ANTES del restart: sin anotarlo no se reinicia.
  if ! anotar "$archivo" "${propios[@]}" "$ahora"; then
    sin_contador "$nombre" "no puedo anotar el contador $archivo"
    continue
  fi
  if ! anotar "$global" "${todos[@]}" "$ahora"; then
    sin_contador "$nombre" "no puedo anotar el contador $global"
    continue
  fi
  rc=0
  docker_con_tope "$GUARD_RESTART_TIMEOUT_SECONDS" restart "$nombre" >/dev/null || rc=$?
  if [ "$rc" -eq 0 ]; then
    alert_add "guard: reinicie $nombre (unhealthy)" \
      "Reinicio $((${#propios[@]} + 1)) de $GUARD_MAX_RESTARTS en la ultima hora."
  elif es_tope_vencido "$rc"; then
    restart_fallido="$nombre"
    aviso_docker_no_responde "docker restart $nombre no termino en $GUARD_RESTART_TIMEOUT_SECONDS s"
  else
    restart_fallido="$nombre"
    alert_add "guard: fallo docker restart $nombre" \
      "Salio con codigo $rc; el contenedor sigue unhealthy. En esta corrida no reinicio nada mas." \
      "guard-fallo-$nombre" 30
  fi
done
alert_flush guard
