#!/usr/bin/env bash
# Deploy y rollback en el VPS (F0-03). Uso, desde el clon del servidor:
#
#   APP_VERSION=<sha> scripts/deploy.sh deploy     (o: make deploy APP_VERSION=<sha>)
#   scripts/deploy.sh rollback                     (o: make rollback)
#
# Secuencia del deploy (docs/DEPLOY_RUNBOOK.md):
#   1. Preflight: Compose >= 2.24 (`!reset`), `docker compose config` valido,
#      los servicios de DEPLOY_SERVICES existen, la base corre, disco < 80 %,
#      backup exitoso de menos de 24 h.
#   2. Guarda la version que corre hoy en .deploy/previous.
#   3. `pull` de las imagenes de APP_VERSION (las construye CI:
#      .github/workflows/build-images.yml; el VPS no construye).
#   4. MIGRA ANTES DE RECREAR, con el codigo viejo sirviendo:
#      `compose run --rm --no-deps backend alembic upgrade head`. Por eso las
#      migraciones son expand/contract (CLAUDE.md §3): el codigo viejo tiene
#      que funcionar contra el esquema nuevo.
#   5. Backend gradual: levanta las replicas nuevas AL LADO de las viejas
#      (`--no-recreate --scale`), espera que esten sanas (`--wait`), deja que
#      nginx las resuelva (`resolve`), baja las viejas. Si las nuevas no quedan
#      sanas se descartan y las viejas siguen sirviendo. DEPLOY_ROLLING=0: `up`
#      directo (5-10 s de 502 mientras se recrean).
#   6. Resto de la app (workers, beat, frontend, nginx) con `up -d --no-deps`:
#      nunca recrea db/redis/rabbitmq.
#   7. `nginx -t` + `nginx -s reload`: por si cambio la imagen o la config de
#      nginx (el backend lo re-resuelve solo). Nunca restart.
#   8. Compuerta de 60 s: /api/ops/health/ready y la home responden, ningun
#      contenedor unhealthy, 5xx < 0,5 % en el log de nginx de los ultimos
#      2 minutos. Si falla: rollback automatico (sin migrar).
#
# Rollback: APP_VERSION = .deploy/previous; pull, pasos 5 a 8, NUNCA migra.
#
# Sin sudo ni docker.sock: el usuario que lo corre tiene que estar en el grupo
# docker. Las variables de abajo se pueden fijar en /etc/shifty/ops.env.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${DEPLOY_SERVICES:=backend celery_worker celery_worker_interactive celery_beat frontend nginx}"
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

preflight() {
  local completo="$1"

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
  docker compose run --rm --no-deps -T "$DEPLOY_BACKEND_SERVICE" alembic upgrade head
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
    docker compose up -d --no-deps --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT" "$servicio" || return 1
    return 0
  fi

  local viejas=() todas=() nuevas=() id
  mapfile -t viejas < <(docker compose ps -q "$servicio")
  local total=$((${#viejas[@]} + DEPLOY_BACKEND_REPLICAS))
  log "backend: ${#viejas[@]} replicas viejas, levanto $DEPLOY_BACKEND_REPLICAS nuevas"

  local fallo=0
  docker compose up -d --no-deps --no-recreate --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT" \
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
  docker compose up -d --no-deps "${resto[@]}" || return 1
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
  docker compose pull $DEPLOY_SERVICES || log "$etiqueta: pull fallo; sigo con las imagenes locales de $version"
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
  if desplegar_version "$anterior" rollback; then
    log "rollback: ok, corre $anterior"
    return 0
  fi
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
  docker compose pull $DEPLOY_SERVICES
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

case "${1:-deploy}" in
  deploy) cmd_deploy ;;
  rollback)
    tomar_lock
    preflight 0
    cmd_rollback
    ;;
  preflight) preflight 1 ;;
  *) die "uso: $0 [deploy|rollback|preflight]" ;;
esac
