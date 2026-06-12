# Matriz Fina de Limpieza - 2026-06-01

## Estado

La alineacion limpia con `origin/main` ya existe en la branch `codex/shifty-origin-main-aligned`,
montada en el worktree local `.worktrees/origin-main-aligned`.

No se aplico esa alineacion sobre `main` porque el repo padre sigue con cambios no relacionados
fuera de `shifty/`. Forzarla ahi mezclaria historia valida con trabajo ajeno y subiria el riesgo.

## Circuito Operativo Actual

- Guia de trabajo para backend: [docs/PLAN_AUDITORIA_BACKEND.md](./PLAN_AUDITORIA_BACKEND.md)
- Guia de trabajo para frontend: [docs/PLAN_AUDITORIA_AMIGO.md](./PLAN_AUDITORIA_AMIGO.md)
- Matriz compartida de decisiones: [docs/AUDIT_MATRIX_SHARED.md](./AUDIT_MATRIX_SHARED.md)
- Regla vigente: borrar solo cuando no haya consumidores en runtime, tests, migraciones, scripts o docs operativas

## Criterio

Estados posibles:

- `borrar`: eliminar del repo si reaparece o si ya no aporta ni como historial
- `archivar`: conservar fuera del camino del runtime, sin tratarlo como fuente vigente
- `conservar`: mantener como parte activa del producto, setup o soporte operativo
- `refactorizar`: mantener, pero cambiar implementacion o estructura por deuda tecnica o duplicacion

Objetivo:

- reducir ruido y duplicacion
- mantener intacta la estructura activa
- no danar funcionalidad ni contratos

## Matriz Archivo por Archivo

