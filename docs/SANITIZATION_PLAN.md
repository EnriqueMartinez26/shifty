# 🛡️ Plan de Sanitización Sentinel-Powered: Shifty v2

Este plan integra las **Restricciones Técnicas de Sentinel** para asegurar que el sistema sea 100% consistente con la documentación oficial.

## 1. Integridad de Datos y 3NF (Sentinel 1.1 - 1.4)
Para cumplir con la normalización y evitar datos huérfanos.
- [ ] **Property Enforcement**: Asegurar que `ends_at` sea estrictamente una `@property` calculada (como indica Sentinel 5.1) y no se guarde en la DB.
- [ ] **DB Constraints**: Verificar en el código de SQLAlchemy que existan los `UniqueConstraint` críticos:
    - `appointments.(staff_id, starts_at)`
    - `appointments.idempotency_key`
- [ ] **Soft Deletes**: Estandarizar que en `Appointments` se use el estado `cancelled` y `cancelled_at` en lugar de borrar registros (Sentinel 2.6).

## 2. Motor de Disponibilidad (Sentinel 2.1 - 2.2)
Refactorizar la lógica de `AvailabilityService` para usar la fórmula de detección oficial.
- [ ] **Detección de Solapamiento**: Implementar la lógica: `event1.start < event2.end AND event1.end > event2.start` en todas las consultas de validación.
- [ ] **Buffer & Notice**: Asegurar que el cálculo de slots aplique estrictamente `min_booking_notice_hours` y `buffer_minutes` desde la configuración del `Store`.

## 3. Máquina de Estados (Sentinel 2.5)
- [ ] **ValidTransitions**: Refactorizar el método `apply_status_transition` en el modelo `Appointment` para que coincida exactamente con el grafo de Sentinel (ej: `pending` solo puede ir a `confirmed` o `cancelled`).

## 4. Consistencia Temporal (Core Hardening)
- [ ] **UTC Oracle**: Seguir con la implementación de `now_utc()` para asegurar que las comparaciones en `cancellation_hours` y `min_booking_notice_hours` no fallen por desfases de servidor (Sentinel 2.3 - 2.4).
- [ ] **TZ-Aware**: Garantizar que todas las columnas de tiempo en Postgres sean `TIMESTAMP WITH TIME ZONE` para preservar la integridad regional.

## 5. Protocolo de Errores y Tipado (Sentinel-UI Sync)
- [ ] **Standard Exceptions**: Implementar las clases `BadRequestError`, `ForbiddenError` y `ConflictError` (409) mencionadas en Sentinel para que el frontend pueda reaccionar con lógica específica a cada una.
- [ ] **Shadowing Fix**: Renombrar parámetros en routers para evitar colisiones con tipos nativos (ej: `date_type`).

## Próximos Pasos Refactorizados:
1. **Fase 1 (Core)**: Finalizar `core/utils.py` y el handler de excepciones normalizado.
2. **Fase 2 (Models & Constraints)**: Actualizar los modelos de SQLAlchemy para incluir los `CheckConstraints` y `UniqueConstraints` de Sentinel.
3. **Fase 3 (Service Logic)**: Aplicar la fórmula de solapamiento en `AppointmentService`.
