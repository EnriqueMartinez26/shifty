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
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${GUARD_MAX_RESTARTS:=3}"
: "${GUARD_MAX_TOTAL_RESTARTS:=6}"
: "${GUARD_WINDOW_SECONDS:=3600}"
: "${GUARD_NO_RESTART:=db rabbitmq}"
: "${GUARD_DEPENDENCIES:=db redis_state}"
# Proyectos de compose que vigila; por defecto, el de este clon.
: "${GUARD_PROJECTS:=$COMPOSE_PROJECT_NAME}"

if deploy_in_progress; then
  log "guard: hay un deploy en curso, no se reinicia nada"
  exit 0
fi

estado="$SHIFTY_STATE_DIR/guard"
mkdir -p "$estado"
ahora="$(date +%s)"
global="$estado/_global"

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
enfermos=()
for proyecto in $GUARD_PROJECTS; do
  ids="$(docker ps -q --filter health=unhealthy \
    --filter "label=com.docker.compose.project=$proyecto" \
    --filter label=com.docker.compose.oneoff=False)"
  for id in $ids; do
    linea="$(docker inspect -f '{{.Name}} {{index .Config.Labels "com.docker.compose.service"}}' "$id")"
    enfermos+=("${linea#/}")
  done
done
[ "${#enfermos[@]}" -gt 0 ] || exit 0

for entrada in "${enfermos[@]}"; do
  servicio="${entrada#* }"
  if en_lista "$servicio" "$GUARD_DEPENDENCIES"; then
    alert "guard: $servicio esta unhealthy (${entrada%% *}); no reinicio nada" \
      "Con una dependencia caida el resto falla por arrastre. Unhealthy: ${enfermos[*]}" \
      "guard-dependencia-$servicio" 30
    exit 0
  fi
done

for entrada in "${enfermos[@]}"; do
  nombre="${entrada%% *}"
  servicio="${entrada#* }"

  if en_lista "$servicio" "$GUARD_NO_RESTART"; then
    alert "guard: $nombre ($servicio) esta unhealthy; no se reinicia solo" \
      "Mirar: docker logs --tail 200 $nombre" "guard-no-reinicia-$nombre" 60
    continue
  fi

  archivo="$estado/$nombre"
  mapfile -t propios < <(recientes "$archivo")
  mapfile -t todos < <(recientes "$global")

  if [ "${#propios[@]}" -ge "$GUARD_MAX_RESTARTS" ]; then
    alert "guard: $nombre sigue unhealthy y ya se reinicio ${#propios[@]} veces en la ultima hora" \
      "No se reinicia mas hasta que baje el contador. Mirar: docker logs --tail 200 $nombre" \
      "guard-tope-$nombre" 60
    continue
  fi
  if [ "${#todos[@]}" -ge "$GUARD_MAX_TOTAL_RESTARTS" ]; then
    alert "guard: tope global de $GUARD_MAX_TOTAL_RESTARTS reinicios por hora alcanzado; $nombre sigue unhealthy" \
      "Demasiados contenedores cayendo a la vez: hace falta una persona." \
      "guard-tope-global" 60
    continue
  fi

  printf '%s\n' "${propios[@]}" "$ahora" >"$archivo"
  printf '%s\n' "${todos[@]}" "$ahora" >"$global"
  if docker restart "$nombre" >/dev/null; then
    alert "guard: reinicie $nombre (unhealthy)" \
      "Reinicio $((${#propios[@]} + 1)) de $GUARD_MAX_RESTARTS en la ultima hora."
  else
    alert "guard: fallo docker restart $nombre" "El contenedor sigue unhealthy." \
      "guard-fallo-$nombre" 30
  fi
done
