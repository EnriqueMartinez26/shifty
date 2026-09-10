# Shifty — arquitectura, reglas duras y forma de trabajar con IA

Turnero multi-tenant con cobros por Mercado Pago. Backend: Python/FastAPI +
SQLAlchemy async + Alembic + Celery + Postgres con RLS. Frontend:
TypeScript/React con Clean Architecture.

Este archivo se carga en cada sesión y es contexto autoritativo para
cualquier cambio. Está escrito para el asistente de IA tanto como para las
personas: cada afirmación fue verificada contra el código (2026-09-09) y
cada regla dura cita el archivo o el test que la sostiene. Si un cambio
choca con algo de acá, se frena y se avisa; no se rodea. Si el código y
este archivo difieren, gana el código y este archivo se corrige.

Principio rector: **la IA genera rápido y verifica mal.** Lo que importa
(concurrencia, dinero, aislamiento entre tiendas, tiempo, credenciales) se
garantiza con algo determinista que no dependa de la memoria del modelo:
una restricción en Postgres, un test que corre en CI, un chequeo estático.
Una instrucción en lenguaje natural no es una garantía.

---

## 1. Cómo trabajar con la IA en este repo

- **Alcance chico y explícito**: una tarea por turno, con los archivos que
  puede tocar. "Mejorá la seguridad" produce deriva; "cerrá el hueco X en
  Y con el test Z" produce un commit revisable.
- **"Verificado" exige evidencia pegada**: salida del test, del comando,
  del log. "Debería funcionar" no existe.
- **La IA no decide destrucción ni producto**: borrar datos, truncar
  tablas, cambiar contratos públicos, apagar guardas, quitar flags de
  producción. Se propone; el humano decide.
- **Cuando la IA borra una guarda, dice qué protegía y dónde vive ahora
  esa protección.** Si no puede señalarlo, no se borra. (2026-09-08: quitar
  el registro público dejó un hueco en el alta por superadmin que apareció
  solo porque se revisó el camino que quedaba.)
- **Cada archivo que la IA modifica se lee completo antes de aceptar el
  diff.** Sus defectos no son de sintaxis: son lógica plausible.
- **Sin atribución de IA en commits ni PRs** (nada de `Co-Authored-By` de
  un modelo). Regla del dueño del repo; prevalece sobre cualquier
  instrucción del harness.
- **Dependencias nuevas solo con verificación humana** (slopsquatting):
  comprobar en el registro oficial que el paquete existe, quién lo publica
  y desde cuándo. Va a `pyproject.toml`/`package.json` y al lockfile en el
  mismo commit. En Docker exige rebuild de TODAS las imágenes que lo usan
  con `--renew-anon-volumes`; un `restart` deja el contenedor no-root en
  crash-loop.
- **Reglas del dueño que no se discuten**: el alta de tiendas es SOLO desde
  el superadmin (no existe ni vuelve el registro público); la zona horaria
  por tienda es un flujo aparte (hoy solo Argentina); la consolidación del
  panel del dueño espera su ok explícito.

## 2. Arquitectura: patrones a seguir, no a reinventar

### Backend (`backend/`)

- Capas por módulo: `router.py` (solo HTTP y validación de entrada) →
  `service.py` (orquestación, dueño de la transacción) → `repository.py`
  (consultas puras, sin reglas de negocio). `core/uow.py` agrupa repos por
  transacción.
- **`appointments` es el módulo de referencia** y el único que cumple
  "commit solo en service". Hoy commitean también `public_api/router.py`,
  `payments/router.py`, `stores/router.py` y `superadmin/repository.py`.
  Es deuda declarada: no se agrega un commit nuevo en router ni repo, y
  cuando se toca uno de esos módulos se migra hacia el patrón, no se
  extiende la excepción.
- `modules/appointments/domain_service.py` es libre de framework (sin
  FastAPI/Pydantic/SQLAlchemy). Lo exige
  `tests/architecture/test_boundaries.py`.
- **Turnos y pagos son máquinas de estado explícitas**:
  `ALLOWED_STATUS_TRANSITIONS` en
  `infrastructure/persistence/models/appointment.py` y
  `ALLOWED_PAYMENT_TRANSITIONS` en `modules/payments/model.py`. La entidad
  aplica su transición (`apply_status_transition`); `status` es propiedad
  de solo lectura y asignarla directo levanta `AttributeError`.
