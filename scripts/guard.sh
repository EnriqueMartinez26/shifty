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
# - Una sola corrida a la vez: `flock -n` sobre $SHIFTY_STATE_DIR/guard.lock.
#   Cron la lanza cada minuto y cada corrida quedaba colgada en `docker ps`:
#   se apilaban (procesos 435 -> 764, load 68 en 2 vCPU). Si el lock no se
#   puede abrir (estado de solo lectura) corre sin el: avisar importa mas.
# - Toda llamada a docker tiene tope: GUARD_DOCKER_TIMEOUT_SECONDS (30) para
#   ps/inspect y GUARD_RESTART_TIMEOUT_SECONDS (120) para restart, que espera
#   el stop_grace_period del contenedor (60 s el de celery_worker). Si docker
#   no contesta o `docker ps` falla, esa corrida no reinicia nada y avisa una
#   vez. Tras un `docker restart` que falla no reinicia nada mas en la
#   corrida (el 13/11 dockerd devolvia errores, no se colgaba). Sin el
#   binario `timeout` corre sin tope y lo anota una vez por corrida.
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

# El lock dura lo que dura el proceso (fd 9): un guard matado lo suelta. Si
# no se puede abrir, corre sin el (falla abierto): sin lock se pueden apilar
# corridas, sin aviso nadie se entera.
if command -v flock >/dev/null 2>&1; then
  if { exec 9>"$SHIFTY_STATE_DIR/guard.lock"; } 2>/dev/null; then
    if ! flock -n 9; then
      log "guard: otra corrida sigue en curso ($SHIFTY_STATE_DIR/guard.lock); salgo sin hacer nada"
      exit 0
    fi
  else
    log "guard: no pude abrir el lock ($SHIFTY_STATE_DIR/guard.lock); corro sin el"
  fi
else
  log "guard: el host no tiene flock; corro sin el lock de una sola corrida"
fi
if ! command -v timeout >/dev/null 2>&1; then
  log "guard: el host no tiene timeout; docker y el mail de alerta corren sin tope"
fi

enfermos=()

# docker <args> con tope de <segundos>. Sale 124 (137 si hubo que matarlo) si
# docker no contesta. El hijo no hereda el fd del lock: un docker colgado que
# sobreviva al guard no bloquea a las corridas siguientes.
docker_con_tope() {
  local tope="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout -k 5 "$tope" docker "$@" 9>&-
  else
    docker "$@" 9>&-
  fi
}

es_tope_vencido() {
  [ "$1" -eq 124 ] || [ "$1" -eq 137 ]
}

# docker_no_responde <que paso>: docker no contesto o fallo. Esta corrida no
# reinicia nada mas. Un aviso con clave fija, no uno por contenedor ni por
# corrida.
docker_no_responde() {
  alert_add "guard: docker no responde ($1); no reinicio nada" \
    "Mirar: systemctl status docker; journalctl -u docker --since -30min. Unhealthy: ${enfermos[*]:-sin listar}" \
    guard-docker-no-responde 60
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
# saturado, 0 no. `restart_fallido`: el contenedor cuyo restart fallo.
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

  archivo="$estado/$nombre"
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
  if [ -n "$restart_fallido" ]; then
    log "guard: no reinicio $nombre: el docker restart de $restart_fallido fallo en esta corrida"
    continue
  fi

  printf '%s\n' "${propios[@]}" "$ahora" >"$archivo"
  printf '%s\n' "${todos[@]}" "$ahora" >"$global"
  rc=0
  docker_con_tope "$GUARD_RESTART_TIMEOUT_SECONDS" restart "$nombre" >/dev/null || rc=$?
  if [ "$rc" -eq 0 ]; then
    alert_add "guard: reinicie $nombre (unhealthy)" \
      "Reinicio $((${#propios[@]} + 1)) de $GUARD_MAX_RESTARTS en la ultima hora."
  elif es_tope_vencido "$rc"; then
    docker_no_responde "docker restart $nombre no termino en $GUARD_RESTART_TIMEOUT_SECONDS s"
  else
    restart_fallido="$nombre"
    alert_add "guard: fallo docker restart $nombre" \
      "Salio con codigo $rc; el contenedor sigue unhealthy. En esta corrida no reinicio nada mas." \
      "guard-fallo-$nombre" 30
  fi
done
alert_flush guard
