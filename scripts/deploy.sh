#!/usr/bin/env bash
# Deploy y rollback en el VPS (F0-03). Uso, desde el clon del servidor:
#
#   APP_VERSION=<sha> bash scripts/deploy.sh deploy   (o: make deploy APP_VERSION=<sha>)
#   bash scripts/deploy.sh rollback                    (o: make rollback)
#   bash scripts/deploy.sh edge                        (o: make deploy-edge)
#
# El VPS no tiene `make`: ahi se usa la forma con bash; make es solo un atajo
# donde este instalado.
#
# Secuencia del deploy (docs/DEPLOY_RUNBOOK.md):
#   1. Preflight: COMPOSE_FILE incluye docker-compose.prod.yml, Compose >=
#      2.24 (`!reset`), `docker compose config` valido, los servicios de
#      DEPLOY_SERVICES existen, la base corre, disco < 80 %, store y politica
#      de retencion de assets validos, backup exitoso de menos de 24 h, y
#      Quality paso en main para APP_VERSION (API de GitHub, con
#      DEPLOY_GITHUB_TOKEN si el repo es privado; `workflow_dispatch` de
#      build-images.yml publica sin esa compuerta). El rollback no pregunta:
#      es el camino de emergencia.
#   2. `pull` de las imagenes de APP_VERSION y verificacion de que cada
#      `imagen:tag` quedo local (las construye CI:
#      .github/workflows/build-images.yml). El VPS NUNCA construye: todo `up`
#      lleva --no-build y --remove-orphans (un servicio renombrado, como
#      `redis` -> `redis_cache`/`redis_state`, dejaba vivo el contenedor viejo
#      con su puerto). `run` no tiene --no-build en ninguna version de
#      Compose (ver `migrar`).
#   3. Assets y borde antes de migrar: extrae, importa y verifica los assets
#      inmutables de cada replica frontend activa, el destino de rollback y la
#      version candidata; confirma que `nginx` corre con el montaje `:ro` del
#      store y la huella/imagen esperada (un deploy normal nunca recrea el
#      borde). Cualquier error frena antes de migrar o recrear la app.
#   4. Guarda la version que corre hoy en .deploy/previous (y frontend-previous
#      cuando cambia el frontend), salvo en un redeploy del mismo sha: ahi
#      previous queda como estaba.
#   5. MIGRA ANTES DE RECREAR, con el codigo viejo sirviendo:
#      `compose run --rm --no-deps -T backend alembic upgrade head`. Por eso las
#      migraciones son expand/contract (CLAUDE.md §3): el codigo viejo tiene
#      que funcionar contra el esquema nuevo.
#   6. Backend y frontend graduales (los dos servicios detras del borde):
#      levanta las replicas nuevas AL LADO de las viejas (`--no-recreate
#      --scale`), espera que esten sanas (`--wait`), deja que nginx las
#      resuelva (`resolve`), baja las viejas. Si las nuevas no quedan sanas se
#      descartan y las viejas siguen sirviendo. Primero el backend y despues el
#      frontend, que corre UNA replica y en el cambio tiene dos un momento
#      (2026-10-15: recrearlo dejaba la home en 502 en cada deploy). Bajada la
#      vieja, `nginx -t` + reload para que el borde la saque de sus peers en
#      el momento (si no, la tiene hasta 5 s mas).
#      DEPLOY_ROLLING=0: `up` directo (5-10 s de 502 mientras se recrean).
#   7. Resto de la app (workers, beat) con `up -d --no-deps`: nunca recrea
#      db/redis/rabbitmq ni el borde.
#   8. `nginx -t` + `nginx -s reload`, escribe `.deploy/current` y
#      `.deploy/frontend-current`. El borde (nginx) solo se RECARGA en un
#      deploy normal; se recrea unicamente con `edge` (make deploy-edge),
#      cuando cambio su imagen, su config o el store montado.
#   9. Compuerta de 60 s: /api/ops/health/ready y la home responden, ningun
#      contenedor unhealthy, `rabbitmq-diagnostics alarms` sin alarmas, 5xx < 0,5 %
#      en el log de nginx de los ultimos 2 minutos, y smoke HTTP de un asset JS
#      del release contra su SHA-256 y tamano del manifest. Si pasa, ejecuta GC
#      no bloqueante de releases vencidos. Si falla: rollback automatico (sin
#      migrar); en un redeploy del mismo sha, alerta sin rollback (antes ya
#      corria esa version).
#
# Rollback: APP_VERSION = .deploy/previous; pull, verifica/importa assets y
# montaje `:ro` del borde (sin recrear nginx), pasos 6 a 9, NUNCA migra.
# Si el pull falla sigue con las imagenes locales, pero solo si estan todas:
# si falta una, sale con 2 y alerta sin tocar nada.
#
# Edge: prepara/importa/verifica los assets activos y previos, hace pull de
# nginx y recrea SOLO si falta el contenedor, cambio el id de su imagen,
# cambio la huella (config + asset store) o falta el montaje `:ro` (un bind
# mount de un archivo sigue viendo el inodo viejo cuando git lo reemplaza:
# hace falta recrear, no alcanza con reload). Cuando hace falta recrear,
# primero prueba la config con `nginx -t` en un contenedor efimero
# (`--entrypoint nginx -T nginx -t`): si falla, no recrea ni registra huella
# y el borde actual sigue sirviendo. Si no hubo cambios, omite el contenedor
# efimero y solo recarga nginx.
#
# Sin sudo ni docker.sock: el usuario que lo corre tiene que estar en el grupo
# docker. Las variables de abajo se pueden fijar en /etc/shifty/ops.env.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RELEASE_ASSET_HELPER="$script_dir/release-assets.sh"

# shellcheck source=lib/common.sh
. "$script_dir/lib/common.sh"

# Compose toma el proyecto, el .env y COMPOSE_FILE del directorio actual.
cd "$SHIFTY_DIR"

# Sin nginx: el borde se recarga, no se recrea (ver `edge`).
: "${DEPLOY_SERVICES:=backend celery_worker celery_worker_interactive celery_beat frontend}"
: "${DEPLOY_BACKEND_SERVICE:=backend}"
# Las mismas que `deploy.replicas` de docker-compose.prod.yml (contrato en
# test_compose_contract): en el pico corren el doble, viejas mas nuevas.
: "${DEPLOY_BACKEND_REPLICAS:=2}"
# La SPA estatica (nginx, 64M): una replica alcanza en estado estable. El
# deploy levanta la nueva al lado de la vieja y la vieja se baja despues.
: "${DEPLOY_FRONTEND_SERVICE:=frontend}"
: "${DEPLOY_FRONTEND_REPLICAS:=1}"
: "${DEPLOY_ROLLING:=1}"
: "${DEPLOY_WAIT_TIMEOUT:=180}"
# Lo que tarda nginx en re-resolver `backend` y `frontend` (resolver
# valid=5s, F0-01).
: "${DEPLOY_DNS_SETTLE:=6}"
: "${DEPLOY_STOP_TIMEOUT:=35}"
: "${DEPLOY_MIN_COMPOSE:=2.24.0}"
: "${DEPLOY_DISK_MAX_PERCENT:=80}"
: "${DEPLOY_BACKUP_MAX_AGE_HOURS:=24}"
: "${DEPLOY_SKIP_BACKUP_CHECK:=0}"
# Quality verde en main para el sha (preflight). Saltearlo (staging con una
# imagen de rama) deja una alerta.
: "${DEPLOY_SKIP_QUALITY_CHECK:=0}"
: "${DEPLOY_GITHUB_REPO:=EnriqueMartinez26/shifty}"
: "${DEPLOY_QUALITY_WORKFLOW:=quality.yml}"
# DEPLOY_GITHUB_TOKEN (opcional): solo lo usa quality_verde, por stdin de
# curl. common.sh lo des-exporta: no llega al entorno de docker/compose.
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
: "${DEPLOY_ASSET_MIN_FREE_BYTES:=536870912}"
: "${DEPLOY_ASSET_RETENTION_DAYS:=14}"
: "${DEPLOY_ASSET_MIN_RELEASES:=3}"
: "${DEPLOY_ASSET_PROTECTED_RELEASES:=}"

