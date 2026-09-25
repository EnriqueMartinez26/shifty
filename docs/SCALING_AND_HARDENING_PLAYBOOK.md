# Scaling And Hardening Playbook

## Objetivo

Escalar Shifty de forma segura para crecimiento multi-tenant sin degradar agenda ni pagos.

## 1) Edge y red

- Frontend + API detras de Cloudflare.
- WAF activo con reglas administradas y bloqueo de bots agresivos.
- TLS estricto (`Full (strict)`), HSTS y rate limits por IP/ruta.
- `TRUST_PROXY_HEADERS=true` solo si el trafico pasa por proxy confiable.

## 2) Sesiones y secretos

- Access token corto + refresh rotativo en cookie `HttpOnly`.
- Revocacion de sesiones por tienda, por usuario y global ante incidente.
- Rotacion trimestral de:
  - `SECRET_KEY`
  - `FIELD_ENCRYPTION_KEY`
  - credenciales de pasarelas por tienda
- Playbook de incidente: revocacion masiva + rotacion de llaves + invalidacion de refresh sessions.

## 3) PostgreSQL y pooling

- **Sin PgBouncer** (descartado en `plan-correccion-rendimiento.md` §8): en
  modo `transaction` rompe el advisory lock de sesion que usan los jobs de
  Celery (el contexto de RLS no es el problema: `set_config(..., true)` es
  local a la transaccion, `core/database.py`).
  `deploy/pgbouncer/pgbouncer.ini.example` es un resto de esa recomendacion y
  no se usa.
- El pool lo da SQLAlchemy en cada proceso: con 3 replicas del backend de un
  proceso cada una (F0-04), las conexiones son `3 x (pool_size + max_overflow)`
  mas los workers de Celery; `max_connections` de Postgres se dimensiona con
  esa cuenta (F0-14: 100-150).
- Camino cuando haya mas de un host: Postgres administrado (plan §7, decision
  3), no un pooler delante del de hoy.
- Indices compuestos de agenda ya aplicados:
  - `store_id + staff_id + starts_at`
  - `store_id + status + starts_at`
  - `store_id + client_phone`

## 4) Reportes pesados

- Separar lecturas pesadas con replica de solo lectura o vistas materializadas.
- Mantener agenda/escrituras en nodo primario.
- Exportaciones por rango limitado y tareas asincronas en cola `reports`.

## 5) Workers y colas

- Colas separadas:
  - `payments`
  - `webhooks`
  - `notifications`
  - `reports`
- Alertar por backlog en `webhook_inbox` y `outbox_messages`.

## 6) SLO operativos recomendados

Umbrales de alerta del plan (§6) y donde se miden: `docs/DEPLOY_RUNBOOK.md` §8.

- p95 < 500 ms por ruta y 5xx < 0,1 % (`scripts/latency-check.sh`)
- Error rate API < 1%
- Webhooks pendientes bajo umbral
- Outbox pendiente bajo umbral
- Restore drill mensual exitoso

## 7) Pruebas de carga

- Escenarios Locust en `backend/loadtests/locustfile.py`:
  - disponibilidad publica
  - reservas publicas
  - webhooks
- Ejecutar antes de cada release mayor y guardar resultados.
