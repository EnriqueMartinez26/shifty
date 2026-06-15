# Avances Shifty - 2026-05-28

## Contexto

Este documento resume los avances implementados en Shifty sobre agenda, multi-tenant, seguridad, pagos, deuda, reportes, observabilidad y escalabilidad.

Referencia de push:

- Branch: `main`
- Commit: `b4278ee01595f58a1d1f143472bc7ecf42b96e57`
- URL: `https://github.com/EnriqueMartinez26/martinez-scienza/commit/b4278ee01595f58a1d1f143472bc7ecf42b96e57`

El objetivo fue evolucionar Shifty como SaaS multi-tenant simple y robusto para servicios profesionales, priorizando:

- simplicidad de uso
- aislamiento por tenant (store)
- estabilidad operativa
- crecimiento seguro

## Cambios implementados

## 1) Seguridad, auth y tenancy

- Registro publico deshabilitado por defecto (`ALLOW_PUBLIC_REGISTRATION=false`).
- Sesion con cookies seguras (access + refresh) y rotacion de refresh token.
- Revocacion de sesiones:
  - por tienda
  - por usuario
  - global (super admin)
- Hardening de middleware y contexto por request (`request_id`, `store_id`, `user_id`).
- Matriz de roles canonica:
  - `super_admin`
  - `store_admin`
  - `professional`
  - `receptionist`
  - `client`
- Compatibilidad legacy de roles:
  - `admin` -> `store_admin`
  - `staff` -> `professional`

## 2) Agenda y disponibilidad

- Disponibilidad consolidada con reglas de negocio sobre:
  - horarios de tienda
  - horarios de profesional
  - bloqueos
  - turnos existentes
  - reglas de anticipo
- Optimizacion de gaps para evitar huecos improductivos.
- Overbooking protegido por validacion de dominio + constraint en DB.
- Estado de turnos extendido (`pending`, `pending_payment`, `confirmed`, `completed`, `cancelled`, `absent`, `expired`).

## 3) Bloqueos de agenda

- CRUD de bloqueos para agenda interna.
- Soporte de bloques por lote con recurrencia (`none`, `daily`, `weekly`).
- Plantillas de bloqueos para uso rapido.
- Privacidad en canal publico: el cliente solo ve `No disponible`, nunca motivos internos.

## 4) Flujo publico y OTP

- Flujo publico de turnos sin registro obligatorio de cliente.
- OTP implementado para validacion de telefono (SMS/WhatsApp via proveedor configurable).
- Endpoints:
  - `POST /public/otp/request`
  - `POST /public/otp/verify`
- Feature flag `otp_booking` para exigir OTP antes de reservar en tiendas seleccionadas.

## 5) Pagos y senas

- Configuracion de seña por servicio.
- Integracion con Mercado Pago por tienda.
- Estados de pago consolidados:
  - `pending`
  - `approved`
  - `rejected`
  - `expired`
  - `refunded`
  - `manual_confirmed`
- Webhook inbox idempotente + outbox para eventos internos.
- Nuevas capacidades:
  - devoluciones (`refund`)
  - resumen de conciliacion (`reconciliation summary`)
- Base preparada para proveedor adicional (`stripe`) a traves de `provider` en gateway config.

## 6) Deuda / fiado

- Ledger por cliente y tienda (`charge`, `payment`, `adjustment`, `refund`).
- Balance corrido y movimientos auditables.

## 7) Reportes

- Reportes por tienda y por profesional.
- Horas usadas por profesional y metricas operativas.
- Restriccion por roles para lectura y exportacion.

## 8) Observabilidad operativa

- Logs estructurados con contexto.
- Sentry habilitable por configuracion.
- Endpoints operativos:
  - `GET /ops/health/live`
  - `GET /ops/health/ready`
  - `GET /ops/slo`
- Umbrales SLO configurables para webhooks y outbox pendientes/fallidos.

## 9) Backups y restore drill

- Scripts:
  - `backend/scripts/backup_db.py`
  - `backend/scripts/restore_backup.py`
  - `backend/scripts/backup_restore_drill.py`
- Runbook operativo:
  - `docs/BACKUP_RESTORE_RUNBOOK.md`
- Pipeline mensual de evidencia:
  - `.github/workflows/monthly-backup-drill.yml`

## 10) Escalabilidad y performance

- Indices compuestos para agenda y busqueda.
- Colas Celery separadas (`payments`, `webhooks`, `notifications`, `reports`).
- Load tests base con Locust:
  - `backend/loadtests/locustfile.py`
- Playbook tecnico:
  - `docs/SCALING_AND_HARDENING_PLAYBOOK.md`
- Ejemplo de configuracion PgBouncer:
  - `deploy/pgbouncer/pgbouncer.ini.example`

## 11) Frontend

- Roles canonicamente normalizados tambien en UI.
- Proteccion por rol en rutas y sidebar.
- Login/flujo alineado a sesion por cookies.
- Code splitting por rutas (lazy loading en `App.tsx`).
- Personalizacion de tienda extendida en Settings (logo, portada, redes, WhatsApp, descripcion).

## Migraciones relevantes

- `c2d4e6f8a901_evolve_shifty_payments_auth_ledger.py`
- `d7f8a9b0c1d2_add_store_feature_flags.py`
- `e8a1b3c5d7f9_add_appointments_composite_indexes.py`
- `f3b2a1c4d5e6_add_otp_verifications_table.py`

## Validacion

- Backend: `77 passed` en test suite.
- Frontend: pendiente de validacion local en entorno con Node/pnpm disponible.

## Archivos de referencia para compartir

- `docs/ROLE_MATRIX.md`
- `docs/BACKUP_RESTORE_RUNBOOK.md`
- `docs/SCALING_AND_HARDENING_PLAYBOOK.md`
- `docs/archive/status/AVANCES_SHIFTY_2026-05-28.md`

## Estado final del avance

- Implementacion principal completada para esta etapa.
- Listo para despliegue por etapas con feature flags por tenant.
- Recomendado: activar primero en entorno interno y luego cohortes controladas.
