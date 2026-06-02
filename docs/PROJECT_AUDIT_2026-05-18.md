# Auditoria tecnica Shifty - 2026-05-18

## Estado ejecutivo

Shifty ya tiene una base valiosa para un SaaS de reservas: FastAPI, React, PostgreSQL, Redis, RLS documentado, portal publico, gestion de servicios/staff/usuarios, reportes y un esfuerzo real de arquitectura limpia. El estado actual no es todavia productivo: el refactor backend v2 dejo contratos desalineados entre migraciones, modelos y routers, y faltan validaciones operativas de base de datos con el entorno real.

El frontend quedo verificable: compila y pasa tests. El backend fue corregido a nivel estatico y de contrato, pero no pudo ejecutarse localmente porque esta maquina no tiene Python ni Docker disponibles en PATH.

## Correcciones aplicadas ahora

- Frontend: corregidos errores de TypeScript en Staff, imports muertos y render de `Email` value object.
- Frontend: `npm run build` pasa y `npm test` pasa 95/95 tests.
- Backend: `main.py` ahora monta el router real de `modules.appointments`, no el router placeholder con `STORE_ID = "store-1"`.
- Backend: restaurado contrato runtime de `AppointmentModel` con `client_id`, `ends_at`, `notes_staff`, timestamps de cancelacion/completado, relaciones y transiciones de estado.
- Backend: agregados defaults de ULID para modelos que se crean sin `id` (`User`, `Staff`, `Schedule`, `Appointment`, `AppointmentBlock`).
- Backend: restaurados campos de password reset en `UserModel` y migracion nueva para alinear la DB.
- Backend: idempotencia Redis ahora es iterativa, con espera maxima, error 409 controlado y liberacion de llave si falla la operacion.
- Backend: eliminado endpoint `/auth/debug-register`, logs manuales en archivo y filtrado de excepciones internas durante registro.
- Backend: StaffResponse vuelve a exponer `service_ids`, que es lo que consume el frontend.
- Backend: sincronizados contratos que el frontend ya consume: `GET /staff/{id}`, `PUT /staff/{id}`, filtros `email`/`role` en `GET /users/`, staff publico por `service_id` y disponibilidad publica inferida por `service_id`.
- Backend: el booking publico ahora acepta payloads sin `store_public_id` ni `idempotency_key` cuando puede inferir el store de forma segura desde `service_id`/`staff_id`; tambien devuelve `service_id`, `staff_id` y `notes` para el mapper actual del frontend.
- Frontend: el wizard publico de `/booking/:slug` ahora resuelve el store por slug y usa endpoints publicos (`/public/services`, `/public/staff`, `/public/availability`, `/public/appointments`) con `store_public_id` explicito.
- Seguridad: validacion de configuracion insegura en produccion y cabeceras defensivas basicas en Nginx.

## Implementacion SuperAdmin y billing SaaS

- SuperAdmin queda modelado como `role = "admin"` mas `is_global_admin = true`; no se agrego un cuarto rol local.
- `users.is_global_admin` vuelve a ser columna real, via modelo y migracion, y se expone en login/JWT, `/me` y `UserResponse`.
- Nuevo modulo `modules.superadmin` con API protegida por `get_current_global_admin` para listar/crear/editar tiendas, crear admins de tienda, listar/editar usuarios y promover/revocar SuperAdmins con proteccion contra revocar el ultimo SuperAdmin activo.
- Nuevo modulo `modules.billing` con modelos `Plan`, `StoreSubscription`, `SaaSCoupon` y `CouponRedemption` para descuentos comerciales SaaS, separados del flujo de reservas.
- Nueva migracion Alembic crea tablas de planes, suscripciones, cupones y canjes; agrega RLS para tablas globales y por store.
- Nuevo script `backend/scripts/bootstrap_superadmin.py` crea o promueve el primer SuperAdmin desde variables de entorno, sin endpoint publico de bootstrap.

## Endurecimiento ciberseguridad backend

- FastAPI ahora corta requests antes del parseo si el body supera `MAX_REQUEST_BODY_BYTES` (default 32 KB), evitando payloads gigantes tipo imagen/base64 que puedan inflar CPU, memoria, Redis o DB.
- Se bloquean escrituras con `Content-Type` no permitido; por defecto solo `application/json` y `application/x-www-form-urlencoded`, por lo que `multipart/form-data`, `image/*`, `application/octet-stream` y `text/plain` no entran al backend actual.
- Se agrego rate limiting Redis global por IP y limites especificos para `/auth/*`, reservas publicas y acciones publicas por telefono. En produccion falla cerrado si Redis no puede proteger.
- Auth aplica limites por IP + email/token en register, login, forgot-password, reset-password y change-password para reducir fuerza bruta y abuso de SMTP.
- Portal publico aplica limites por IP + telefono/turno en creacion, consulta, cancelacion y reprogramacion.
- Responses backend agregan headers defensivos: `nosniff`, `DENY` frame, referrer policy, permissions policy, COOP/CORP, no-store y CSP para endpoints API.
- Se agrego handler generico de excepciones para no filtrar stack traces ni detalles internos en errores 500.
- Schemas backend acotan IDs, slugs, passwords, notas, busquedas, listas de servicios, montos y prefijos de archivos; tambien rechazan `data:`, `javascript:`, `file:` y esquemas inseguros en URLs configurables.
- `/query` dejo de ser publico: ahora requiere admin autenticado y limita `query`, `namespace` y `k`.
- Nginx corta bodies a 32 KB, reduce buffers/timeouts de cliente y proxy, y mantiene buffering para no enviar streams grandes al backend.
- Docker compose limita PostgreSQL, Redis, backend y frontend a `127.0.0.1` en desarrollo; Nginx queda como entrada publica.
- Nueva migracion fuerza RLS (`FORCE ROW LEVEL SECURITY`) en tablas tenant y billing para que el owner de conexion no saltee aislamiento por accidente.

