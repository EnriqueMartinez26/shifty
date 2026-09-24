#!/usr/bin/env bash
# Latencia y 5xx de los ultimos 5 minutos (F5-01). Lo corre cron cada 5
# minutos (deploy/cron/shifty-latency), como root.
#
# Lee el access log JSON de nginx (`docker compose logs`, asi no depende del
# container_name) y lo pasa por backend/scripts/latency_report.py (solo
# stdlib, con el python3 del host). La tabla queda en el log del cron; si una
# ruta pasa el umbral (p95 > 500 ms o 5xx > 0,1 %) avisa, con silencio de 30
# minutos para no mandar un mail cada 5.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${LATENCY_WINDOW:=5m}"
: "${LATENCY_P95_MS:=500}"
: "${LATENCY_MAX_5XX_RATE:=0.001}"
: "${LATENCY_MIN_SAMPLES:=20}"
: "${LATENCY_PYTHON:=python3}"

cd "$SHIFTY_DIR"
usar_version_en_curso
temporal="$(mktemp -d)"
trap 'rm -rf -- "$temporal"' EXIT

if ! docker compose logs --no-log-prefix --since "$LATENCY_WINDOW" nginx \
  >"$temporal/nginx.log" 2>/dev/null; then
  alert "latencia: no se pudieron leer los logs de nginx" "" latencia-logs 30
  exit 1
fi

codigo=0
"$LATENCY_PYTHON" backend/scripts/latency_report.py \
  --p95-ms "$LATENCY_P95_MS" \
  --max-5xx-rate "$LATENCY_MAX_5XX_RATE" \
  --min-samples "$LATENCY_MIN_SAMPLES" \
  <"$temporal/nginx.log" >"$temporal/reporte.txt" || codigo=$?
cat "$temporal/reporte.txt"

case "$codigo" in
  0) ;;
  1)
    alert "latencia o errores sobre el umbral en los ultimos $LATENCY_WINDOW" \
      "$(grep '^ALERTA' "$temporal/reporte.txt" || true)" latencia 30
    ;;
  *)
    alert "latencia: el reporte fallo (codigo $codigo)" "" latencia-reporte 60
    ;;
esac
exit "$codigo"