| Archivo | Accion | Motivo | Siguiente paso |
| --- | --- | --- | --- |
| `.worktrees/` | conservar | worktree auxiliar valido para alinear historia sin tocar `main` sucio | mantenerlo ignorado por git |
| `docs/archive/status/AVANCES_SHIFTY_2026-05-28.md` | archivar | referencia de alcance entregado | dejar archivado |
| `docs/archive/status/AVANCES_MATRIX_2026-05-30.md` | archivar | estado de integracion contra avances | dejar archivado |
| `docs/MULTI_VERTICAL_AUDIT_AND_STRATEGY_2026-06-01.md` | conservar | hoja de ruta multi-rubro vigente | usar como base de implementacion |
| `docs/ROLE_MATRIX.md` | conservar | documento operativo vigente | mantener alineado a roles reales |
| `docs/BACKUP_RESTORE_RUNBOOK.md` | conservar | runbook operativo vigente | mantener |
| `docs/SCALING_AND_HARDENING_PLAYBOOK.md` | conservar | soporte tecnico vigente | mantener |
| `docs/SETUP_GUIDE.md` | refactorizar | probable drift respecto al setup real actual | revisar comandos, puertos, auth y dependencias |
| `docs/DOCUMENTACION_TURNERO.md` | refactorizar | sigue sesgado a salones y barberias | reescribir como turnero multi-rubro |
| `docs/archive/data-model/ANALISIS_3NF.md` | archivar | material historico de analisis, no runtime | dejar archivado |
| `docs/archive/data-model/DB_DESIGN_3NF_RLS_AUDIT.md` | archivar | auditoria de diseno historica | dejar archivado |
| `docs/archive/data-model/normalizacion_3fn.md` | archivar | duplicado conceptual del analisis 3NF | dejar archivado |
| `docs/archive/plans/POLISH_PLAN.md` | archivar | backlog de polish viejo, no estado vigente | dejar archivado |
| `docs/archive/audits/PROJECT_AUDIT_2026-05-18.md` | archivar | snapshot de auditoria pasada | dejar archivado |
| `docs/archive/plans/SANITIZATION_PLAN.md` | archivar | plan tecnico historico | dejar archivado |
| `docs/fetch-standar.md` | conservar | referencia util de especificacion | mover opcionalmente a `docs/reference/` |
| `docs/archive/refactoring/*.md` | conservar | historial de migracion ya archivado | no reactivar como fuente de verdad |
| `docs/archive/poo-elevation/*.md` | conservar | referencia historica ya archivada | no usar como estado actual |
| `POO_ELEVATION/code_ServiceContainer.ts` | archivar | ejemplo historico que no participa del runtime | mover a `docs/archive/poo-elevation/` |
| `REFACTORING_DOCS/` | archivar | namespace legacy ya reemplazado por `docs/archive/refactoring/` | no volver a poblarlo |
| `frontend/src/presentation/hooks/useDashboard.ts` | refactorizar | hook de UI usando `apiClient` directo | pasar por `application/service` o repositorio dedicado |
| `frontend/src/presentation/hooks/useStores.ts` | refactorizar | acceso HTTP directo y contrato mutable | encapsular en servicio o store gateway |
| `frontend/src/presentation/hooks/usePayments.ts` | refactorizar | acceso HTTP directo a pagos | introducir servicio de pagos en application |
| `frontend/src/presentation/hooks/useChangePassword.ts` | refactorizar | acceso HTTP directo a auth | mover a servicio de auth |
| `frontend/src/presentation/hooks/useBudgets.ts` | refactorizar | acceso HTTP directo a budgets | encapsular en servicio |
| `frontend/src/presentation/hooks/useManagedUsers.ts` | refactorizar | mezcla gestion UI y HTTP | unificar con servicio o repositorio de usuarios |
| `frontend/src/presentation/hooks/useLedger.ts` | refactorizar | acceso HTTP directo a ledger | encapsular en servicio |
| `frontend/src/presentation/hooks/usePublic.ts` | refactorizar | acceso HTTP directo a booking publico | extraer gateway publico consistente |
| `frontend/src/presentation/hooks/useReports.ts` | refactorizar | acceso HTTP directo a reportes | encapsular en servicio |
| `frontend/src/presentation/hooks/useAppointmentBlocks.ts` | refactorizar | acceso HTTP directo a blocks | encapsular en servicio |
| `frontend/src/presentation/containers/UserManagementContainer.tsx` | refactorizar | instancia servicios y repositorios manualmente | inyectar via composition root o custom hook |
| `frontend/src/presentation/containers/StaffManagementContainer.tsx` | refactorizar | instancia servicios y repositorios manualmente | mismo criterio que users |
| `frontend/src/presentation/containers/ServiceManagementContainer.tsx` | refactorizar | instancia servicios y repositorios manualmente | mismo criterio que users |
| `frontend/src/presentation/containers/CalendarContainer.tsx` | refactorizar | mezcla orchestration UI, DI manual y HTTP indirecto | separar casos de uso y adapters |
| `frontend/src/presentation/components/organisms/booking/BookingStepService.tsx` | refactorizar | consulta HTTP desde componente | mover a hook o servicio |
| `frontend/src/presentation/components/organisms/booking/BookingStepStaff.tsx` | refactorizar | consulta HTTP desde componente | mover a hook o servicio |
| `frontend/src/presentation/components/organisms/booking/BookingStepDateTime.tsx` | refactorizar | consulta HTTP desde componente | mover a hook o servicio |
| `frontend/src/presentation/components/organisms/StaffFormModal.tsx` | refactorizar | crea servicio y repositorio dentro del componente | mover a hook o DI central |
| `frontend/src/presentation/components/atoms/SkeuoCard.tsx` | borrar | componente atomico sin consumidores | eliminado |
| `frontend/src/presentation/components/atoms/UIAtoms.tsx` | borrar | utileria atomica sin consumidores | eliminado |
| `frontend/src/assets/hero.png` | borrar | asset huérfano | eliminado |
| `frontend/src/presentation/pages/Login.tsx` | refactorizar | auth page todavia usa `apiClient` directo | extraer hook `useLogin` |
| `frontend/src/presentation/pages/Register.tsx` | refactorizar | register page usa `apiClient` directo | extraer hook `useRegisterBusiness` |
| `frontend/src/presentation/pages/ForgotPassword.tsx` | refactorizar | auth page con HTTP directo | extraer hook |
| `frontend/src/presentation/pages/ResetPassword.tsx` | refactorizar | auth page con HTTP directo | extraer hook |
| `frontend/scripts/verify-clean-architecture.ts` | conservar | guardrail estructural vigente | mantener y extender chequeos |
| `frontend/src/presentation/lib/businessLabels.ts` | conservar | base de multi-rubro actual | extender con labels y presets por vertical |
| `backend/scripts/seed_simulation.py` | refactorizar | seed util pero muy largo y sesgado a belleza | dividir por factories o fixtures y agregar seed multi-rubro |
| `backend/scripts/backup_db.py` | conservar | utilidad operativa vigente | mantener |
| `backend/scripts/restore_backup.py` | conservar | utilidad operativa vigente | mantener |
| `backend/scripts/backup_restore_drill.py` | conservar | utilidad operativa vigente | mantener |
| `backend/modules/notifications/service.py` | borrar | archivo vacio sin consumidores | eliminado |
| `backend/modules/notifications/templates.py` | borrar | archivo vacio sin consumidores | eliminado |
| `backend/test_uow.py` | conservar | test activo en `origin/main` | no volver a borrarlo |
| `backend/loadtests/locustfile.py` | conservar | soporte de performance vigente | mantener |
| `backend/loadtests/README.md` | conservar | documentacion de load test vigente | mantener |
| `backend/core/business_types.py` | conservar | pieza central de multi-rubro | mantener y expandir |
| `backend/modules/stores/model.py` | refactorizar | `business_type` hoy vive en `theme_config` por compatibilidad | migrar luego a columna real si se estabiliza |
| `backend/modules/stores/schemas.py` | conservar | contrato actual de store | mantener mientras se expande vertical config |
| `backend/modules/public/schemas.py` | refactorizar | booking publico aun tiene formulario fijo | extender a `custom_fields` e intake dinamico |
| `backend/modules/public/router.py` | refactorizar | flujo publico multi-rubro parcial, pero sin intake configurable | extender una vez exista schema dinamico |
| `backend/modules/payments/*` | conservar | modulo funcional y vigente | mantener |
| `backend/modules/ledger/*` | conservar | modulo funcional y vigente | mantener |
| `backend/modules/appointment_blocks/*` | conservar | modulo funcional y vigente | mantener |
| `backend/modules/otp/*` | conservar | modulo funcional y vigente | mantener |
| `backend/modules/ops/*` | conservar | soporte operativo vigente | mantener |
| `deploy/pgbouncer/pgbouncer.ini.example` | conservar | referencia de despliegue vigente | mantener |
| `.github/workflows/monthly-backup-drill.yml` | conservar | evidencia operativa vigente | mantener |

