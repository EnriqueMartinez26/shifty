#!/bin/sh
# Genera en el build de la imagen la config de nginx del tunel de Sentry.
#
# Sin VITE_SENTRY_DSN (el default: Sentry apagado) /sentry-tunnel responde 404.
# Con DSN, /sentry-tunnel reenvia SOLO al endpoint de envelopes de ese proyecto:
# el destino queda fijo en el build, asi que no es un proxy abierto. Un DSN con
# otra forma corta el build (falla cerrado) en vez de generar algo raro.
#
# Escribe dos archivos:
#   /etc/nginx/sentry-tunnel-http.conf  contexto http (zona de rate limit)
#   /etc/nginx/sentry-tunnel.conf       contexto server (el location)
set -eu

HTTP_CONF=/etc/nginx/sentry-tunnel-http.conf
SERVER_CONF=/etc/nginx/sentry-tunnel.conf
CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
DSN="${VITE_SENTRY_DSN:-}"

if [ -z "$DSN" ]; then
    : > "$HTTP_CONF"
    printf 'location = /sentry-tunnel { return 404; }\n' > "$SERVER_CONF"
    exit 0
fi

if ! printf '%s' "$DSN" | grep -Eq '^https://[0-9a-f]+@[a-z0-9.-]+/[0-9]+$'; then
    echo "sentry-tunnel: VITE_SENTRY_DSN no tiene la forma https://<clave>@<host>/<proyecto>" >&2
    exit 1
fi

if [ ! -f "$CA_BUNDLE" ]; then
    echo "sentry-tunnel: falta $CA_BUNDLE para verificar el TLS de Sentry" >&2
    exit 1
fi

HOST_PATH="${DSN#*@}"
HOST="${HOST_PATH%%/*}"
PROJECT_ID="${DSN##*/}"

printf 'limit_req_zone $binary_remote_addr zone=sentry_tunnel:1m rate=10r/s;\n' > "$HTTP_CONF"

cat > "$SERVER_CONF" <<CONF
location = /sentry-tunnel {
    limit_except POST { deny all; }
    client_max_body_size 256k;
    limit_req zone=sentry_tunnel burst=20 nodelay;

    # Resolver de Docker y destino en variable: si el DNS de Sentry falla, cae
    # solo el tunel, no el arranque de nginx (y con el, toda la SPA).
    resolver 127.0.0.11 valid=300s;
    set \$sentry_envelope https://${HOST}/api/${PROJECT_ID}/envelope/;
    proxy_pass \$sentry_envelope;
    proxy_set_header Host ${HOST};
    proxy_ssl_server_name on;
    proxy_ssl_name ${HOST};
    proxy_ssl_verify on;
    proxy_ssl_trusted_certificate ${CA_BUNDLE};

    # Nada de la sesion ni de la IP del cliente viaja a Sentry.
    proxy_set_header Cookie "";
    proxy_set_header Authorization "";
    proxy_set_header X-Forwarded-For "";
    proxy_set_header X-Real-IP "";

    include /etc/nginx/security-headers.conf;
}
CONF