## Verificacion realizada

- `frontend`: `npm install`
- `frontend`: `npm run build` OK.
- `frontend`: `npm test` OK, 18 suites y 95 tests.
- `frontend`: luego de los tipos SuperAdmin, `npm run build` sigue OK y `npm test -- --runInBand --silent` sigue OK, 18 suites y 95 tests.
- `frontend`: `npm audit fix` sin `--force`; persisten 4 vulnerabilidades bajas en dependencias de Jest/jsdom que requieren upgrade mayor.
- VS Code diagnostics: sin errores reportados en backend/frontend tras los cambios.
- Ciberseguridad backend: VS Code diagnostics sin errores y `git diff --check` OK tras el hardening.

No ejecutado: `pytest`, migraciones Alembic ni arranque FastAPI. Bloqueo: no hay Python real, `py`, `uv` ni Docker disponibles en esta maquina.

## Riesgos criticos pendientes

1. Backend sin validacion runtime completa. Hay que instalar Python/Docker y correr migraciones, tests e integraciones antes de asumir que el backend esta sano.
2. Arquitectura duplicada. Conviven `modules/*` y `presentation/application/domain/infrastructure`; ya se corrigio el router de turnos, pero hay que decidir una arquitectura oficial y retirar la otra o integrarla bien.
3. Staff-servicios esta duplicado entre JSON `service_ids` y tabla `staff_services`. Para escalar conviene normalizar en pivot y dejar el JSON como cache o eliminarlo.
4. RLS necesita prueba real de aislamiento por tenant. Ya se agrego migracion con `FORCE ROW LEVEL SECURITY`; falta validarla contra PostgreSQL real y revisar rol de conexion no propietario para produccion.
5. Portal publico usa bypass global de RLS para resolver stores/servicios. Es funcional, pero debe auditarse endpoint por endpoint para garantizar que solo expone datos publicos.
6. Autenticacion guarda JWT en `localStorage`; es practico para desarrollo, pero aumenta impacto de XSS. Para produccion conviene migrar a cookie `HttpOnly` + `SameSite` + CSRF.
7. Rate limiting ya esta aplicado globalmente y en auth/public. Falta testearlo con Redis real, calibrar cuotas por plan y agregar metricas/alertas.
8. Overbooking: hoy depende de bloqueo pesimista sobre staff y chequeos de overlap. Para alta concurrencia, conviene sumar constraint/exclusion index en PostgreSQL con rangos por staff y estado activo.
9. Docker compose expone PostgreSQL y Redis al host y trae credenciales default. Debe quedar marcado como dev-only o endurecerse para staging/prod.
10. Observabilidad incompleta: hay `structlog`, auditoria y eventos, pero faltan request IDs, logs estructurados consistentes, metricas y trazas de errores de negocio.

## Backlog recomendado

### Prioridad 0 - levantar base confiable

- Instalar runtime backend o usar Docker.
- Ejecutar `python -m pytest`, `python run_migrations.py` y arranque de FastAPI.
- Crear seed minimo reproducible con 2 stores y test de aislamiento RLS.
- Probar flujo completo: register, login, CRUD servicios, CRUD staff, disponibilidad, reserva publica, cancelacion y reportes.

### Prioridad 1 - contratos y datos

- Consolidar status de turnos en un solo casing entre backend y frontend.
- Normalizar staff-servicios con `staff_services` como fuente de verdad.
- Revisar migraciones d5/c5: fueron correctivas pero dejaron downgrade incompleto y columnas restauradas por migracion nueva.
- Agregar tests de migracion o al menos smoke test contra PostgreSQL limpio.

### Prioridad 2 - seguridad SaaS

- Aplicar rate limits por IP y por email/telefono.
- Cambiar JWT de localStorage a cookie segura para produccion.
- Revisar permisos de cada endpoint administrativo por rol.
- Limitar CORS por entorno y bloquear localhost en produccion, ya validado en settings.
- Ocultar Swagger/ReDoc o protegerlo en produccion.

### Prioridad 3 - escalabilidad y producto

- Code splitting frontend para bajar bundle inicial mayor a 500 kB.
- Cachear disponibilidad con invalidacion por patron robusta; `redis.delete` no borra wildcards.
- Agregar jobs reales de reminders y respetar flags del store.
- Completar cobro real con pasarela de pagos, facturacion, limites por plan y pantalla frontend SuperAdmin. Ya existe base backend/API para planes, suscripciones y cupones comerciales.
- E2E con Playwright para booking publico y dashboard admin.

## Conclusión

El proyecto esta en una fase intermedia avanzada: el frontend esta bastante sano y el backend tiene buena intencion arquitectonica, pero venia con un corte de refactor incompleto. Las correcciones de esta pasada atacan los bloqueos principales de contrato y seguridad basica. El siguiente paso no deberia ser sumar features: deberia ser levantar backend en entorno reproducible, correr migraciones/tests y cerrar la decision arquitectonica para que el SaaS crezca sin deuda cruzada.