## Prioridad de Segunda Pasada

### P1

- `frontend/src/presentation/hooks/use*.ts` que usan `apiClient` directo
- `frontend/src/presentation/containers/*ManagementContainer.tsx`
- `frontend/src/presentation/components/organisms/booking/BookingStep*.tsx`
- `frontend/src/presentation/components/organisms/StaffFormModal.tsx`
- `docs/DOCUMENTACION_TURNERO.md`
- `docs/SETUP_GUIDE.md`

### P2

- `backend/scripts/seed_simulation.py`
- `backend/modules/public/schemas.py`
- `backend/modules/public/router.py`
- `backend/modules/stores/model.py`

### P3

- `docs/archive/data-model/ANALISIS_3NF.md`
- `docs/archive/data-model/DB_DESIGN_3NF_RLS_AUDIT.md`
- `docs/archive/data-model/normalizacion_3fn.md`
- `docs/archive/plans/POLISH_PLAN.md`
- `docs/archive/audits/PROJECT_AUDIT_2026-05-18.md`
- `docs/archive/plans/SANITIZATION_PLAN.md`
- `POO_ELEVATION/code_ServiceContainer.ts`

## Regla de Ejecucion

Cada archivo marcado como `refactorizar` o `archivar` debe pasar por esta secuencia:

1. mover o cambiar un grupo pequeno
2. correr `frontend tsc`, `frontend jest`, `backend pytest` relevante
3. confirmar que no reaparecen imports o paths legacy
4. commitear por bloque pequeno