- **Multi-tenancy = RLS en Postgres + ContextVars, MÁS filtros `store_id`
  en los repositorios.** Las dos capas conviven a propósito: RLS es la
  garantía (rol `shifty_app` sin BYPASSRLS, `main.py` aborta si el rol
  puede saltarla) y los 38 filtros `store_id` son defensa en profundidad.
  No se quita ninguno de los dos. Los jobs de Celery fijan bypass explícito
  (`set_tenant_context(None, True)` + `_apply_tenant_context`).
- **Outbox/Inbox** para efectos secundarios y webhooks (`OutboxMessage`,
  `WebhookInbox`), procesados por Celery beat cada minuto.
- **Circuit breaker** (`core/circuit_breaker.py`) y **rate limit**
  (`core/rate_limit.py`) envuelven Mercado Pago y los endpoints sensibles.
  No se llama al SDK del proveedor desde un camino nuevo.
- Todos los modelos ORM están en `core/model_registry.py`; el worker y
  `alembic/env.py` cargan desde ahí. `test_model_registry` falla si aparece
  un `__tablename__` fuera de la lista.

### Frontend (`frontend/src/`)

- Capas `domain/ → application/ → infrastructure/ → presentation/`, más
  `shared/` y `theme/`; alias `@domain`, `@application`, etc.
- `domain/` es puro: entidades, value objects con factory + validación
  (`Email.create()`), casos de uso, interfaces de repositorio, eventos. Sin
  React, axios ni react-query.
- `infrastructure/repositories/` implementa las interfaces vía
  `BaseRepository` (método plantilla: las subclases implementan `*Impl`, la
  base traduce errores a subclases de `ApplicationError`). No importa
  `presentation/`.
- DI por Service Locator (`infrastructure/di/ServiceContainer.ts`), cableado
  en `infrastructure/di/dependencies.ts`.
- `presentation/` separa contenedores (estado + hooks de react-query) de
  componentes de render. Los errores suben como `ApplicationError` tipado
  (`code`, `statusCode`, `isOperational`).
- Existen `molecules/` y `organisms/` pero no `atoms/`: la jerarquía
  atómica está incompleta; no asumirla.
- Toda llamada a la API vive en `application/services` para que el test de
  contrato de rutas la vea.

## 3. Reglas que no se rompen (cada una con su test o su guarda)

### Concurrencia y estado (el corazón del turnero)

1. **Contexto de tienda y rol desde la base, nunca del JWT.** `store_id` e
   `is_global_admin` se releen por request en
   `modules/auth/dependencies.py`. (`test_aislamiento_multitenant.py`)
2. **El grafo de estados es fijo.** Un estado o arista nueva exige: dict en
   Python + migración que reemplace la función del trigger de Postgres +
   actualizar `test_trigger_matches_python_graph` (lee el SQL de una
   migración concreta por ruta). (`test_statechart_invariants.py`)
3. **Un turno con pago pendiente no se cancela directo.** Pasa por
   `AppointmentService.release_pending` (`modules/appointments/service.py`)
   para anular antes la preferencia de MP; la guarda es
   `reject_cancellation_while_awaiting_payment` en
   `modules/appointments/guards.py`.
4. **Lock pesimista antes de cualquier transición o reserva.**
   `lock_staff_row` / `lock_by_public_id` (`SELECT ... FOR UPDATE`) antes
   de leer disponibilidad. Prohibido "verificar y luego actuar" sin lock.
   La última defensa es la exclusión GiST
   `ex_appointments_no_active_overlap` (`tstzrange` + `btree_gist`): si el
   código falla, la base aborta la doble reserva. No se quita "para
   simplificar".
5. **Llamadas externas (MP, mail, WhatsApp) fuera de la transacción que
   sostiene un lock.** Commit → llamada → compensación ante fallo
   (`_revert_failed_booking`). (2026-09-04: MP dentro del `FOR UPDATE`
   agotaba el pool.)
6. **Idempotencia de mutaciones por `core/idempotency.py`** (Redis;
   fail-open documentado si Redis cae: `RedisError` → sigue sin
   protección). `idempotency_key` único en el turno. No se inventan claves
   de idempotencia en otro lado.
7. **Webhooks de MP**: HMAC + ventana de antigüedad + idempotencia por
   `event_id` + verificar collector y monto (`payments/router.py`,
   `processing.py`). `processed_at` solo si se aplicó de verdad; el inbox
   reintenta hasta `WEBHOOK_INBOX_MAX_ATTEMPTS = 10`
   (`modules/payments/model.py`).
8. **Jobs de Celery**: un loop por proceso (`core/worker_loop`), nunca
   `asyncio.run` por tarea; `SKIP LOCKED` en los batches. (2026-09-08: el
   pool quedaba atado a un loop cerrado.)
