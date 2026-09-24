#!/usr/bin/env bash
# Deploy y rollback en el VPS (F0-03). Uso, desde el clon del servidor:
#
#   APP_VERSION=<sha> scripts/deploy.sh deploy     (o: make deploy APP_VERSION=<sha>)
#   scripts/deploy.sh rollback                     (o: make rollback)
#   scripts/deploy.sh edge                         (o: make deploy-edge)
#
# Secuencia del deploy (docs/DEPLOY_RUNBOOK.md):
#   1. Preflight: COMPOSE_FILE incluye docker-compose.prod.yml, Compose >=
#      2.24 (`!reset`), `docker compose config` valido, los servicios de
#      DEPLOY_SERVICES existen, la base corre, disco < 80 %, backup exitoso de
#      menos de 24 h.
#   2. Guarda la version que corre hoy en .deploy/previous.
#   3. `pull` de las imagenes de APP_VERSION y verificacion de que cada
#      `imagen:tag` quedo local (las construye CI:
#      .github/workflows/build-images.yml). El VPS NUNCA construye: todo `up`
#      y `run` lleva --no-build.
#   4. MIGRA ANTES DE RECREAR, con el codigo viejo sirviendo:
#      `compose run --rm --no-deps backend alembic upgrade head`. Por eso las
#      migraciones son expand/contract (CLAUDE.md §3): el codigo viejo tiene
#      que funcionar contra el esquema nuevo.
#   5. Backend gradual: levanta las replicas nuevas AL LADO de las viejas
#      (`--no-recreate --scale`), espera que esten sanas (`--wait`), deja que
#      nginx las resuelva (`resolve`), baja las viejas. Si las nuevas no quedan
#      sanas se descartan y las viejas siguen sirviendo. DEPLOY_ROLLING=0: `up`
#      directo (5-10 s de 502 mientras se recrean).
#   6. Resto de la app (workers, beat, frontend) con `up -d --no-deps`:
#      nunca recrea db/redis/rabbitmq ni el borde. El frontend se recrea si
#      cambio su imagen: la SPA da 502 un instante.
#   7. `nginx -t` + `nginx -s reload`. El borde (nginx) solo se RECARGA en un
#      deploy normal; se recrea unicamente con `edge` (make deploy-edge),
#      cuando cambio su imagen o su config.
#   8. Compuerta de 60 s: /api/ops/health/ready y la home responden, ningun
#      contenedor unhealthy, 5xx < 0,5 % en el log de nginx de los ultimos
#      2 minutos. Si falla: rollback automatico (sin migrar).
#
# Rollback: APP_VERSION = .deploy/previous; pull, pasos 5 a 8, NUNCA migra.
# Si el pull falla sigue con las imagenes locales, pero solo si estan todas:
# si falta una, sale con 2 y alerta sin tocar nada.
#
# Edge: pull de nginx y recreacion SOLO si cambio el id de su imagen o la
# config montada (un bind mount de un archivo sigue viendo el inodo viejo
# cuando git lo reemplaza: hace falta recrear, no alcanza con reload).
#
# Sin sudo ni docker.sock: el usuario que lo corre tiene que estar en el grupo
# docker. Las variables de abajo se pueden fijar en /etc/shifty/ops.env.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# Compose toma el proyecto, el .env y COMPOSE_FILE del directorio actual.
cd "$SHIFTY_DIR"

