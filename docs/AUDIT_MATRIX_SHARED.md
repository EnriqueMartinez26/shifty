# Matriz Compartida de Auditoria

## Regla

Cada fila debe indicar:

- `archivo`
- `paradigma`
- `estado`
- `consumidores`
- `accion`
- `owner`

## Matriz Inicial

| archivo | paradigma | estado | consumidores | accion | owner |
| --- | --- | --- | --- | --- | --- |
| `frontend/src/presentation/pages/Budget.tsx` | Clean Architecture | muerto | ninguno | borrar | frontend |
| `frontend/src/presentation/hooks/useBudgets.ts` | Clean Architecture | muerto | ninguno | borrar | frontend |
| `frontend/src/application/services/BudgetService.ts` | Clean Architecture | muerto | ninguno | borrar | frontend |
| `frontend/src/application/hooks/useService.ts` | Clean Architecture | duplicado | ninguno | borrar | frontend |
| `frontend/src/application/hooks/index.ts` | Clean Architecture | duplicado | ninguno | borrar | frontend |
| `frontend/src/presentation/hooks/index.ts` | Clean Architecture | duplicado | importado por ruta directa a archivos | archivar o borrar | frontend |
| `frontend/src/infrastructure/di/index.ts` | Clean Architecture | duplicado | ninguno | borrar | frontend |
| `frontend/src/lib/utils.ts` | Clean Architecture | duplicado | ninguno | borrar | frontend |
| `frontend/src/presentation/components/atoms/SkeuoCard.tsx` | Clean Architecture | muerto | ninguno | borrar | frontend |
| `frontend/src/presentation/components/atoms/UIAtoms.tsx` | Clean Architecture | muerto | ninguno | borrar | frontend |
| `frontend/src/assets/hero.png` | asset huérfano | muerto | ninguno | borrar | frontend |
| `backend/modules/budget/router.py` | 3NF / runtime routing | borrado | ninguno | borrar | backend |
| `backend/modules/budget/repository.py` | 3NF / runtime routing | borrado | router eliminado | borrar | backend |
| `backend/modules/budget/schemas.py` | 3NF / runtime routing | borrado | router eliminado | borrar | backend |
| `backend/modules/notifications/service.py` | notifications / helper legacy | borrado | ninguno | borrar | backend |
| `backend/modules/notifications/templates.py` | notifications / helper legacy | borrado | ninguno | borrar | backend |
| `backend/application/services/appointment_service.py` | application / appointment service legacy | borrado | ninguno | borrar | backend |
| `backend/application/dtos/appointment_dtos.py` | application / appointment DTOs legacy | borrado | ninguno | borrar | backend |
| `backend/core/events.py` | infraestructura / event bus legacy | borrado | ninguno | borrar | backend |
| `backend/core/tenant_guard.py` | tenancy helper legacy | borrado | ninguno | borrar | backend |
| `backend/scripts/check_db.py` | script manual legacy | borrado | ninguno | borrar | backend |
| `backend/pytest_output.txt` | artefacto de ejecución | borrado | ninguno | borrar | backend |
| `backend/server.py` | entrypoint legacy | borrado | ninguno | borrar | backend |
| `server.py` | entrypoint legacy | borrado | ninguno | borrar | backend |
| `backend/reset_db.py` | script manual legacy | borrado | ninguno | borrar | backend |
| `backend/refactor_service.py` | script manual legacy | borrado | ninguno | borrar | backend |
| `backend/fix_tests.py` | script manual legacy | borrado | ninguno | borrar | backend |
| `create_sqlite_dev_db.py` | script manual legacy | borrado | ninguno | borrar | backend |
| `docs/archive/data-model/ANALISIS_3NF.md` | 3NF | archivado | referencia documental | archivar | backend |
| `docs/archive/data-model/DB_DESIGN_3NF_RLS_AUDIT.md` | 3NF / RLS | archivado | referencia documental | archivar | backend |
| `docs/DOCUMENTACION_TURNERO.md` | producto / copy | sesgado | equipo | refactorizar | shared |
| `docs/SETUP_GUIDE.md` | setup | drift probable | equipo | refactorizar | shared |
| `frontend/scripts/verify-clean-architecture.ts` | guardrail | vivo | CI / developers | conservar | frontend |
| `backend/scripts/seed_simulation.py` | datos / seed | vivo pero largo | scripts | refactorizar | backend |
