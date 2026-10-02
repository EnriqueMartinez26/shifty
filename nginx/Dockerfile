# Parche fijo: `server ... resolve` en upstream exige nginx >= 1.27.3 y un tag
# flotante cacheado viejo en el servidor no arrancaria.
# Rama estable 1.30: la 1.27 dejo de publicarse en abril de 2025 (Alpine 3.21.3,
# OpenSSL 3.3.3 con CVE-2026-31789). El borde de produccion usa el mismo tag
# (docker-compose.prod.yml).
FROM nginx:1.30.5-alpine

# El tag fija nginx; los paquetes de Alpine se llevan al ultimo parche de la
# misma rama (3.24) en el build. El scan de CI (security-scan.yml) mira la
# imagen construida: un CVE de Alpine corregido despues de publicado el tag
# (2026-09-26: libexpat CVE-2026-93990, 2.8.5-r0) no espera al rebuild oficial.
# Cambia en cada build para que el upgrade de seguridad no salga de la cache
# (D-20260930-23).
ARG SECURITY_UPGRADE_STAMP=manual
RUN apk upgrade --no-cache

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