# Sin nginx: el borde se recarga, no se recrea (ver `edge`).
: "${DEPLOY_SERVICES:=backend celery_worker celery_worker_interactive celery_beat frontend}"
: "${DEPLOY_BACKEND_SERVICE:=backend}"
: "${DEPLOY_BACKEND_REPLICAS:=3}"
: "${DEPLOY_ROLLING:=1}"
: "${DEPLOY_WAIT_TIMEOUT:=180}"
# Lo que tarda nginx en re-resolver `backend` (resolver valid=5s, F0-01).
: "${DEPLOY_DNS_SETTLE:=6}"
: "${DEPLOY_STOP_TIMEOUT:=35}"
: "${DEPLOY_MIN_COMPOSE:=2.24.0}"
: "${DEPLOY_DISK_MAX_PERCENT:=80}"
: "${DEPLOY_BACKUP_MAX_AGE_HOURS:=24}"
: "${DEPLOY_SKIP_BACKUP_CHECK:=0}"
: "${DOMAIN:=}"
: "${DEPLOY_HEALTH_URL:=${DOMAIN:+https://$DOMAIN/api/ops/health/ready}}"
: "${DEPLOY_SMOKE_URLS:=${DOMAIN:+https://$DOMAIN/}}"
# 12 x 5 s = 60 s de compuerta; se tolera UN fallo suelto.
: "${DEPLOY_GATE_CHECKS:=12}"
: "${DEPLOY_GATE_INTERVAL:=5}"
: "${DEPLOY_GATE_MAX_FAILURES:=1}"
: "${DEPLOY_GATE_LOG_WINDOW:=2m}"
# 5xx: falla si supera 0,5 % Y hay al menos DEPLOY_GATE_MIN_5XX. Con poco
# trafico un 502 suelto no dispara un rollback.
: "${DEPLOY_GATE_MIN_5XX:=3}"
: "${DEPLOY_AUTO_ROLLBACK:=1}"
: "${DEPLOY_EDGE_SERVICE:=nginx}"
# Archivos que el borde monta por bind mount (relativos al clon).
: "${DEPLOY_EDGE_CONF_FILES:=nginx/nginx.prod.conf}"
: "${DEPLOY_PROD_COMPOSE:=docker-compose.prod.yml}"

estado_dir="$SHIFTY_DIR/.deploy"
lock="$estado_dir/lock"

# --- utilidades -------------------------------------------------------------

tomar_lock() {
  mkdir -p "$estado_dir"
  if ! mkdir "$lock" 2>/dev/null; then
    die "hay otro deploy en curso (lock $lock). Si no lo hay, borrar el directorio a mano."
  fi
  trap 'rm -rf -- "$lock"' EXIT
}

version_en_curso() {
  if [ -s "$estado_dir/current" ]; then
    head -n 1 "$estado_dir/current"
    return
  fi
  # Primer deploy con este script: el tag de la imagen del backend que corre.
  local id imagen
  id="$(docker compose ps -q "$DEPLOY_BACKEND_SERVICE" | head -n 1)"
  [ -n "$id" ] || return 0
  imagen="$(docker inspect -f '{{.Config.Image}}' "$id")"
  case "$imagen" in *:*) printf '%s\n' "${imagen##*:}" ;; esac
}

version_mayor_o_igual() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n 1)" = "$2" ]
}

# --- preflight --------------------------------------------------------------

# COMPOSE_FILE del entorno (gana, como en compose) o del .env del clon.
compose_file_efectivo() {
  if [ -n "${COMPOSE_FILE:-}" ]; then
    printf '%s\n' "$COMPOSE_FILE"
    return
  fi
  sed -n 's/^[[:space:]]*COMPOSE_FILE[[:space:]]*=[[:space:]]*//p' .env 2>/dev/null |
    tail -n 1 | tr -d '"'"'"'\r'
}

preflight() {
  local completo="$1"

  local archivos
  archivos="$(compose_file_efectivo)"
  case ":$archivos:" in
    *":$DEPLOY_PROD_COMPOSE:"* | *"/$DEPLOY_PROD_COMPOSE:"*) ;;
    *) die "preflight: COMPOSE_FILE (${archivos:-vacio}) no incluye $DEPLOY_PROD_COMPOSE; fijarlo en el .env del servidor (docs/DEPLOY_RUNBOOK.md §1)" ;;
  esac

  local version
  version="$(docker compose version --short 2>/dev/null || true)"
  version="${version#v}"
  if [ -z "$version" ] || ! version_mayor_o_igual "$version" "$DEPLOY_MIN_COMPOSE"; then
    die "preflight: Docker Compose ${version:-?} < 2.24: no entiende \`!reset\` y publicaria los puertos internos (docs/RELEASE_CHECKLIST.md)"
  fi
  docker compose config -q || die "preflight: docker compose config no valida (COMPOSE_FILE en el .env del servidor?)"

  local servicios s
  servicios=" $(docker compose config --services | tr '\n' ' ') "
  for s in $DEPLOY_SERVICES; do
    case "$servicios" in
      *" $s "*) ;;
      *) die "preflight: el servicio $s no existe en el compose; ajustar DEPLOY_SERVICES" ;;
    esac
  done
  if [ -z "$(docker compose ps -q db)" ]; then
    die "preflight: la base (servicio db) no esta corriendo; el deploy no la levanta (--no-deps)"
  fi
  [ -n "$DEPLOY_HEALTH_URL" ] || die "preflight: falta DOMAIN (o DEPLOY_HEALTH_URL) para la compuerta"

  [ "$completo" = 1 ] || return 0

  local uso
  uso="$(disk_use_percent "$SHIFTY_DIR")"
  if [ "${uso:-100}" -ge "$DEPLOY_DISK_MAX_PERCENT" ]; then
    die "preflight: disco al ${uso} % (maximo $DEPLOY_DISK_MAX_PERCENT %); un pull puede llenarlo"
  fi

  if [ "$DEPLOY_SKIP_BACKUP_CHECK" != 1 ]; then
    local registro="$BACKUP_DIR/last-success" ultimo
    ultimo="$(awk 'NR == 1 { print $1 }' "$registro" 2>/dev/null || true)"
    case "$ultimo" in
      '' | *[!0-9]*) die "preflight: no hay backup exitoso registrado en $registro (scripts/backup.sh)" ;;
    esac
    if [ $(($(date +%s) - ultimo)) -ge $((DEPLOY_BACKUP_MAX_AGE_HOURS * 3600)) ]; then
      die "preflight: el ultimo backup exitoso tiene mas de ${DEPLOY_BACKUP_MAX_AGE_HOURS} h; correr scripts/backup.sh antes de migrar"
    fi
  fi
  log "preflight: ok (compose $version, disco ${uso} %)"
}