asset_tmp_dirs=()
asset_container_ids=()
asset_releases=()
asset_image_ids=()
asset_sources=()
asset_estimated_bytes=()
asset_needs_extract=()

estado_dir="$SHIFTY_DIR/.deploy"
lock="$estado_dir/lock"

# --- utilidades -------------------------------------------------------------

tomar_lock() {
  mkdir -p "$estado_dir"
  if ! mkdir "$lock" 2>/dev/null; then
    die "hay otro deploy en curso (lock $lock). Si no lo hay, borrar el directorio a mano."
  fi
  trap limpiar_deploy EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

escribir_estado() {
  local destino="$1" valor="$2" tmp
  mkdir -p "$(dirname "$destino")" || return 1
  tmp="$(mktemp "${destino}.XXXXXX")" || return 1
  if ! printf '%s\n' "$valor" >"$tmp" || ! mv -f "$tmp" "$destino"; then
    rm -f "$tmp" || true
    return 1
  fi
}

frontend_previous_release() {
  if [ -s "$estado_dir/frontend-previous" ]; then
    head -n 1 "$estado_dir/frontend-previous"
    return
  fi
  if [ -s "$estado_dir/frontend-current" ]; then
    return
  fi
  head -n 1 "$estado_dir/previous" 2>/dev/null || true
}

limpiar_deploy() {
  local id dir
  for id in "${asset_container_ids[@]:-}"; do
    [ -n "$id" ] && docker rm -f "$id" >/dev/null 2>&1 || true
  done
  for dir in "${asset_tmp_dirs[@]:-}"; do
    [ -n "$dir" ] && rm -rf -- "$dir" || true
  done
  rm -rf -- "$lock"
}

configurar_asset_store() {
  [[ "$DEPLOY_ASSET_RETENTION_DAYS" =~ ^(0|[1-9][0-9]*)$ &&
    "$DEPLOY_ASSET_MIN_RELEASES" =~ ^(0|[1-9][0-9]*)$ ]] ||
    die "preflight: politica de retencion de assets invalida"
  (( DEPLOY_ASSET_RETENTION_DAYS >= 14 && DEPLOY_ASSET_MIN_RELEASES >= 3 )) ||
    die "preflight: assets requiere al menos 14 dias y 3 releases"
  ASSET_STORE_PATH="$(asset_helper store "$DEPLOY_ASSET_STORE")" ||
    die "preflight: no se pudo preparar el asset store persistente"
  local env_store="" norm_env_store
  env_store="$(leer_env_repo ASSET_STORE_PATH)"
  if [ -n "$env_store" ]; then
    norm_env_store="$(asset_helper store "$env_store")" ||
      die "preflight: ASSET_STORE_PATH invalido en .env: $env_store"
    [ "$norm_env_store" = "$ASSET_STORE_PATH" ] ||
      die "preflight: DEPLOY_ASSET_STORE ($ASSET_STORE_PATH) difiere de ASSET_STORE_PATH en .env ($norm_env_store)"
  fi
  export ASSET_STORE_PATH
}

asset_helper() {
  SHIFTY_DIR="$SHIFTY_DIR" bash "$RELEASE_ASSET_HELPER" "$@"
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
  leer_env_repo COMPOSE_FILE
}

# Quality (quality.yml) tiene que haber pasado en un push a main para ESTE sha.
# build-images.yml solo publica despues de eso, salvo a mano
# (`workflow_dispatch`), que construye cualquier rama: sin esta pregunta, una
# imagen de un commit en rojo o de una rama sin mergear se podia desplegar.
# Con el repo privado la API contesta 404 sin token: DEPLOY_GITHUB_TOKEN
# (opcional, en /etc/shifty/ops.env; PAT fine-grained con solo "Actions: read"
# sobre este repo) va como `Authorization: Bearer` POR STDIN (`curl -K -`),
# nunca en argv, que cualquier usuario del host ve en `ps`. Sin token, la
# consulta anonima de siempre (60 por hora por IP, solo con repo publico).
# Falla cerrada: si GitHub no contesta, el deploy espera o se saltea a
# conciencia con DEPLOY_SKIP_QUALITY_CHECK=1.
quality_verde() {
  local version="${APP_VERSION:-}"
  # Va a una URL: solo lo que admite un tag de imagen.
  case "$version" in
    '' | *[!A-Za-z0-9_.-]*) die "preflight: APP_VERSION invalida (${version:-vacia}): tiene que ser el sha del commit" ;;
  esac
  if [ "$DEPLOY_SKIP_QUALITY_CHECK" = 1 ]; then
    alert "deploy: $version se despliega SIN verificar Quality (DEPLOY_SKIP_QUALITY_CHECK=1)" \
      "Solo para staging con una imagen de rama. En produccion, desplegar un sha de main con Quality verde."
    return 0
  fi
  local token="${DEPLOY_GITHUB_TOKEN:-}"
  # Va entre comillas en una linea de configuracion de curl: un caracter
  # fuera de los de un token de GitHub podria inyectar otra opcion. El
  # mensaje no lo repite.
  case "$token" in
    *[!A-Za-z0-9_]*) die "preflight: DEPLOY_GITHUB_TOKEN tiene caracteres que un token de GitHub no tiene (solo letras, digitos y _)" ;;
  esac
  local url respuesta
  # Sin `status=success` (ni `branch`/`event`): esos filtros salen de un indice
  # de GitHub que puede atrasarse horas. El 2026-11-23 la corrida 45080249904
  # (completed/success desde las 23:07 UTC) no aparecia con `status=success`
  # 4 h despues y el preflight frenaba un sha verde. Se piden todas las
  # corridas del sha y la identidad y el resultado se verifican aca.
  url="https://api.github.com/repos/$DEPLOY_GITHUB_REPO/actions/workflows/$DEPLOY_QUALITY_WORKFLOW/runs?head_sha=$version&exclude_pull_requests=true&per_page=100"
  if [ -n "$token" ]; then
    # printf es un builtin: el token no pasa por argv de ningun proceso.
    respuesta="$(printf 'header = "Authorization: Bearer %s"\n' "$token" |
      curl -fsS -m 15 -H 'Accept: application/vnd.github+json' -K - "$url")" ||
      die "preflight: no pude preguntarle a GitHub si Quality paso para $version (con DEPLOY_GITHUB_TOKEN: vencido o sin \"Actions: read\" sobre $DEPLOY_GITHUB_REPO?); reintentar, o DEPLOY_SKIP_QUALITY_CHECK=1 si se verifico a mano en Actions"
  elif ! respuesta="$(curl -fsS -m 15 -H 'Accept: application/vnd.github+json' "$url")"; then
    die "preflight: no pude preguntarle a GitHub si Quality paso para $version (repo privado sin DEPLOY_GITHUB_TOKEN?); reintentar, o DEPLOY_SKIP_QUALITY_CHECK=1 si se verifico a mano en Actions"
  fi
  local leidas total vistas
  leidas="$(printf '%s\n' "$respuesta" | corridas_de_quality)"
  total="$(printf '%s\n' "$leidas" | sed -n 's/^total \([0-9][0-9]*\)$/\1/p')"
  vistas="$(printf '%s\n' "$leidas" | sed -n 's/^vistas \([0-9][0-9]*\)$/\1/p')"
  if [ -z "$total" ] || [ -z "$vistas" ]; then
    die "preflight: respuesta inesperada de GitHub al buscar Quality para $version: ${respuesta:0:200}"
  fi
  # Mas corridas que las de una pagina: la ultima podria no estar entre las
  # vistas. No pasa con un sha (una corrida por push y sus reintentos).
  if [ "$total" -gt "$vistas" ]; then
    die "preflight: GitHub tiene $total corridas de Quality para $version y solo se leyeron $vistas; ver Actions > Quality"
  fi
  # La corrida de Quality (path exacto) de un push a main para ESTE sha (igual
  # caracter a caracter: GitHub da el sha completo de 40, asi que un sha corto
  # nunca coincide). Si hay varias, decide la mas nueva (id mayor): una verde
  # vieja no tapa una corrida posterior roja o en curso.
  local tipo id path sha rama evento estado conclusion
  local mejor=0 mejor_estado='' mejor_conclusion=''
  while IFS=$'\t' read -r tipo id path sha rama evento estado conclusion; do
    [ "$tipo" = corrida ] || continue
    [ "$path" = ".github/workflows/$DEPLOY_QUALITY_WORKFLOW" ] || continue
    [ "$sha" = "$version" ] || continue
    [ "$rama" = main ] || continue
    [ "$evento" = push ] || continue
    case "$id" in '' | *[!0-9]*) continue ;; esac
    if [ "$id" -gt "$mejor" ]; then
      mejor="$id" mejor_estado="$estado" mejor_conclusion="$conclusion"
    fi
  done <<<"$leidas"
  if [ "$mejor" = 0 ]; then
    die "preflight: Quality no paso en main para $version (no hay una corrida de un push a main para ese sha completo de 40 caracteres); ver Actions > Quality"
  fi
  if [ "$mejor_estado" != completed ] || [ "$mejor_conclusion" != success ]; then
    die "preflight: Quality no paso en main para $version: la corrida $mejor esta $mejor_estado/$mejor_conclusion; ver Actions > Quality"
  fi
  log "preflight: Quality verde en main para $version (corrida $mejor)"
}

