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

- PgBouncer en modo `transaction` para reducir consumo de conexiones.
- Objetivo inicial:
  - `default_pool_size=30`
  - `max_client_conn=300`
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