# --- pasos ------------------------------------------------------------------

migrar() {
  log "migrando a head con el codigo viejo sirviendo"
  docker compose run --rm --no-deps --no-build -T "$DEPLOY_BACKEND_SERVICE" alembic upgrade head
}

# Las funciones de pasos devuelven su error con `|| return 1` explicito: se
# llaman dentro de `if` y `&&`, donde bash apaga `set -e` para todo su cuerpo.
recargar_nginx() {
  docker compose exec -T nginx nginx -t || return 1
  docker compose exec -T nginx nginx -s reload || return 1
}

# Replicas nuevas al lado de las viejas; las viejas se bajan solo cuando las
# nuevas estan sanas. Verificado con Compose v5.5: `--no-recreate --scale`
# crea las que faltan con la configuracion nueva y deja las existentes.
backend_gradual() {
  local servicio="$DEPLOY_BACKEND_SERVICE"
  if [ "$DEPLOY_ROLLING" != 1 ]; then
    log "backend: recreacion directa (DEPLOY_ROLLING=0): 5-10 s de 502"
    docker compose up -d --no-deps --no-build --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT" "$servicio" || return 1
    return 0
  fi

  local viejas=() todas=() nuevas=() id
  mapfile -t viejas < <(docker compose ps -q "$servicio")
  local total=$((${#viejas[@]} + DEPLOY_BACKEND_REPLICAS))
  log "backend: ${#viejas[@]} replicas viejas, levanto $DEPLOY_BACKEND_REPLICAS nuevas"

  local fallo=0
  docker compose up -d --no-deps --no-build --no-recreate --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT" \
    --scale "$servicio=$total" "$servicio" || fallo=1

  mapfile -t todas < <(docker compose ps -q "$servicio")
  for id in "${todas[@]}"; do
    case " ${viejas[*]} " in *" $id "*) ;; *) nuevas+=("$id") ;; esac
  done

  if [ "$fallo" = 1 ]; then
    if [ "${#nuevas[@]}" -gt 0 ]; then
      docker rm -f "${nuevas[@]}" >/dev/null || true
    fi
    log "backend: las replicas nuevas no quedaron sanas en ${DEPLOY_WAIT_TIMEOUT} s; se descartaron y siguen las viejas"
    log "backend: si el error dice container_name, el servicio no se puede escalar (DEPLOY_ROLLING=0)"
    return 1
  fi

  # nginx re-resuelve `backend` solo (`server backend:8000 resolve` +
  # `resolver 127.0.0.11 valid=5s`, nginx/nginx.prod.conf): se espera que
  # aprenda las IPs nuevas antes de bajar las viejas. El reload del final es
  # por si cambio la imagen o la config de nginx.
  sleep "$DEPLOY_DNS_SETTLE"
  if [ "${#viejas[@]}" -gt 0 ]; then
    docker stop -t "$DEPLOY_STOP_TIMEOUT" "${viejas[@]}" >/dev/null || return 1
    docker rm "${viejas[@]}" >/dev/null || return 1
  fi
  log "backend: ${#nuevas[@]} replicas nuevas sirviendo"
}

resto_de_la_app() {
  local resto=() s
  for s in $DEPLOY_SERVICES; do
    [ "$s" = "$DEPLOY_BACKEND_SERVICE" ] || resto+=("$s")
  done
  [ "${#resto[@]}" -gt 0 ] || return 0
  docker compose up -d --no-deps --no-build "${resto[@]}" || return 1
}

# Cada `imagen:tag` que va a correr tiene que estar local: sin esto, un pull
# a medias terminaba en un `up` que construia o que fallaba a mitad de camino.
imagenes_locales() {
  local imagen faltan=""
  # shellcheck disable=SC2086
  for imagen in $(docker compose config --images $DEPLOY_SERVICES); do
    docker image inspect "$imagen" >/dev/null 2>&1 || faltan="$faltan $imagen"
  done
  if [ -n "$faltan" ]; then
    log "faltan imagenes locales:$faltan"
    return 1
  fi
}

# --- compuerta --------------------------------------------------------------

compuerta() {
  local fallos=0 i url
  for ((i = 1; i <= DEPLOY_GATE_CHECKS; i++)); do
    for url in $DEPLOY_HEALTH_URL $DEPLOY_SMOKE_URLS; do
      if ! curl -fsS -o /dev/null -m 5 "$url"; then
        fallos=$((fallos + 1))
        log "compuerta: $url no respondio bien ($i/$DEPLOY_GATE_CHECKS)"
      fi
    done
    sleep "$DEPLOY_GATE_INTERVAL"
  done
  if [ "$fallos" -gt "$DEPLOY_GATE_MAX_FAILURES" ]; then
    log "compuerta: $fallos chequeos fallidos (maximo $DEPLOY_GATE_MAX_FAILURES)"
    return 1
  fi

  local ids enfermos
  ids="$(docker compose ps -q | tr '\n' ' ')"
  if [ -n "${ids// /}" ]; then
    # shellcheck disable=SC2086
    enfermos="$(docker inspect -f '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' $ids |
      awk '$2 == "unhealthy" { sub("^/", "", $1); print $1 }' | tr '\n' ' ')"
    if [ -n "${enfermos// /}" ]; then
      log "compuerta: contenedores unhealthy: $enfermos"
      return 1
    fi
  fi

  local lineas total errores
  lineas="$(docker compose logs --no-log-prefix --since "$DEPLOY_GATE_LOG_WINDOW" nginx 2>/dev/null || true)"
  total="$(printf '%s\n' "$lineas" | grep -c '"s":' || true)"
  errores="$(printf '%s\n' "$lineas" | grep -cE '"s":"?5[0-9]{2}' || true)"
  if [ "$errores" -ge "$DEPLOY_GATE_MIN_5XX" ] && [ $((errores * 1000)) -gt $((total * 5)) ]; then
    log "compuerta: 5xx $errores de $total en $DEPLOY_GATE_LOG_WINDOW (> 0,5 %)"
    return 1
  fi
  log "compuerta: ok ($fallos fallos sueltos, 5xx $errores/$total)"
}