# Lee la respuesta de GitHub (`.../runs`) por stdin e imprime:
#   total <total_count>
#   vistas <objetos de workflow_runs leidos>
#   corrida<TAB>id<TAB>path<TAB>head_sha<TAB>head_branch<TAB>event<TAB>status<TAB>conclusion
# Solo los campos directos de cada corrida: los anidados (repository.name,
# head_commit.message...) no se confunden con los de la corrida. Un campo que
# falta o viene vacio sale como `-`. Sin jq ni python3 garantizados en el host, awk (mawk en
# Ubuntu) recorre el JSON caracter a caracter respetando strings y escapes.
# Un JSON mal formado (llaves sin cerrar, string cortado, una coma de mas)
# imprime solo `error`, y quality_verde falla cerrada.
corridas_de_quality() {
  awk '
    function valor() {
      if (d == 0) { if (raiz) err = 1; raiz = 1; return }
      if (ty[d] == "{") { if (st[d] != "valor") err = 1 }
      else if (st[d] != "primero" && st[d] != "valor") err = 1
      st[d] = "coma"
    }
    function abrir(t) {
      if (d == 0 && t != "{") err = 1
      valor()
      if (d == 1 && t == "[" && k[1] == "workflow_runs") runs = 2
      d++
      ty[d] = t; st[d] = "primero"; k[d] = ""
      if (d == runs + 1 && t == "{") { split("", campo); vistas++ }
    }
    function cerrar(t) {
      if (d == 0 || (t == "}" && ty[d] != "{") || (t == "]" && ty[d] != "[") ||
          (st[d] != "primero" && st[d] != "coma")) { err = 1; return }
      if (d == runs + 1 && ty[d] == "{") {
        printf "corrida\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", f("id"), f("path"),
          f("head_sha"), f("head_branch"), f("event"), f("status"), f("conclusion")
      }
      if (d == runs) runs = -10
      d--
    }
    # Nunca vacio: `read` con IFS de tabulador junta dos tabuladores seguidos.
    function f(nombre) { return (nombre in campo && campo[nombre] != "") ? campo[nombre] : "-" }
    function escalar(v, es_string) {
      if (d > 0 && ty[d] == "{" && (st[d] == "primero" || st[d] == "clave")) {
        if (!es_string) { err = 1; return }
        k[d] = v; st[d] = "dos_puntos"; return
      }
      valor()
      if (d == 1 && k[1] == "total_count" && !es_string) total = v
      if (d == runs + 1) campo[k[d]] = v
    }
    { buf = buf $0 "\n" }
    END {
      runs = -10; n = length(buf)
      for (i = 1; i <= n && !err; i++) {
        c = substr(buf, i, 1)
        if (c == "\"") {
          s = ""; i++
          while (i <= n && (c = substr(buf, i, 1)) != "\"") {
            if (c == "\\") { s = s c substr(buf, i + 1, 1); i += 2 }
            else { s = s c; i++ }
          }
          if (i > n) { err = 1; break }
          escalar(s, 1)
        } else if (c == "{" || c == "[") abrir(c)
        else if (c == "}" || c == "]") cerrar(c)
        else if (c == ":") {
          if (d == 0 || ty[d] != "{" || st[d] != "dos_puntos") err = 1
          else st[d] = "valor"
        } else if (c == ",") {
          if (d == 0 || st[d] != "coma") err = 1
          else st[d] = (ty[d] == "{") ? "clave" : "valor"
        } else if (c != " " && c != "\t" && c != "\r" && c != "\n") {
          s = ""
          while (i <= n && substr(buf, i, 1) ~ /[A-Za-z0-9.+-]/) { s = s substr(buf, i, 1); i++ }
          i--
          if (s !~ /^(true|false|null|-?[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?)$/) err = 1
          else escalar(s, 0)
        }
      }
      if (err || d != 0 || !raiz || total !~ /^[0-9]+$/) { print "error"; exit }
      print "total " total
      print "vistas " (vistas + 0)
    }
  '
}

preflight() {
  local completo="$1"

  configurar_asset_store

  # El volumen pg_backups es un bind (docker-compose.prod.yml): si el
  # directorio del host no existe, `db` no puede recrearse.
  # mkdir + chmod aparte: si el chmod no se puede (otro dueno), el directorio
  # igual sirve y se avisa, en vez de frenar el deploy. 0750: el deploy corre
  # como `deploy` y lee last-success (docs/DEPLOY_RUNBOOK.md §1).
  if [ ! -d "$BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_DIR" ||
      die "preflight: no se pudo crear $BACKUP_DIR (crearlo como root: install -d -o root -g deploy -m 0750 $BACKUP_DIR)"
    chmod 0750 "$BACKUP_DIR" 2>/dev/null || log "preflight: no pude dejar $BACKUP_DIR en 0750"
    log "preflight: cree $BACKUP_DIR"
  fi

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

  local uso uso_assets
  uso="$(disk_use_percent "$SHIFTY_DIR")"
  if [ "${uso:-100}" -ge "$DEPLOY_DISK_MAX_PERCENT" ]; then
    die "preflight: disco al ${uso} % (maximo $DEPLOY_DISK_MAX_PERCENT %); un pull puede llenarlo"
  fi
  if [ -d "$ASSET_STORE_PATH" ]; then
    uso_assets="$(disk_use_percent "$ASSET_STORE_PATH")"
    if [ "${uso_assets:-100}" -ge "$DEPLOY_DISK_MAX_PERCENT" ]; then
      die "preflight: disco del asset store al ${uso_assets} % (maximo $DEPLOY_DISK_MAX_PERCENT %)"
    fi
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
  quality_verde
  log "preflight: ok (compose $version, disco ${uso} %)"
}

# --- pasos ------------------------------------------------------------------

# Sin --no-build: `compose run` no lo tiene (solo `up`/`create`; Compose
# 5.5.1 frena con "unknown flag", 2026-10-02) y `--pull never` existe recien
# desde 2.33, por encima de DEPLOY_MIN_COMPOSE. Igual no construye ni baja
# nada: la vista de produccion no tiene `build` (`build: !reset null`,
# test_produccion_no_construye_ninguna_imagen) y `imagenes_locales` ya
# verifico que la imagen de la version esta en el host.
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
# Uso: servicio_gradual <servicio> <replicas nuevas>. El servicio no puede
# fijar container_name (un nombre fijo impide una segunda replica).
servicio_gradual() {
  local servicio="$1" replicas="$2"
  if [ "$DEPLOY_ROLLING" != 1 ]; then
    log "$servicio: recreacion directa (DEPLOY_ROLLING=0): 5-10 s de 502"
    docker compose up -d --no-deps --no-build --remove-orphans --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT" "$servicio" || return 1
    return 0
  fi

  local viejas=() todas=() nuevas=() id
  mapfile -t viejas < <(docker compose ps -q "$servicio")
  local total=$((${#viejas[@]} + replicas))
  log "$servicio: ${#viejas[@]} replicas viejas, levanto $replicas nuevas"

  local fallo=0
  docker compose up -d --no-deps --no-build --remove-orphans --no-recreate --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT" \
    --scale "$servicio=$total" "$servicio" || fallo=1

  mapfile -t todas < <(docker compose ps -q "$servicio")
  for id in "${todas[@]}"; do
    case " ${viejas[*]} " in *" $id "*) ;; *) nuevas+=("$id") ;; esac
  done

  if [ "$fallo" = 1 ]; then
    if [ "${#nuevas[@]}" -gt 0 ]; then
      docker rm -f "${nuevas[@]}" >/dev/null || true
    fi
    log "$servicio: las replicas nuevas no quedaron sanas en ${DEPLOY_WAIT_TIMEOUT} s; se descartaron y siguen las viejas"
    log "$servicio: si el error dice container_name, el servicio no se puede escalar (DEPLOY_ROLLING=0)"
    return 1
  fi

  # nginx re-resuelve el servicio solo (`server backend:8000 resolve`,
  # `server frontend:3000 resolve` + `resolver 127.0.0.11 valid=5s`,
  # nginx/nginx.prod.conf): se espera que aprenda las IPs nuevas antes de
  # bajar las viejas. Un request que todavia va a una vieja que se apaga falla
  # al conectar y nginx lo reintenta en otra replica (`proxy_next_upstream`
  # por defecto: error timeout). El reload del final es por si cambio la
  # imagen o la config de nginx.
  sleep "$DEPLOY_DNS_SETTLE"
  if [ "${#viejas[@]}" -gt 0 ]; then
    docker stop -t "$DEPLOY_STOP_TIMEOUT" "${viejas[@]}" >/dev/null || return 1
    docker rm "${viejas[@]}" >/dev/null || return 1
  fi
  log "$servicio: ${#nuevas[@]} replicas nuevas sirviendo"
}

backend_gradual() {
  servicio_gradual "$DEPLOY_BACKEND_SERVICE" "$DEPLOY_BACKEND_REPLICAS"
}

# Solo si el frontend esta en DEPLOY_SERVICES (un staging sin SPA lo saca).
# Devuelve 1 si la replica nueva no quedo sana (sigue la vieja) y 2 si el
# borde no recargo despues de bajar la vieja.
frontend_gradual() {
  case " $DEPLOY_SERVICES " in
    *" $DEPLOY_FRONTEND_SERVICE "*) ;;
    *) return 0 ;;
  esac
  servicio_gradual "$DEPLOY_FRONTEND_SERVICE" "$DEPLOY_FRONTEND_REPLICAS" || return 1
  # Revision del PR #188: borrada la replica vieja, nginx la sigue teniendo
  # como peer hasta re-resolver (valid=5s) y la mitad de las conexiones nuevas
  # iban a una IP que ya no existe. El reload re-resuelve `frontend` en el
  # momento; proxy_connect_timeout 2s (nginx.prod.conf) cubre los requests
  # que lleguen antes.
  if ! recargar_nginx; then
    log "$DEPLOY_FRONTEND_SERVICE: nginx -t o reload fallo despues de bajar la replica vieja"
    return 2
  fi
}

resto_de_la_app() {
  local resto=() s
  for s in $DEPLOY_SERVICES; do
    [ "$s" = "$DEPLOY_BACKEND_SERVICE" ] || [ "$s" = "$DEPLOY_FRONTEND_SERVICE" ] || resto+=("$s")
  done
  [ "${#resto[@]}" -gt 0 ] || return 0
  docker compose up -d --no-deps --no-build --remove-orphans "${resto[@]}" || return 1
}

# Resuelve la imagen exacta de un unico servicio de compose.
# `docker compose config --images <svc>` incluye dependencias transitivas
# (`depends_on`) en orden no deterministico; parsear `services:` de la
# salida canonica de `docker compose config <svc>` devuelve solo la imagen
# del servicio pedido.
compose_service_image() {
  local servicio="$1"
  docker compose config "$servicio" | awk -v svc="$servicio" '
    found { next }
    { sub(/\r$/, "") }
    /^services:[[:space:]]*$/ { in_services = 1; in_target = 0; next }
    in_services && /^[^[:space:]]/ { in_services = 0; in_target = 0 }
    in_services && substr($0, 1, 2) == "  " && substr($0, 3, 1) != " " {
      line = substr($0, 3)
      sub(/[[:space:]]*$/, "", line)
      in_target = (line == svc ":")
      next
    }
    !found && in_target && /^    image:[[:space:]]+/ {
      sub(/^    image:[[:space:]]+/, "")
      sub(/[[:space:]]+$/, "")
      if ((substr($0, 1, 1) == "\"" && substr($0, length($0), 1) == "\"") ||
          (substr($0, 1, 1) == "'"'"'" && substr($0, length($0), 1) == "'"'"'")) {
        $0 = substr($0, 2, length($0) - 2)
      }
      print
      found = 1
    }
  '
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

asset_plan_release() {
  local release="$1" image_id="$2" i size_output size_kb bytes manifest
  for i in "${!asset_releases[@]}"; do
    if [[ "${asset_releases[$i]}" = "$release" ]]; then
      [[ "${asset_image_ids[$i]}" = "$image_id" ]] ||
        die "assets: replicas del release $release usan imagenes distintas"
      return 0
    fi
  done
  manifest="$ASSET_STORE_PATH/.manifests/$release.manifest"
  asset_releases+=("$release")
  asset_image_ids+=("$image_id")
  asset_sources+=("")
  if [[ -e "$manifest" || -L "$manifest" ]]; then
    asset_helper verify "$ASSET_STORE_PATH" "$release" "$image_id" ||
      die "assets: el manifest existente de $release no coincide con la imagen activa"
    asset_estimated_bytes+=(0)
    asset_needs_extract+=(0)
    return 0
  fi
  # The frontend image uses nginx:alpine, so BusyBox du is already available.
  # Estimate before docker cp writes any files into the persistent store.
  size_output="$(docker run --rm --network none --entrypoint sh "$image_id" \
    -c 'du -sk /usr/share/nginx/html/assets')" ||
    die "assets: no pude estimar el tamano de $release antes de extraerlo"
  size_kb="$(awk 'NR == 1 && $1 ~ /^[0-9]+$/ { print $1 }' <<<"$size_output")"
  [[ "$size_kb" =~ ^[0-9]+$ ]] || die "assets: estimacion invalida para $release: $size_output"
  bytes=$((10#$size_kb * 1024))
  asset_estimated_bytes+=("$bytes")
  asset_needs_extract+=(1)
}

asset_extract_release() {
  local i="$1" release image_id name container tmp actual
  [[ "${asset_needs_extract[$i]}" = 1 ]] || return 0
  release="${asset_releases[$i]}"
  image_id="${asset_image_ids[$i]}"
  tmp="$(mktemp -d "$ASSET_STORE_PATH/.staging/shifty-assets.XXXXXX")" ||
    die "assets: no pude crear el directorio temporal de extraccion"
  asset_tmp_dirs+=("$tmp")
  mkdir -p "$tmp/assets" ||
    die "assets: no pude crear el directorio temporal de assets"
  name="shifty-assets-$release-$$-$i"
  container="$(docker create --name "$name" "$image_id")" ||
    die "assets: no pude crear un contenedor detenido de $release"
  [ -n "$container" ] || die "assets: docker create no devolvio un id para $release"
  asset_container_ids+=("$container")
  actual="$(docker inspect -f '{{.Image}}' "$container")" ||
    die "assets: no pude verificar la identidad de la imagen $release"
  [ "$actual" = "$image_id" ] ||
    die "assets: la imagen del contenedor de extraccion no coincide para $release"
  docker cp "$container:/usr/share/nginx/html/assets/." "$tmp/assets/" ||
    die "assets: no pude extraer /usr/share/nginx/html/assets de $release"
  asset_sources[i]="$tmp/assets"
}

frontend_image_id() {
  local release="$1" image
  image="$(APP_VERSION="$release" compose_service_image "$DEPLOY_FRONTEND_SERVICE")"
  [ -n "$image" ] || return 1
  docker image inspect -f '{{.Id}}' "$image"
}

frontend_release_running() {
  local id image release
  id="$(docker compose ps -q "$DEPLOY_FRONTEND_SERVICE" | head -n 1)"
  [ -n "$id" ] || return 1
  image="$(docker inspect -f '{{.Config.Image}}' "$id")" ||
    die "assets: no pude identificar el release del frontend actual"
  release="${image##*:}"
  [[ "$release" =~ ^[A-Za-z0-9_.-]+$ ]] || die "assets: tag de frontend actual invalido"
  printf '%s\n' "$release"
}

importar_frontends_activos() {
  local ids id image release image_id
  ids="$(docker compose ps -q "$DEPLOY_FRONTEND_SERVICE")"
  [ -n "$ids" ] || die "assets: no hay frontend actual para proteger sus chunks"
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    image="$(docker inspect -f '{{.Config.Image}}' "$id")" ||
      die "assets: no pude identificar la imagen de un frontend activo"
    release="${image##*:}"
    [[ "$release" =~ ^[A-Za-z0-9_.-]+$ ]] || die "assets: tag de frontend activo invalido"
    image_id="$(docker inspect -f '{{.Image}}' "$id")" ||
      die "assets: no pude leer la identidad de un frontend activo"
    asset_plan_release "$release" "$image_id"
  done <<<"$ids"
}

frontend_release_target() {
  local requested="$1" current="$2"
  case " $DEPLOY_SERVICES " in
    *" $DEPLOY_FRONTEND_SERVICE "*) printf '%s\n' "$requested" ;;
    *) printf '%s\n' "$current" ;;
  esac
}

reiniciar_plan_assets() {
  asset_releases=()
  asset_image_ids=()
  asset_sources=()
  asset_estimated_bytes=()
  asset_needs_extract=()
}

planificar_release_previa() {
  local release="$1" etiqueta="$2" faltante_msg="$3" image_id
  [ -n "$release" ] || return 0
  if image_id="$(frontend_image_id "$release" 2>/dev/null)"; then
    asset_plan_release "$release" "$image_id"
  else
    if [ "$etiqueta" = "rollback" ]; then
      log "assets: la imagen rollback $release no esta local; se conserva si ya fue importada"
    fi
    if [ -f "$ASSET_STORE_PATH/.manifests/$release.manifest" ]; then
      asset_helper verify "$ASSET_STORE_PATH" "$release" ||
        die "assets: el manifest $etiqueta existente no se pudo verificar"
    else
      die "$faltante_msg"
    fi
  fi
}

materializar_assets_planificados() {
  local capacidad_msg="$1" import_suffix="${2:-}" i
  [ "${#asset_releases[@]}" -gt 0 ] || return 0
  asset_helper capacity-bytes "$ASSET_STORE_PATH" "$DEPLOY_ASSET_MIN_FREE_BYTES" \
    "${asset_estimated_bytes[@]}" ||
    die "$capacidad_msg"
  for i in "${!asset_releases[@]}"; do
    asset_extract_release "$i"
  done
  for i in "${!asset_sources[@]}"; do
    [ -n "${asset_sources[$i]}" ] || continue
    asset_helper import "$ASSET_STORE_PATH" "${asset_releases[$i]}" \
      "${asset_image_ids[$i]}" "${asset_sources[$i]}" ||
      die "assets: importacion fallida para ${asset_releases[$i]}${import_suffix}"
    rm -rf -- "${asset_sources[$i]%/assets}"
    asset_sources[i]=""
  done
  for i in "${!asset_releases[@]}"; do
    asset_helper verify "$ASSET_STORE_PATH" "${asset_releases[$i]}" \
      "${asset_image_ids[$i]}" || die "assets: verificacion final fallida para ${asset_releases[$i]}"
  done
}

preparar_assets_release() {
  local candidate="$1" actual_release="$2" rollback_release="$3"
  local candidate_image live_frontends
  reiniciar_plan_assets
  ASSET_STORE_PATH="$(asset_helper prepare "$ASSET_STORE_PATH")" ||
    die "assets: no pude preparar el store persistente"
  export ASSET_STORE_PATH

  live_frontends="$(docker compose ps -q "$DEPLOY_FRONTEND_SERVICE")"
  if [ -n "$live_frontends" ]; then
    importar_frontends_activos
  else
    planificar_release_previa "$actual_release" "actual" \
      "assets: falta el frontend actual $actual_release y no hay assets ya importados"
  fi

  if [ -n "$rollback_release" ] && [ "$rollback_release" != "$actual_release" ]; then
    planificar_release_previa "$rollback_release" "rollback" \
      "assets: la imagen rollback $rollback_release no esta local y no hay assets ya importados; no se cambiara la app"
  fi

  candidate_image="$(frontend_image_id "$candidate")" ||
    die "assets: no esta disponible la imagen frontend candidata $candidate"
  asset_plan_release "$candidate" "$candidate_image"

  materializar_assets_planificados \
    "assets: capacidad insuficiente; no se migro ni recreo ningun servicio" \
    "; la app sigue sin cambios"
}

require_asset_release() {
  local release="$1"
  [ -n "$release" ] || return 0
  asset_helper verify "$ASSET_STORE_PATH" "$release" ||
    die "assets: falta un manifest valido para $release; no se activara el edge"
}

edge_fingerprint() {
  # shellcheck disable=SC2086
  { cat $DEPLOY_EDGE_CONF_FILES; printf '\nasset-store=%s\n' "$ASSET_STORE_PATH"; } | sha256sum | cut -d' ' -f1
}

borde_monta_assets_ro() {
  local id="$1" state restarting mounts src rw expected_src
  [ -n "$id" ] || return 1
  state="$(docker inspect -f '{{.State.Status}}' "$id" 2>/dev/null || true)"
  restarting="$(docker inspect -f '{{.State.Restarting}}' "$id" 2>/dev/null || true)"
  [ "$state" = "running" ] && [ "$restarting" != "true" ] || return 1
  mounts="$(docker inspect -f '{{range .Mounts}}{{if and (eq .Type "bind") (eq .Destination "/srv/shifty-assets/assets")}}{{.Source}}|{{.RW}}{{end}}{{end}}' "$id" 2>/dev/null || true)"
  [ -n "$mounts" ] || return 1
  src="${mounts%%|*}"
  rw="${mounts#*|}"
  [ -n "$src" ] && [ "$rw" = "false" ] || return 1
  expected_src="$(realpath -m -- "$ASSET_STORE_PATH/assets")"
  [ "$(realpath -m -- "$src")" = "$expected_src" ]
}

recrear_borde() {
  local servicio="$1" imagen deseada corriendo id huella anterior
  docker compose pull "$servicio" || die "edge: pull de $servicio fallo"
  imagen="$(compose_service_image "$servicio")"
  [ -n "$imagen" ] || die "edge: no pude resolver la imagen de $servicio"
  deseada="$(docker image inspect -f '{{.Id}}' "$imagen")" || die "edge: falta la imagen $imagen"
  id="$(docker compose ps -q "$servicio" | head -n 1)"
  corriendo=""
  [ -z "$id" ] || corriendo="$(docker inspect -f '{{.Image}}' "$id")"
  # El store tambien forma parte del fingerprint: cambiar su ruta requiere
  # recrear el bind mount, aunque el archivo nginx no haya cambiado.
  huella="$(edge_fingerprint)"
  anterior="$(cat "$estado_dir/edge-conf.sha256" 2>/dev/null || true)"
  if [ -z "$id" ] || [ "$deseada" != "$corriendo" ] || [ "$huella" != "$anterior" ] || ! borde_monta_assets_ro "$id"; then
    # nginx -t ANTES de recrear, en un contenedor efimero con la misma imagen
    # y los mismos montajes (2026-11-25): una config invalida deja el borde
    # actual sirviendo, no un borde nuevo que no arranca. `run` no publica los
    # puertos del servicio ni usa su container_name. Sin registrar la huella,
    # el proximo `edge` vuelve a intentarlo.
    docker compose run --rm --no-deps --entrypoint nginx -T "$servicio" -t ||
      die "edge: la configuracion candidata de $servicio no pasa nginx -t; no se recrea y el borde actual sigue sirviendo"
    log "edge: recreo $servicio (imagen ${corriendo:-ninguna} -> $deseada, config ${anterior:-sin registro} -> $huella)"
    docker compose up -d --no-deps --no-build --remove-orphans --force-recreate --wait \
      --wait-timeout "$DEPLOY_WAIT_TIMEOUT" "$servicio" ||
      die "edge: $servicio no quedo sano despues de recrearlo"
    id="$(docker compose ps -q "$servicio" | head -n 1)"
    if [ -z "$id" ] || ! borde_monta_assets_ro "$id"; then
      die "edge: $servicio recreado pero no monta $ASSET_STORE_PATH/assets en modo solo lectura"
    fi
  else
    log "edge: sin cambios de imagen, config ni asset store; solo reload"
  fi
  recargar_nginx || die "edge: nginx -t o reload fallo"
  escribir_estado "$estado_dir/edge-conf.sha256" "$huella" ||
    die "edge: no pude guardar la huella en $estado_dir/edge-conf.sha256"
}

verificar_borde_assets() {
  local candidate="$1" current="$2" rollback="$3" es_rollback="${4:-0}"
  require_asset_release "$current"
  require_asset_release "$candidate"
  [ -z "$rollback" ] || [ ! -f "$ASSET_STORE_PATH/.manifests/$rollback.manifest" ] ||
    require_asset_release "$rollback"

  local id
  id="$(docker compose ps -q "$DEPLOY_EDGE_SERVICE" | head -n 1)"
  if [ -z "$id" ] || ! borde_monta_assets_ro "$id"; then
    die "edge: el contenedor $DEPLOY_EDGE_SERVICE no esta corriendo o no monta $ASSET_STORE_PATH/assets en modo solo lectura; correr 'bash scripts/deploy.sh edge' primero"
  fi

  if [ "$es_rollback" != 1 ]; then
    local huella imagen deseada corriendo anterior
    huella="$(edge_fingerprint)"
    imagen="$(compose_service_image "$DEPLOY_EDGE_SERVICE")"
    [ -n "$imagen" ] || die "edge: no pude resolver la imagen de $DEPLOY_EDGE_SERVICE"
    deseada="$(docker image inspect -f '{{.Id}}' "$imagen" 2>/dev/null || true)"
    corriendo="$(docker inspect -f '{{.Image}}' "$id" 2>/dev/null || true)"
    anterior="$(cat "$estado_dir/edge-conf.sha256" 2>/dev/null || true)"
    if [ ! -s "$estado_dir/edge-conf.sha256" ] || [ "$huella" != "$anterior" ] || [ -z "$deseada" ] || [ "$deseada" != "$corriendo" ]; then
      die "edge: la configuracion, imagen o asset store del borde cambio (o falta .deploy/edge-conf.sha256); el deploy ordinario no recrea $DEPLOY_EDGE_SERVICE: correr 'bash scripts/deploy.sh edge' primero"
    fi
  fi
}

gc_assets_despues_de_exito() {
  local current="$1" previous
  previous="$(frontend_previous_release)"
  if [ -n "$previous" ] && [ ! -f "$ASSET_STORE_PATH/.manifests/$previous.manifest" ]; then
    previous=""
  fi
  local id image release active=""
  id="$(docker compose ps -q "$DEPLOY_FRONTEND_SERVICE" 2>/dev/null || true)"
  for id in $id; do
    image="$(docker inspect -f '{{.Config.Image}}' "$id" 2>/dev/null || true)"
    release="${image##*:}"
    [[ "$release" =~ ^[A-Za-z0-9_.-]+$ ]] && active="$active $release"
  done
  if ! DEPLOY_ASSET_PROTECTED_RELEASES="$DEPLOY_ASSET_PROTECTED_RELEASES $active" \
    asset_helper gc "$ASSET_STORE_PATH" "$current" "$previous" \
      "$((DEPLOY_ASSET_RETENTION_DAYS * 86400))" "$DEPLOY_ASSET_MIN_RELEASES"; then
    log "assets: GC non-blocking fallido; no se libera espacio automaticamente"
  fi
}

# --- compuerta --------------------------------------------------------------

seleccionar_asset_js_smoke() {
  local target_release="$1" retired_release="${2:-}"
  local target_manifest="$ASSET_STORE_PATH/.manifests/$target_release.manifest"
  local retired_manifest=""
  [ -f "$target_manifest" ] || {
    log "compuerta: falta manifest $target_manifest para smoke de asset JS"
    return 1
  }
  if [ -n "$retired_release" ] && [ "$retired_release" != "$target_release" ] &&
    [ -f "$ASSET_STORE_PATH/.manifests/$retired_release.manifest" ]; then
    retired_manifest="$ASSET_STORE_PATH/.manifests/$retired_release.manifest"
  fi
  local seleccion
  seleccion="$(awk -F '\t' -v retired="$retired_manifest" '
    BEGIN {
      if (retired != "") {
        in_files = 0
        while ((getline line < retired) > 0) {
          gsub(/\r$/, "", line)
          if (line == "files_begin") { in_files = 1; continue }
          if (!in_files) continue
          n = split(line, cols, "\t")
          if (n == 3) prev_paths[cols[3]] = 1
        }
        close(retired)
      }
      in_files = 0
      first = ""
      preferred = ""
    }
    {
      gsub(/\r$/, "", $0)
      if ($0 == "files_begin") { in_files = 1; next }
      if (!in_files || NF != 3) next
      if (tolower($3) ~ /\.(js|mjs)$/) {
        row = $1 "\t" $2 "\t" $3
        if (first == "") first = row
        if (retired != "" && !(($3) in prev_paths) && preferred == "") {
          preferred = row
        }
      }
    }
    END {
      if (preferred != "") print preferred
      else if (first != "") print first
    }
  ' "$target_manifest")"
  if [ -z "$seleccion" ]; then
    log "compuerta: no hay ningun asset .js/.mjs en $target_manifest"
    return 1
  fi
  printf '%s\n' "$seleccion"
}

verificar_asset_http() {
  local target_release="$1" retired_release="${2:-}"
  local seleccion expected_hash expected_size rel_path
  seleccion="$(seleccionar_asset_js_smoke "$target_release" "$retired_release")" || return 1
  IFS=$'\t' read -r expected_hash expected_size rel_path <<<"$seleccion"

  local base_src origin asset_url
  base_src="${DEPLOY_ASSET_SMOKE_BASE_URL:-}"
  [ -n "$base_src" ] || base_src="${DEPLOY_SMOKE_URLS%% *}"
  [ -n "$base_src" ] || base_src="${DEPLOY_HEALTH_URL%% *}"
  [ -n "$base_src" ] || base_src="${DOMAIN:+https://$DOMAIN}"
  origin="$(printf '%s' "$base_src" | sed -n 's#^\([A-Za-z][A-Za-z0-9+.-]*://[^/?#]*\).*#\1#p')"
  if [ -z "$origin" ]; then
    log "compuerta: no pude derivar origin para smoke HTTP de asset JS (base: ${base_src:-vacia})"
    return 1
  fi
  asset_url="$origin/assets/$rel_path"

  local tmp_body curl_out curl_rc=0 http_code ctype ctype_norm prefix actual_hash actual_size
  tmp_body="$(mktemp)" || {
    log "compuerta: no pude crear archivo temporal para smoke de $asset_url"
    return 1
  }
  if [ -n "${CURL_CA_BUNDLE:-}" ]; then
    curl_out="$(curl -sS --connect-timeout 3 -m 5 --cacert "$CURL_CA_BUNDLE" \
      -H 'Accept-Encoding: identity' -o "$tmp_body" \
      -w '%{http_code}\n%{content_type}\n' "$asset_url")" || curl_rc=$?
  else
    curl_out="$(curl -sS --connect-timeout 3 -m 5 \
      -H 'Accept-Encoding: identity' -o "$tmp_body" \
      -w '%{http_code}\n%{content_type}\n' "$asset_url")" || curl_rc=$?
  fi
  if [ "$curl_rc" -ne 0 ]; then
    rm -f -- "$tmp_body"
    log "compuerta: fallo HTTP al pedir asset JS $asset_url (curl exit $curl_rc)"
    return 1
  fi
  http_code="$(printf '%s\n' "$curl_out" | sed -n '1p' | tr -d '\r')"
  ctype="$(printf '%s\n' "$curl_out" | sed -n '2p' | tr -d '\r')"
  if [ "$http_code" != "200" ]; then
    rm -f -- "$tmp_body"
    log "compuerta: asset JS $asset_url devolvio HTTP $http_code (esperado 200)"
    return 1
  fi
  ctype_norm="$(printf '%s' "${ctype%%;*}" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if ! [[ "$ctype_norm" =~ ^(application|text)/(javascript|ecmascript|x-javascript)$ ]]; then
    rm -f -- "$tmp_body"
    log "compuerta: asset JS $asset_url devolvio Content-Type invalido: ${ctype:-vacio}"
    return 1
  fi
  prefix="$(head -c 256 "$tmp_body" | tr '\r\n\t' '   ' | tr -d '\0' | tr '[:upper:]' '[:lower:]' | sed 's/^ *//')"
  case "$prefix" in
    '<!doctype'* | '<html'*)
      rm -f -- "$tmp_body"
      log "compuerta: asset JS $asset_url devolvio HTML en vez de JavaScript"
      return 1 ;;
  esac
  actual_hash="$(sha256sum <"$tmp_body")"
  actual_hash="${actual_hash%% *}"
  actual_size="$(wc -c <"$tmp_body" | tr -d '[:space:]')"
  rm -f -- "$tmp_body"
  if [ "${actual_hash,,}" != "${expected_hash,,}" ] || [ "$actual_size" != "$expected_size" ]; then
    log "compuerta: asset JS $asset_url no coincide en hash/tamano (esperado ${expected_hash}:${expected_size}, obtenido ${actual_hash}:${actual_size})"
    return 1
  fi
  log "compuerta: asset JS $rel_path ok ($actual_size bytes)"
}

# Las alarmas de RabbitMQ se leen con rabbitmq_sin_alarmas (lib/common.sh,
# compartida con el chequeo horario de scripts/checks.sh): cualquier salida
# que no sea la de "sin alarmas" de 3.13.7 cuenta como alarma y la compuerta
# falla cerrada.
compuerta() {
  local target_release="${1:-}" retired_release="${2:-}"
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

  # Con la alarma de memoria o de disco activa, RabbitMQ bloquea a los
  # publicadores: el OTP y los jobs se quedan esperando aunque /ready conteste.
  local alarmas
  if ! alarmas="$(docker compose exec -T rabbitmq rabbitmq-diagnostics -q alarms --formatter json 2>&1)"; then
    log "compuerta: no se pudo consultar las alarmas de rabbitmq: $alarmas"
    return 1
  fi
  alarmas="$(printf '%s' "$alarmas" | tr -d '[:space:]')"
  if ! rabbitmq_sin_alarmas "$alarmas"; then
    log "compuerta: rabbitmq tiene alarmas activas (o una salida que no se entiende): $alarmas"
    return 1
  fi

  local lineas total errores
  lineas="$(docker compose logs --no-log-prefix --since "$DEPLOY_GATE_LOG_WINDOW" nginx 2>/dev/null || true)"
  total="$(printf '%s\n' "$lineas" | grep -c '"s":' || true)"
  errores="$(printf '%s\n' "$lineas" | grep -cE '"s":"?5[0-9]{2}' || true)"
  if [ "$errores" -ge "$DEPLOY_GATE_MIN_5XX" ] && [ $((errores * 1000)) -gt $((total * 5)) ]; then
    log "compuerta: 5xx $errores de $total en $DEPLOY_GATE_LOG_WINDOW (> 0,5 %)"
    return 1
  fi
  verificar_asset_http "$target_release" "$retired_release" || return 1
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
  local actual rollback target frontend_en_deploy=0
  case " $DEPLOY_SERVICES " in
    *" $DEPLOY_FRONTEND_SERVICE "*) frontend_en_deploy=1 ;;
  esac
  if ! actual="$(frontend_release_running)"; then
    if [ "$frontend_en_deploy" != 1 ]; then
      die "rollback: no hay una imagen frontend activa para conservar sus assets"
    fi
    actual=""
    if [ -s "$estado_dir/frontend-current" ]; then
      actual="$(head -n 1 "$estado_dir/frontend-current")"
    elif [ -s "$estado_dir/current" ]; then
      actual="$(head -n 1 "$estado_dir/current")"
    fi
    if [ -n "$actual" ] && [ ! -f "$ASSET_STORE_PATH/.manifests/$actual.manifest" ] &&
      ! frontend_image_id "$actual" >/dev/null 2>&1; then
      actual=""
    fi
  fi
  rollback="$(frontend_previous_release)"
  target="$(frontend_release_target "$version" "$actual")"
  if [ -n "$actual" ] && [ "$target" = "$actual" ]; then rollback="$actual"; fi
  preparar_assets_release "$target" "$actual" "$rollback"
  verificar_borde_assets "$target" "$actual" "$rollback" 1
  backend_gradual || return 1
  frontend_gradual || return 1
  resto_de_la_app || return 1
  recargar_nginx || return 1
  escribir_estado "$estado_dir/current" "$version" || return 1
  if [ -n "$target" ]; then
    escribir_estado "$estado_dir/frontend-current" "$target" || return 1
  fi
  compuerta "$target" "$actual" || return 1
  gc_assets_despues_de_exito "$target"
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

  local frontend_ids hay_registro=0
  frontend_ids="$(docker compose ps -q "$DEPLOY_FRONTEND_SERVICE")" ||
    die "assets: no pude consultar las replicas frontend actuales"
  if [ -s "$estado_dir/current" ] || [ -s "$estado_dir/previous" ] ||
    [ -s "$estado_dir/frontend-current" ] || [ -s "$estado_dir/frontend-previous" ]; then
    hay_registro=1
  fi

  # Un redeploy del sha que ya corre (re-correr un deploy que salio bien) no
  # toca previous: pisarlo con ese mismo sha perdia el destino del rollback
  # (2026-10-12, produccion: previous paso de a203ee54 a 494f5072).
  local anterior="" redeploy=0 rollback_protegido="" asset_actual=""
  if [ -n "$frontend_ids" ]; then
    anterior="$(version_en_curso)"
    if [ -n "$anterior" ] && [ "$anterior" = "$nueva" ]; then
      redeploy=1
      log "deploy: redeploy de la misma version $nueva; previous sigue en $(head -n 1 "$estado_dir/previous" 2>/dev/null || echo '(ninguna)')"
    fi
    if [ "$redeploy" = 1 ]; then
      rollback_protegido="$(frontend_previous_release)"
    elif [ -s "$estado_dir/frontend-current" ]; then
      local fc
      fc="$(head -n 1 "$estado_dir/frontend-current")"
      if [ "$fc" = "$anterior" ]; then
        rollback_protegido="$anterior"
      else
        rollback_protegido="$(frontend_previous_release)"
      fi
    else
      rollback_protegido="$anterior"
    fi
    asset_actual="$(frontend_release_running)" ||
      die "assets: no pude identificar la imagen frontend activa"
  else
    if [ "$hay_registro" = 1 ]; then
      die "assets: falta el frontend de un host con release registrado; no se omitiran assets actuales/rollback"
    fi
    case " $DEPLOY_SERVICES " in
      *" $DEPLOY_FRONTEND_SERVICE "*) ;;
      *) die "assets: primer deploy sin frontend; incluir $DEPLOY_FRONTEND_SERVICE en DEPLOY_SERVICES" ;;
    esac
    if [ -n "$(docker compose ps -q "$DEPLOY_BACKEND_SERVICE")" ]; then
      log "deploy: recuperando deploy inicial interrumpido (backend sin frontend ni estado registrado; sin previous)"
    fi
  fi
  log "deploy: ${anterior:-(sin version previa)} -> $nueva"

  export APP_VERSION="$nueva"
  # shellcheck disable=SC2086
  docker compose pull $DEPLOY_SERVICES || die "deploy: pull de $nueva fallo (la imagen esta publicada en GHCR? docker login ghcr.io?)"
  imagenes_locales || die "deploy: despues del pull faltan imagenes de $nueva; no se migra ni se recrea nada"

  local asset_candidato asset_rollback
  asset_candidato="$(frontend_release_target "$nueva" "$asset_actual")"
  [ -n "$asset_candidato" ] ||
    die "assets: no hay frontend actual ni candidato para servir desde el edge"
  asset_rollback="$rollback_protegido"
  preparar_assets_release "$asset_candidato" "$asset_actual" "$asset_rollback"
  verificar_borde_assets "$asset_candidato" "$asset_actual" "$asset_rollback" 0
  if [ "$redeploy" != 1 ] && [ -n "$anterior" ]; then
    escribir_estado "$estado_dir/previous" "$anterior"
  fi
  if [ "$redeploy" != 1 ] && [ -n "$asset_actual" ] && [ "$asset_candidato" != "$asset_actual" ]; then
    escribir_estado "$estado_dir/frontend-previous" "$asset_actual"
  fi
  migrar

  if ! backend_gradual; then
    alert "deploy $nueva: el backend nuevo no quedo sano" "Siguen sirviendo las replicas de ${anterior:-antes}. La migracion ya corrio (expand/contract)."
    exit 1
  fi
  # Un frontend nuevo que no queda sano cae aca: siguen la SPA vieja y el
  # backend nuevo, y el rollback vuelve a dejar las dos en la version anterior.
  # La alerta nombra la causa real (revision del PR #188: decia "compuerta").
  local causa="fallo la compuerta" codigo_front=0
  frontend_gradual || codigo_front=$?
  case "$codigo_front" in
    0)
      if resto_de_la_app && recargar_nginx && escribir_estado "$estado_dir/current" "$nueva" &&
        escribir_estado "$estado_dir/frontend-current" "$asset_candidato" &&
        compuerta "$asset_candidato" "$asset_actual"; then
        log "deploy: ok, corre $nueva"
        gc_assets_despues_de_exito "$asset_candidato"
        return 0
      fi
      ;;
    2) causa="el borde no recargo despues de renovar el frontend" ;;
    *) causa="el frontend nuevo no quedo sano" ;;
  esac

  # En un redeploy, antes ya corria esta misma version: no hay estado al que
  # volver. Ir a previous seria cambiar de version sin que nadie lo pidiera, y
  # un sha que ya paso la compuerta y ahora falla apunta al entorno (rabbitmq,
  # base, disco), no al codigo. Se avisa y previous queda intacto.
  if [ "$redeploy" = 1 ]; then
    alert "deploy $nueva: $causa en un redeploy de la misma version; sin rollback automatico" \
      "Sigue corriendo $nueva, como antes. Revisar el entorno (docs/DEPLOY_RUNBOOK.md); si el codigo es el problema, bash scripts/deploy.sh rollback (o make rollback) vuelve a $(head -n 1 "$estado_dir/previous" 2>/dev/null || echo '(sin previous)')."
    exit 1
  fi
  alert "deploy $nueva: $causa, rollback a ${anterior:-?}" "Ver docs/DEPLOY_RUNBOOK.md"
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
  [ -n "${APP_VERSION:-}" ] || die "edge: falta APP_VERSION o .deploy/current; pasar APP_VERSION=<sha> en un host vacio"
  configurar_asset_store
  ASSET_STORE_PATH="$(asset_helper prepare "$ASSET_STORE_PATH")" ||
    die "edge: no pude preparar el store persistente"
  export ASSET_STORE_PATH

  local previous running
  previous="$(frontend_previous_release)"
  running="$(docker compose ps -q "$DEPLOY_FRONTEND_SERVICE")" ||
    die "edge: no pude consultar las replicas frontend actuales"

  reiniciar_plan_assets

  # `.deploy/current` tracks the whole application. A backend-only deploy can
  # advance it while the frontend still serves an older image, so the running
  # frontend image tags below (plus frontend_previous_release) are the asset
  # releases of record for the edge.
  if [ -n "$running" ]; then
    importar_frontends_activos
    planificar_release_previa "$previous" "rollback" \
      "assets: la imagen previa $previous no esta local y no hay manifest ya importado para el borde"
    materializar_assets_planificados "assets: capacidad insuficiente para preparar el borde"
  else
    if [ -s "$estado_dir/current" ] || [ -s "$estado_dir/previous" ] ||
      [ -s "$estado_dir/frontend-current" ] || [ -s "$estado_dir/frontend-previous" ]; then
      die "edge: hay release registrado pero no hay frontend activo para verificar sus assets"
    fi
    log "edge: host sin releases registrados ni frontend activo; se prepara store vacio"
  fi

  recrear_borde "$DEPLOY_EDGE_SERVICE"
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
