FROM node:26.5.0-trixie-slim AS build

WORKDIR /app

COPY package*.json .npmrc ./
RUN npm install --global npm@11.17.0 \
    && npm --version \
    && npm ci

COPY . .

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
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

RUN npm run build

FROM nginx:1.27-alpine

# El mismo DSN del build decide el tunel: sin DSN, /sentry-tunnel es un 404.
ARG VITE_SENTRY_DSN=
COPY sentry-tunnel.sh /tmp/sentry-tunnel.sh
RUN VITE_SENTRY_DSN="${VITE_SENTRY_DSN}" sh /tmp/sentry-tunnel.sh && rm /tmp/sentry-tunnel.sh

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