# --- subcomandos ------------------------------------------------------------

# pull + backend + resto + reload + compuerta, sin migrar.
desplegar_version() {
  local version="$1" etiqueta="$2"
  export APP_VERSION="$version"
  # shellcheck disable=SC2086
  docker compose pull $DEPLOY_SERVICES || log "$etiqueta: pull fallo; sigo solo si las imagenes de $version estan locales"
  if ! imagenes_locales; then
    alert "deploy: $etiqueta a $version imposible, faltan imagenes locales" \
      "Sin pull y sin las imagenes en el host no hay a que volver. No se toco nada."
    return 2
  fi
  backend_gradual || return 1
  resto_de_la_app || return 1
  recargar_nginx || return 1
  printf '%s\n' "$version" >"$estado_dir/current"
  compuerta
}

cmd_rollback() {
  local anterior
  anterior="$(head -n 1 "$estado_dir/previous" 2>/dev/null || true)"
  [ -n "$anterior" ] || die "rollback: no hay version anterior en $estado_dir/previous"
  log "rollback a $anterior (sin migrar)"
  local codigo=0
  desplegar_version "$anterior" rollback || codigo=$?
  if [ "$codigo" = 0 ]; then
    log "rollback: ok, corre $anterior"
    return 0
  fi
  [ "$codigo" = 2 ] && return 2
  alert "deploy: el ROLLBACK a $anterior tambien fallo la compuerta" \
    "Intervenir a mano: docker compose ps; docker compose logs --tail 200 backend nginx"
  return 2
}

