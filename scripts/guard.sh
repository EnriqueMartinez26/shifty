#!/usr/bin/env bash
# Guard del host (F0-21): reinicia los contenedores `unhealthy` del proyecto.
#
# `restart: always` solo actua cuando el proceso MUERE; un contenedor vivo
# pero `unhealthy` (API colgada, worker que dejo de consumir) queda asi para
# siempre. Esto lo corre cron cada minuto (deploy/cron/shifty-guard), como
# root, con el CLI de docker: sin autoheal ni docker.sock montado en un
# contenedor (plan §7, decision 25).
#
# Tope: GUARD_MAX_RESTARTS (3) reinicios por contenedor en GUARD_WINDOW_SECONDS
# (1 h). Pasado el tope no reinicia mas y avisa: un contenedor que vuelve a
# caer cada 20 minutos necesita una persona, no un bucle. Cada reinicio avisa.
# Durante un deploy (lock en .deploy/lock) no hace nada.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${GUARD_MAX_RESTARTS:=3}"
: "${GUARD_WINDOW_SECONDS:=3600}"
# Proyectos de compose que vigila; por defecto, el de este clon.
: "${GUARD_PROJECTS:=$COMPOSE_PROJECT_NAME}"

if deploy_in_progress; then
  log "guard: hay un deploy en curso, no se reinicia nada"
  exit 0
fi

estado="$SHIFTY_STATE_DIR/guard"
mkdir -p "$estado"
ahora="$(date +%s)"

for proyecto in $GUARD_PROJECTS; do
  ids="$(docker ps -q --filter health=unhealthy --filter "label=com.docker.compose.project=$proyecto")"
  for id in $ids; do
    nombre="$(docker inspect -f '{{.Name}}' "$id")"
    nombre="${nombre#/}"
    archivo="$estado/$nombre"

    recientes=()
    if [ -f "$archivo" ]; then
      while read -r marca; do
        case "$marca" in '' | *[!0-9]*) continue ;; esac
        if [ $((ahora - marca)) -lt "$GUARD_WINDOW_SECONDS" ]; then
          recientes+=("$marca")
        fi
      done <"$archivo"
    fi

    if [ "${#recientes[@]}" -ge "$GUARD_MAX_RESTARTS" ]; then
      alert "guard: $nombre sigue unhealthy y ya se reinicio ${#recientes[@]} veces en la ultima hora" \
        "No se reinicia mas hasta que baje el contador. Mirar: docker logs --tail 200 $nombre" \
        "guard-tope-$nombre" 60
      continue
    fi

    printf '%s\n' "${recientes[@]}" "$ahora" >"$archivo"
    if docker restart "$nombre" >/dev/null; then
      alert "guard: reinicie $nombre (unhealthy)" \
        "Reinicio $((${#recientes[@]} + 1)) de $GUARD_MAX_RESTARTS en la ultima hora."
    else
      alert "guard: fallo docker restart $nombre" "El contenedor sigue unhealthy." \
        "guard-fallo-$nombre" 30
    fi
  done
done
