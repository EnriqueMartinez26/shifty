#!/usr/bin/env bash
# Deploy hook de certbot (F0-12): copia el certificado renovado a
# nginx/certs del clon y recarga el borde. Lo llama certbot como root con
# RENEWED_LINEAGE=/etc/letsencrypt/live/<dominio>:
#
#   certbot certonly --webroot -w /opt/shifty/nginx/acme -d <dominio> \
#     --deploy-hook /opt/shifty/scripts/cert-deploy-hook.sh
#
# Se COPIA, no se enlaza: docker-compose.prod.yml monta ./nginx/certs en
# /etc/nginx/certs, y un symlink a /etc/letsencrypt/live apuntaria dentro del
# contenedor a una ruta que no existe. La recarga lleva APP_VERSION de
# .deploy/current: el compose de produccion la exige en todo comando.
set -euo pipefail

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

: "${RENEWED_LINEAGE:=}"
[ -n "$RENEWED_LINEAGE" ] || die "falta RENEWED_LINEAGE (lo define certbot al llamar al deploy hook)"

cd "$SHIFTY_DIR"
usar_version_en_curso
destino="$SHIFTY_DIR/nginx/certs"
mkdir -p "$destino"
# cp -L por si el linaje trae symlinks (los de live/ apuntan a archive/).
cp -L "$RENEWED_LINEAGE/fullchain.pem" "$destino/fullchain.pem.tmp"
cp -L "$RENEWED_LINEAGE/privkey.pem" "$destino/privkey.pem.tmp"
chmod 0644 "$destino/fullchain.pem.tmp"
chmod 0600 "$destino/privkey.pem.tmp"
mv -f "$destino/fullchain.pem.tmp" "$destino/fullchain.pem"
mv -f "$destino/privkey.pem.tmp" "$destino/privkey.pem"

if docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload; then
  log "certificado renovado y borde recargado"
else
  alert "certbot: el certificado se renovo pero nginx no recargo" \
    "Revisar: docker compose exec nginx nginx -t (con APP_VERSION=\$(cat .deploy/current))"
  exit 1
fi