cmd_deploy() {
  [ -n "${APP_VERSION:-}" ] || die "falta APP_VERSION (el sha de la imagen construida por CI)"
  local nueva="$APP_VERSION"
  tomar_lock
  preflight 1

  local anterior
  anterior="$(version_en_curso)"
  if [ -n "$anterior" ]; then
    printf '%s\n' "$anterior" >"$estado_dir/previous"
  fi
  log "deploy: ${anterior:-(sin version previa)} -> $nueva"

  export APP_VERSION="$nueva"
  # shellcheck disable=SC2086
  docker compose pull $DEPLOY_SERVICES || die "deploy: pull de $nueva fallo (la imagen esta publicada en GHCR? docker login ghcr.io?)"
  imagenes_locales || die "deploy: despues del pull faltan imagenes de $nueva; no se migra ni se recrea nada"
  migrar

  if ! backend_gradual; then
    alert "deploy $nueva: el backend nuevo no quedo sano" "Siguen sirviendo las replicas de ${anterior:-antes}. La migracion ya corrio (expand/contract)."
    exit 1
  fi
  if resto_de_la_app && recargar_nginx && printf '%s\n' "$nueva" >"$estado_dir/current" && compuerta; then
    log "deploy: ok, corre $nueva"
    return 0
  fi

  alert "deploy $nueva: fallo la compuerta, rollback a ${anterior:-?}" "Ver docs/DEPLOY_RUNBOOK.md"
  if [ "$DEPLOY_AUTO_ROLLBACK" != 1 ] || [ -z "$anterior" ]; then
    log "deploy: sin rollback automatico (DEPLOY_AUTO_ROLLBACK=$DEPLOY_AUTO_ROLLBACK, previa=${anterior:-ninguna})"
    exit 1
  fi
  local codigo=0
  cmd_rollback || codigo=$?
  exit $((codigo == 0 ? 1 : codigo))
}

# El borde: se recarga en cada deploy; se RECREA solo si cambio su imagen o
# la config que monta. Recrearlo corta todo el trafico un instante.
cmd_edge() {
  tomar_lock
  usar_version_en_curso
  [ -n "${APP_VERSION:-}" ] || die "edge: no hay version en curso (.deploy/current); hacer un deploy primero"
  local servicio="$DEPLOY_EDGE_SERVICE" imagen deseada corriendo id huella anterior
  docker compose pull "$servicio" || die "edge: pull de $servicio fallo"
  imagen="$(docker compose config --images "$servicio" | head -n 1)"
  deseada="$(docker image inspect -f '{{.Id}}' "$imagen")" || die "edge: falta la imagen $imagen"
  id="$(docker compose ps -q "$servicio" | head -n 1)"
  corriendo=""
  [ -z "$id" ] || corriendo="$(docker inspect -f '{{.Image}}' "$id")"
  # shellcheck disable=SC2086
  huella="$(cat $DEPLOY_EDGE_CONF_FILES | sha256sum | cut -d' ' -f1)"
  anterior="$(cat "$estado_dir/edge-conf.sha256" 2>/dev/null || true)"

  if [ "$deseada" != "$corriendo" ] || [ "$huella" != "$anterior" ]; then
    log "edge: recreo $servicio (imagen ${corriendo:-ninguna} -> $deseada, config ${anterior:-sin registro} -> $huella)"
    docker compose up -d --no-deps --no-build --force-recreate --wait \
      --wait-timeout "$DEPLOY_WAIT_TIMEOUT" "$servicio" ||
      die "edge: $servicio no quedo sano despues de recrearlo"
  else
    log "edge: sin cambios de imagen ni de config, solo reload"
  fi
  recargar_nginx || die "edge: nginx -t o reload fallo"
  printf '%s\n' "$huella" >"$estado_dir/edge-conf.sha256"
  log "edge: ok"
}

case "${1:-deploy}" in
  deploy) cmd_deploy ;;
  edge) cmd_edge ;;
  rollback)
    tomar_lock
    # El compose de produccion exige APP_VERSION hasta para `config`: el
    # preflight ya corre con la version a la que se vuelve.
    APP_VERSION="$(head -n 1 "$estado_dir/previous" 2>/dev/null || true)"
    [ -n "$APP_VERSION" ] || die "rollback: no hay version anterior en $estado_dir/previous"
    export APP_VERSION
    preflight 0
    cmd_rollback
    ;;
  preflight) preflight 1 ;;
  *) die "uso: $0 [deploy|rollback|edge|preflight]" ;;
esac