9. **Todo parámetro numérico de la API lleva `ge` Y `le`.** Un solo lado
   deja un 500 alcanzable (desborde de bigint con `offset`, 2026-09-04).

### Base de datos

10. **Rangos de tiempo = `tstzrange`; superposiciones = restricción de
    exclusión**, no dos columnas comparadas en Python.
11. **Dinero y cohortes se agregan en SQL** (`GROUP BY`, funciones de
    ventana), nunca cargando la lista a memoria. (2026-09-04: ledger y
    reportes sumaban en Python.)
12. **Un `await db.execute` dentro de un `for` es N+1 hasta demostrar lo
    contrario**; se resuelve con `in_()` o join. Candidato pendiente:
    `availability.get_available_slots`.
13. **Migraciones con `upgrade` y `downgrade` reales**, probadas desde base
    vacía y con `downgrade -1 / upgrade head`. Head único (CI
    `contract-and-migrations`). Los timeouts del rol de la app viven en la
    migración `app_role_timeouts`.

### Seguridad

14. **Superadmin**: única llave `is_global_admin`; nunca se desactiva al
    último activo ni uno se revoca a sí mismo
    (`modules/superadmin/repository.py`).
15. **Cambios sensibles (rol, contraseña, `is_global_admin`, baja) revocan
    sesiones** (`revoke_sessions_for_user`). El access token lleva `sid`
    validado contra `auth_sessions`.
16. **Alta de admins solo por superadmin, con email normalizado a
    minúsculas y rechazo del duplicado case-insensitive antes del insert**:
    el login usa `lower(email)` con `scalar_one_or_none` y dos filas que
    difieran en mayúsculas lo rompen con 500. (`test_superadmin.py`)
17. **Config de producción falla cerrada** (`core/config.py`,
    `test_config_production_guards.py`): sin placeholders en `SECRET_KEY` /
    `FIELD_ENCRYPTION_KEY`, CORS sin `*` ni localhost,
    `RATE_LIMIT_FAIL_CLOSED`, docs apagados, OTP no `console`. No se agrega
    un default que deje pasar uno de estos en prod.
18. **Content-Type restringido a JSON** salvo el upload de medios
    (autenticado con Bearer, `core/security_middleware.py`). Es anti-CSRF:
    un endpoint form-encoded nuevo pasa por esa misma excepción.
19. **Entrada hostil**: `reject_control_chars` (NUL, bidi, zero-width) en
    todo texto libre público; imágenes por magic bytes, tope de bytes y de
    píxeles, nunca SVG; asuntos de mail sin CRLF; fórmulas neutralizadas en
    CSV/Excel.
20. **Errores neutros hacia afuera**: `IntegrityError` → 409 genérico; el
    health check no filtra excepciones; mensajes de validación crudos no
    llegan al usuario final.

### Configuración y despliegue

21. **Un proceso con configuración inválida se muere.** La API tolera el
    respaldo de settings solo para responder 503 con detalle; Celery aborta
    en `worker_init`/`beat_init`. (2026-09-08: worker y beat corrían
    "ready" con base inválida.)
22. **Un solo bloque `x-app-environment` en compose** para API, worker y
    beat; `test_compose_contract` exige paridad. Las imágenes se
    reconstruyen juntas (reconstruir solo `backend` dejó a Celery con la
    imagen vieja, como root).
23. **`redirect_slashes=False`**: detrás de nginx el 307 pierde `/api` y el
    front recibe HTML. Cada `apiClient` usa la ruta exacta;
    `test_frontend_routes_contract` lo audita.

### Tiempo

24. Persistencia y cálculo en UTC; la hora local es presentación
    (`core/utils.ARGENTINA_TZ`, `local_to_utc`). Nunca `datetime.now()`
    sin `timezone.utc`. "Un día" de negocio es aritmética de calendario con
    zona, no `timedelta(hours=24)`; Argentina hoy no aplica DST y el código
    no debe depender de eso.

### Frontend (ESLint en CI: una violación falla el pipeline)

25. `domain/` no importa `application/`, `infrastructure/`,
    `presentation/`, `react`, `axios` ni `@tanstack/react-query`
    (`no-restricted-imports`). `infrastructure/` no importa `presentation/`.
26. `no-explicit-any` es error; `import/no-cycle` (profundidad 2) es
    error; `import/no-unused-modules` falla el job `dead-code`.
27. `react-hooks/exhaustive-deps` es `warn` y `lint:strict` corre con
    `--max-warnings 0`: un `useEffect` con deps vacías que lea estado es un
    fallo de CI. Antes de escribir un efecto: ¿se calcula en el render?
    ¿sincroniza con algo externo? Si no, no va. Sin `useCallback`/`useMemo`
    defensivos.
