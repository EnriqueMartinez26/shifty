FROM node:26.5.0-trixie-slim AS build

WORKDIR /app

COPY package*.json .npmrc ./
RUN npm install --global npm@11.17.0 \
    && npm --version \
    && npm ci

COPY . .

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
ARG VITE_GA4_MEASUREMENT_ID=
ENV VITE_GA4_MEASUREMENT_ID=${VITE_GA4_MEASUREMENT_ID}
ARG VITE_SENTRY_DSN=
ARG VITE_SENTRY_ENVIRONMENT=production
ARG VITE_SENTRY_TRACES_SAMPLE_RATE=0.1
# Mismo origen: nginx reenvia /sentry-tunnel al proyecto del DSN (ver
# sentry-tunnel.sh). Sin DSN Sentry no se inicializa y el tunel no se usa.
ARG VITE_SENTRY_TUNNEL=/sentry-tunnel
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN}
ENV VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT}
ENV VITE_SENTRY_TRACES_SAMPLE_RATE=${VITE_SENTRY_TRACES_SAMPLE_RATE}
ENV VITE_SENTRY_TUNNEL=${VITE_SENTRY_TUNNEL}
# Contacto de Shifty (banner de renovacion y paginas legales). El repo es
# publico: los valores reales llegan de variables del repo en GitHub
# (build-images.yml), nunca de un archivo versionado. Vacio = esa linea no se
# muestra (docs/DEPLOY_RUNBOOK.md, seccion 2).
ARG VITE_SUPPORT_WHATSAPP=
ARG VITE_CONTACT_EMAIL=
ARG VITE_LEGAL_RESPONSABLES=
ENV VITE_SUPPORT_WHATSAPP=${VITE_SUPPORT_WHATSAPP}
ENV VITE_CONTACT_EMAIL=${VITE_CONTACT_EMAIL}
ENV VITE_LEGAL_RESPONSABLES=${VITE_LEGAL_RESPONSABLES}

RUN npm run build
RUN node configure-analytics-csp.mjs security-headers.conf /app/security-headers.generated.conf

# Mismo nginx que el borde (nginx/Dockerfile, docker-compose.prod.yml).
FROM nginx:1.30.5-alpine

# Paquetes de Alpine al ultimo parche de la rama, como nginx/Dockerfile.
# Cambia en cada build para que el upgrade de seguridad no salga de la cache
# (D-20260930-23). Va en esta etapa: la de build sigue cacheada.
ARG SECURITY_UPGRADE_STAMP=manual
RUN apk upgrade --no-cache

# El mismo DSN del build decide el tunel: sin DSN, /sentry-tunnel es un 404.
ARG VITE_SENTRY_DSN=
COPY sentry-tunnel.sh /tmp/sentry-tunnel.sh
RUN VITE_SENTRY_DSN="${VITE_SENTRY_DSN}" sh /tmp/sentry-tunnel.sh && rm /tmp/sentry-tunnel.sh

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/security-headers.generated.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
