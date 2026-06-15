# Matriz de Estado - Avances Shifty 2026-05-28

## Criterio

Esta matriz separa:

- alcance funcional y documental descrito en `docs/archive/status/AVANCES_SHIFTY_2026-05-28.md`
- estado real de integracion estructural, validacion y git en el workspace local al `2026-05-30`

Actualizacion puntual de esta matriz: `2026-06-02`.

Estados usados:

- `implementado`: presente en el workspace actual y validado por codigo/tests o por presencia de archivos operativos
- `parcial`: existe, pero su validacion o cierre operativo no esta completo
- `pendiente`: no esta cerrado en el workspace actual

## Matriz Avances -> Estado

| Item | Estado | Evidencia | Observaciones |
| --- | --- | --- | --- |
| 1. Seguridad, auth y tenancy | implementado | `backend/modules/auth/*`, `backend/core/security.py`, `backend/core/roles.py`, `backend/core/tenant_guard.py`, `frontend/src/presentation/context/AuthContext.tsx` | Incluye roles canonicos, compatibilidad legacy, cookies/sesion y guards de UI |
| 2. Agenda y disponibilidad | implementado | `backend/modules/appointments/*`, `backend/modules/public/router.py`, `frontend/src/presentation/containers/CalendarContainer.tsx`, `frontend/src/domain/value-objects/BookingStatus.ts` | Estados extendidos y disponibilidad consolidada activos |
| 3. Bloqueos de agenda | implementado | `backend/modules/appointment_blocks/*`, `frontend/src/presentation/hooks/useAppointmentBlocks.ts` | Se preserva privacidad en canal publico |
| 4. Flujo publico y OTP | parcial | `backend/modules/otp/*`, `backend/modules/public/*`, `frontend/src/presentation/hooks/usePublic.ts`, `frontend/src/presentation/pages/PublicBooking.tsx` | El flujo existe, pero el frontend sigue obligando email y el booking no permite "cualquier profesional" |
| 5. Pagos y senas | parcial | `backend/modules/payments/*`, `frontend/src/presentation/hooks/usePayments.ts`, `frontend/src/presentation/pages/Payments.tsx` | Hay base de pagos/webhook/refund, pero falta cerrar la logica real: sena a nivel `Service`, confirmacion del turno recien al aprobarse el cobro y alineacion de confirmacion manual |
| 6. Deuda / fiado | implementado | `backend/modules/ledger/*`, `frontend/src/presentation/hooks/useLedger.ts`, `frontend/src/presentation/pages/Ledger.tsx` | Ledger por cliente operativo |
| 7. Reportes | parcial | `backend/modules/reports/*`, `frontend/src/presentation/hooks/useReports.ts`, `frontend/src/presentation/pages/Reports.tsx` | Existe resumen general, pero `/reports/professionals` no esta cerrado en backend y tampoco esta habilitado el acceso de cada profesional a sus propios reportes |
| 8. Observabilidad operativa | implementado | `backend/modules/ops/router.py`, `backend/core/logging_config.py`, `backend/core/request_context.py` | Sin UI dedicada; corresponde a backend/ops |
| 9. Backups y restore drill | implementado | `.github/workflows/monthly-backup-drill.yml`, `backend/scripts/backup_db.py`, `backend/scripts/restore_backup.py`, `backend/scripts/backup_restore_drill.py`, `docs/BACKUP_RESTORE_RUNBOOK.md` | Traido desde `origin/main` al workspace local |
| 10. Escalabilidad y performance | implementado | `backend/loadtests/README.md`, `backend/loadtests/locustfile.py`, `deploy/pgbouncer/pgbouncer.ini.example`, `docs/SCALING_AND_HARDENING_PLAYBOOK.md`, migraciones de indices | Traido desde `origin/main` al workspace local |
| 11. Frontend | implementado | `frontend/src/presentation/*`, `frontend/scripts/verify-clean-architecture.ts`, `frontend/src/App.tsx` | Se elimino coexistencia funcional de `pages/layouts/features` como capa activa |

## Estado de integracion que no estaba dentro de "Avances"

| Item | Estado | Evidencia | Observaciones |
| --- | --- | --- | --- |
| Migracion estructural completa del frontend | implementado | `frontend/src/presentation/pages`, `frontend/src/presentation/layouts`, `frontend/src/presentation/context`, hooks migrados, `verify-clean-architecture.ts` pasando | La estructura activa queda alineada a `presentation/application/infrastructure/domain` |
| Validacion automatizada frontend | implementado | `npm.cmd run lint`, `node scripts/verify-clean-architecture.ts`, `npm.cmd test -- --runInBand` | `18/18` suites, `95/95` tests |
| Validacion automatizada backend critica | implementado | `backend/tests/integration/test_feature_flags_finance_and_public_privacy.py`, `backend/tests/integration/test_auth.py`, `py_compile` de scripts/migraciones | `7 passed` y `4 passed` |
| Validacion visual end-to-end exhaustiva | parcial | Smoke funcional disponible via app en ejecucion; automatizacion visual no quedo cerrada | El runtime del browser automation fallo en este entorno (`node_repl kernel exited unexpectedly`) |
| Alineacion total de historia git con `origin/main` | pendiente | `main...origin/main [behind 2]` | El contenido ya esta integrado en workspace, pero no se hizo merge/cherry-pick limpio sobre un worktree sin cambios |

## Conclusiones operativas

- Alcance de `docs/archive/status/AVANCES_SHIFTY_2026-05-28.md`: no conviene leerlo como `100% implementado`; pagos, reportes y booking publico siguen parciales en el workspace actual.
- Estructura del frontend pedida: `100% implementada` y validada por el verificador.
- Validacion automatizada: `implementada`.
- Historia git limpia sobre `origin/main`: `pendiente`.
- Validacion visual exhaustiva navegador por navegador: `parcial`.

## Repriorizacion sugerida

El pendiente real ya no es "sumar mas features". Lo critico es cerrar mejor:

1. `/reports/professionals` y acceso de profesionales a sus propios reportes
2. reserva publica sin email obligatorio y con opcion de "cualquier profesional"
3. reserva + pago + webhook + confirmacion manual bajo una misma logica de confirmacion
4. calendario con vistas lista/semana/mes y mejor orden de ausencias/bloqueos
5. multi-rubro configurable por `business_type`, y recien despues promociones por tienda, waiting list y soporte si el negocio lo pide

## Cierre recomendado

Para cerrar el `100%` restante sin comprometer cambios locales ajenos:

1. crear un branch limpio desde `origin/main`
2. portar solo los cambios de `shifty/` ya validados
3. cerrar primero reportes, booking, pagos y calendario antes de abrir backlog periferico
4. correr smoke visual guiado sobre login, dashboard, settings, calendar, payments, ledger y booking publico
5. recien entonces fusionar o reemplazar la rama de trabajo actual