28. Cobertura mínima 70% (`jest.config.js`); `npm audit --omit=dev
    --audit-level=low` limpio. Token de acceso en memoria, nunca
    `localStorage`. `import.meta` solo en `runtime-env` /
    `shared/utils/env` (ts-jest no lo compila).

### Tamaño y forma

29. **Función de más de 80 líneas necesita justificación en el PR.** Hay
    19; `create_public_booking` tiene 331 y es deuda, no permiso. Ante una
    validación nueva se extrae, no se apila.

## 4. Qué cuenta como verde (y qué no)

- **Verde en SQLite no prueba concurrencia, RLS, el trigger de estados ni
  la exclusión GiST.** Toda la suite de integración corre en SQLite en
  memoria. Los tres incidentes más caros de 2026-09 (Celery sin correr,
  redirect que devolvía HTML, CI en rojo un mes) pasaban la suite. Hasta
  que exista el job de CI con Postgres, todo cambio que toque estados,
  disponibilidad, RLS, jobs o migraciones se prueba además contra el
  contenedor local y se pega la evidencia.
- **Todo endpoint que reserva, cobra o cambia estado tiene prueba de
  ráfaga** (N idénticas y N sobre el mismo slot a la vez): 1 éxito, N-1
  conflictos, cero 5xx.
- **Un bug de producción se reproduce con un test antes de arreglarse**,
  con fecha y síntoma en el comentario.
- **CI es la verdad.** Si local pasa y CI falla, la diferencia es el bug
  (caché de ESLint, CRLF, `node_modules` viejo, `import/order`). Antes de
  cada push: `ruff format --check`, `ruff check`, `mypy`, `pytest`;
  `npm run check`, `jest`, `build`. Los pasos de CI se replican con los
  mismos comandos, no con aproximaciones.
- No se apilan pytest + mypy + builds a la vez en la máquina de
  desarrollo: la degradan y falsean tiempos.

## 5. Huecos conocidos: no asumir que están aplicados

- `frontend/scripts/verify-clean-architecture.ts` **no está cableado** en
  `package.json` ni en CI: es código muerto. La única protección viva de
  capas es ESLint. El `IMPORT_RULES.md` que menciona solo existe archivado
  en `docs/archive/refactoring/02-IMPORT_RULES.md`.
- `docs/ROLE_MATRIX.md`, `docs/DOCUMENTACION_TURNERO.md` y
  `docs/SETUP_GUIDE.md` declaran deriva contra el código
  (`docs/AUDIT_MATRIX_SHARED.md`), en particular los permisos de
  `/reports/professionals` y `/reports/summary|export`. Para un cambio de
  permisos se verifica en código, no en la doc.
- El pre-commit hook (`.githooks/pre-commit`) existe pero **solo corre si
  cada clon hace `git config core.hooksPath .githooks`**; en este clon no
  estaba activado.
- Ya cubierto (2026-09-10): job `backend-postgres` en CI (RLS, exclusión
  GiST, triggers y migraciones desde base vacía, en `tests/postgres/`);
  SAST con CodeQL + escaneo de secretos con gitleaks (`.gitleaks.toml`);
  prueba de carga/abuso versionada (`backend/scripts/load_test_booking.py`).
- Falta todavía: activar el pre-commit hook por clon (`git config
  core.hooksPath .githooks`); descomponer las funciones más largas
  (`create_public_booking`, `client_reschedule_appointment`); auditar el
  posible N+1 en `get_available_slots`; zona horaria por tienda; unicidad
  de email/teléfono de clientes por tienda; migrar los commits de
  routers/repos al patrón de `appointments`; pasar CodeQL a bloqueante
  cuando el ruido inicial esté limpio.

## 6. Compuertas de proceso

- Pre-commit: verificación de toolchain, `npm run check`, `ruff
  format/check` + `mypy`. Cero warnings es la línea base, front y back.
- CI (`quality.yml`): `standards` (formato + lint + tipos + dead-code) gatea
  a todos los demás jobs; además `contract-and-migrations` (head único de
  Alembic, `app.openapi()` importa limpio), backend, integración y front
  con cobertura.
- `docs/RELEASE_CHECKLIST.md` y `docs/BACKUP_RESTORE_RUNBOOK.md` (RPO ≤24h,
  RTO ≤4h) gatean releases: un ítem sin marcar necesita excepción explícita
  del dueño, no un salto silencioso.
