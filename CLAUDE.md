# Shifty — arquitectura, reglas duras y forma de trabajar con IA

Turnero multi-tenant con cobros por Mercado Pago. Backend: Python/FastAPI +
SQLAlchemy async + Alembic + Celery + Postgres con RLS. Frontend:
TypeScript/React con Clean Architecture.

Este archivo se carga en cada sesión y es contexto autoritativo para
cualquier cambio. Está escrito para el asistente de IA tanto como para las
personas: cada afirmación fue verificada contra el código (2026-09-09;
re-verificada el 2026-09-19 contra las derivas D del audit) y
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
  (`docker-compose build`): el código y el venv salen de la imagen, sin bind
  mount ni volumen anónimo, y un `restart` sigue corriendo la imagen vieja.
- **Reglas del dueño que no se discuten**: el alta de tiendas es SOLO desde
  el superadmin (no existe ni vuelve el registro público); la zona horaria
  por tienda es un flujo aparte (hoy solo Argentina); la consolidación del
  panel del dueño espera su ok explícito.

## 2. Arquitectura: patrones a seguir, no a reinventar

### Backend (`backend/`)

- Capas por módulo: `router.py` (solo HTTP y validación de entrada) →
  `service.py` (orquestación, dueño de la transacción) → `repository.py`
  (consultas puras, sin reglas de negocio). `core/uow.py` agrupa repos por
  transacción. Es el destino, no el estado de todos: `services` y
  `superadmin` no tienen `service.py`, `stores` es solo router y `otp` solo
  service.
- **`appointments` es el módulo de referencia** de "commit solo en service"
  (con una excepción propia: `claim_reminder`/`release_reminder` de su
  repositorio commitean como operación técnica atómica, con el commit plano
  de `AsyncSession` para no quedar "idle in transaction" durante el SMTP,
  F1-22). Los archivos que
  todavía commitean en router o repositorio NO se listan acá: la lista es
  `COMMITS_DECLARADOS_FUERA_DE_SERVICE` en
  `tests/architecture/test_boundaries.py`, un techo por archivo que solo
  puede bajar (falla si un archivo commitea más o si aparece uno nuevo). Entre
  ellos está `services/repository.py`, excepción declarada hasta que se toque
  el módulo (B6-05). Los módulos ya migrados (`ledger`, `promotions`,
  `public_api`: la reserva y la autogestión viven en
  `public_api/service.py::PublicBookingService`) los fija
  `tests/architecture/test_transaccion_en_service.py`, y `staff`/`users`
  `tests/architecture/test_commits_en_service.py`. Es deuda declarada: no se
  agrega un commit nuevo en router ni repo, y cuando se toca uno de esos
  módulos se migra hacia el patrón y se baja su número, no se extiende la
  excepción.
- `modules/appointments/domain_service.py` es libre de framework (sin
  FastAPI/Pydantic/SQLAlchemy). Lo exige
  `tests/architecture/test_boundaries.py`.
- **Turnos y pagos son máquinas de estado explícitas**:
  `ALLOWED_STATUS_TRANSITIONS` en
  `infrastructure/persistence/models/appointment.py` y
  `ALLOWED_PAYMENT_TRANSITIONS` en `modules/payments/model.py`. La entidad
  aplica su transición (`Appointment.apply_status_transition`,
  `Payment.apply_status`); en las dos `status` es propiedad de solo lectura
  y asignarla directo levanta `AttributeError`
  (`test_statechart_invariants.py`, `test_payment_status_solo_lectura.py`).
  El grafo de turnos lo repite un trigger de Postgres; el de pagos vive
  solo en Python (sin trigger ni `CHECK`).
- **Multi-tenancy = RLS en Postgres + ContextVars, MÁS filtros `store_id`
  en las consultas.** Las dos capas conviven a propósito: RLS es la
  garantía (rol `shifty_app` sin BYPASSRLS, `main.py` aborta si el rol
  puede saltarla) y los filtros `store_id` de repositorios, reportes y panel
  son defensa en profundidad y, bajo RLS, el camino al índice (§3, Base de
  datos) (`test_aislamiento_multitenant.py`,
  `test_reportes_aislamiento_por_tienda.py`; la cuenta de filtros no es un
  control, cambia con cada consulta). No se quita ninguno de los dos. Los
  jobs de Celery fijan bypass explícito (`set_tenant_context(None, True)` +
  `_apply_tenant_context`).
- **Outbox/Inbox** para efectos secundarios y webhooks (`OutboxMessage`,
  `WebhookInbox`), procesados por Celery beat (outbox cada 20 s, inbox cada
  minuto).
- **Dos Redis con papeles distintos** (plan §7, decisión 5). El caché de
  disponibilidad va a `redis_cache` por `core/redis.py::get_availability_cache`
  (`REDIS_CACHE_URL`; `volatile-ttl`, sin persistencia: perderlo solo cuesta
  recalcular). Rate limit, idempotencia, OTP, lockout, OAuth y los resultados
  de Celery van a `redis_state` por `REDIS_URL` (`noeviction`): un desalojo
  nunca puede aflojar una protección. Nada de estado nuevo en el Redis de
  caché, ni caché nuevo en el de estado.
- **Publicar a Celery desde un request pasa por un helper único** con
  `asyncio.to_thread` y tope de 2 s que nunca propaga; ninguna llamada
  síncrona de red dentro de un `async def` (R8-02: con el broker caído,
  publicar en línea congelaba la API hasta 33 s). El helper es
  `core/enqueue.py::enqueue` (F1-03, 2026-09-24): todo `enqueue_*` pasa por
  ahí y `tests/architecture/test_encolado_solo_por_el_helper.py` prohíbe
  `.delay(`/`.apply_async(` fuera de él.
- **Circuit breaker** (`core/circuit_breaker.py`) envuelve Mercado Pago. No
  se llama al SDK del proveedor desde un camino nuevo. El **rate limit**
  (`core/rate_limit.py`) es un middleware por IP con política propia solo
  para `/auth/` y `/public/` (el resto, `/payments/*` incluido, cae en la
  global), más `enforce_rate_limit` puntual en `auth/router.py`,
  `public_api/router.py` y `waitlist/public_router.py`.
- Todos los modelos ORM están en `core/model_registry.py`; el worker,
  `alembic/env.py`, los scripts y el conftest de integración cargan desde
  ahí. `test_model_registry` falla si aparece un `__tablename__` fuera de
  la lista.

### Frontend (`frontend/src/`)

- Capas `domain/ → application/ → infrastructure/ → presentation/`, más
  `shared/` y `theme/`; alias `@domain`, `@application`, etc.
- `domain/` es puro: entidades, value objects con factory + validación
  (`Email.create()`), casos de uso, interfaces de repositorio. Sin
  React, axios ni react-query.
- `infrastructure/repositories/` implementa las interfaces vía
  `BaseRepository` (método plantilla: las subclases implementan `*Impl`, la
  base traduce errores a subclases de `ApplicationError`). No importa
  `presentation/`.
- Sin contenedor de DI: los servicios de `application/services/` se exportan
  como singletons de módulo (`export const userService = new UserService(...)`
  al final de cada archivo, mismo patrón que ya usaba
  `PublicBookingService.ts`) e importan directo donde se consumen, p. ej.
  `presentation/hooks/useManagedDomainUsers.ts`.
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
2. **El grafo de estados es fijo.** Una arista o estado nuevo de turnos
   exige: dict en Python + migración que reemplace la función del trigger de
   Postgres + actualizar `tests/unit/test_trigger_matches_python_graph.py`,
   que compara el dict con el SQL de una migración concreta leída por ruta
   (hoy `b2c3d4e5f6a7_statechart_hardening.py`).
   `test_statechart_invariants.py` cubre el grafo en Python (terminales
   absorbentes, una sola fuente por región).
3. **Un turno con cobro vivo no se suelta sin vencer el cobro.** Cobro vivo
   es `pending_payment` o un `Payment` en `pending` o `rejected` (MP deja
   reintentar sobre el mismo link), p. ej. el link que el panel genera sobre
   un confirmado (`LIVE_CHARGE_PAYMENT_STATUSES` en
   `modules/payments/model.py`; en SQL, `live_charge_of` en
   `modules/payments/repository.py`). El camino compartido que lo vence es
   `payments/service.py::expire_live_charge` (todos menos el job de
   retenciones, que vence por el grafo sin publicar; ver abajo): pago a `expired` por la
   entidad y `payment.preference.expire` al outbox en la misma transacción
   (salvo un link placeholder, que no existe en MP), con el turno lockeado
   antes que el pago; el link de MP lo anula después el outbox. Todos los
   caminos que sueltan un turno (decisión del dueño, 2026-09-25, y revisión
   de perf/f4-pay):
   - cancelar desde el panel (`AppointmentService.cancel`, cualquier
     personal; un turno ya cancelado es 409 `APPOINTMENT_ALREADY_CANCELLED`;
     cancelar no toca un pago acreditado);
   - reprogramar desde el panel (`reschedule`) un turno con link del panel:
     vence el link y el turno nuevo nace sin cobro. Un `pending_payment`
     (seña REQUERIDA pendiente) no se reprograma: 409
     `DEPOSIT_PENDING_RESCHEDULE_DENIED` bajo el lock del turno y antes de
     tocar nada, la seña nunca se pierde; se cobra y después se mueve, o se
     cancela (decisión del dueño 2026-09-25: opción A;
     `guards.reject_reschedule_with_pending_deposit`);
   - liberar (`release_pending`, solo admin);
   - cancelar por bloqueo (`AppointmentBlockService`: alta, cierre de la
     tienda y edición);
   - el webhook que suelta el turno (un rechazo pasa
     un `pending_payment` a `expired`; `processing.apply_mercadopago_webhook_payload`);
   - el job de retenciones vencidas (`payments/jobs.py`, toma los cobros de
     `LIVE_CHARGE_PAYMENT_STATUSES` y los vence por el grafo; sin publicar:
     el link se creó con `expiration_date_to` = la retención y ya venció).
   El cliente no lo cancela ni lo reprograma
   (`client_cancel_denial`/`client_reschedule_denial`, 409
   `PAYMENT_APPOINTMENT_REQUIRES_RELEASE`), y un turno terminal no se
   reprograma desde ningún lado (409 `APPOINTMENT_NOT_ACTIVE`). El link del
   panel y la confirmación manual lockean el turno y rechazan uno soltado
   (`cancelled`/`expired`, `RELEASED_APPOINTMENT_STATUSES`: 409
   `APPOINTMENT_NOT_PAYABLE`); un `completed` o `absent` se sigue cobrando.
   Regenerar el link de un cobro `expired` sella un `preference_id` nuevo y
   lo reabre con `Payment.reopen_for_panel_link` (único llamador el link del
   panel, bajo el lock del turno; `ALLOWED_PAYMENT_TRANSITIONS` no tiene
   `expired → pending` para que un webhook tardío no reabra un cobro vencido;
   `test_reabrir_cobro_para_link_del_panel.py`,
   `test_regenerar_link_de_cobro_vencido.py`). (`test_link_del_panel_es_cobro_vivo.py`,
   `test_cancelar_desde_el_panel_vence_el_cobro.py`,
   `test_cancelar_dos_veces_desde_el_panel.py`,
   `test_reprogramar_del_panel_vence_el_cobro.py`,
   `test_bloqueo_vence_el_cobro_vivo.py`, `test_cobro_rechazado_se_suelta.py`,
   `test_turnos_terminales_no_reviven.py`,
   `test_link_del_panel_solo_turnos_vivos.py`,
   `test_confirmacion_manual_solo_turnos_vivos.py`,
   `test_pg_cancelar_con_cobro_vivo.py`)
4. **Lock pesimista antes de cualquier transición o reserva.**
   `lock_staff_row` / `lock_by_public_id` (`SELECT ... FOR UPDATE`) antes
   de leer disponibilidad. Prohibido "verificar y luego actuar" sin lock.
   La última defensa es la exclusión GiST
   `ex_appointments_no_active_overlap` (`tstzrange` + `btree_gist`): si el
   código falla, la base aborta la doble reserva. No se quita "para
   simplificar".
5. **Llamadas externas (MP, mail, WhatsApp) fuera de la transacción que
   sostiene un lock.** Commit → llamada → compensación ante fallo
   (`public_api/service.py::revert_failed_booking`). (2026-09-04: MP dentro
   del `FOR UPDATE` agotaba el pool.) Liberar un turno no llama a MP: el
   vencimiento del link lo hace el outbox en dos fases (reclamo con `SKIP
   LOCKED` y commit, llamada sin lock, resultado en otra transacción;
   `payments/jobs.py::_claim_and_expire_preferences`, B1-04,
   `test_pg_vencimiento_preferencia.py`).
6. **Idempotencia de mutaciones por `core/idempotency.py`** (Redis de
   ESTADO, `redis_state` por `REDIS_URL`, `noeviction`; fail-open
   documentado si Redis cae: `RedisError` → sigue sin protección). `idempotency_key` único en el turno. No se inventan claves
   de idempotencia en otro lado.
7. **Webhooks de MP**: HMAC + ventana de antigüedad + idempotencia por
   `event_id` + verificar collector y monto (`payments/router.py`,
   `processing.py`); la integridad exige la `external_reference` del link
   VIGENTE (`<turno>:<link_ref>` con `MERCADOPAGO_LINK_REF_ENABLED`, prendido
   por defecto; apagado, regenerar el link de un cobro vencido es 409; el pago
   de MP no trae `preference_id`). Los links que un cobro deja de usar quedan en
   `payment_link_history` (`modules/payments/links.py`) porque su pago puede
   avisarse tarde (webhook demorado, reentregado o perdido; con `binary_mode`
   no hay cupones pendientes) y la conciliacion lo busca 7 días: un `approved`
   de uno de ellos, por su importe, lo adopta un cobro no acreditado (el
   vigente se vence) y cualquier otro pago en un link reemplazado avisa una
   vez por pago de MP; los no aprobados se cierran como no-op. `processed_at` solo si se aplicó de verdad; el inbox
   reintenta hasta `WEBHOOK_INBOX_MAX_ATTEMPTS = 10`
   (`modules/payments/model.py`). Orden único de locks turno → pago: el
   webhook busca el cobro sin lock y lockea turno y después pago, como
   liberar, cancelar y reprogramar desde el panel, la cancelación por bloqueo
   (profesional → turnos → pagos), el link de pago del panel (en sus dos
   fases, `lock_payable_appointment`) y la confirmación manual (F1-18,
   `test_webhook_lockea_turno_antes_que_pago.py`,
   `test_pg_cancelar_con_cobro_vivo.py`). El job de retenciones vencidas
   lockea SOLO el turno (`SKIP LOCKED`, `of=Appointment`: Postgres no deja
   `FOR UPDATE` sobre el lado nullable del outer join) y escribe el pago
   serializado por ese lock, sin `FOR UPDATE` propio: todo otro escritor del
   pago toma el turno antes, y la columna `version` corta lo que quede.
   Lockearlo aparte sumaría una sentencia por lote. Otra excepción
   documentada: la marca `reconciled_at` de la conciliación
   (`payments/jobs.py::_marcar_conciliados`) escribe pagos sin el lock del
   turno; es seguro porque solo toca `reconciled_at`/`updated_at` (no
   `version` ni nada de negocio), en su propia transacción y tomando las
   filas en orden de id con `FOR UPDATE SKIP LOCKED` (una fila tomada queda
   sin marcar; `test_pg_conciliacion_reconciled_at.py`). `X-Request-ID` es parte de la firma de MP
   y nadie lo pisa: el id del borde viaja como `X-Edge-Request-Id`
   (`nginx/nginx.conf` y `nginx/nginx.prod.conf`,
   `tests/unit/test_nginx_contract.py`).
8. **Jobs de Celery**: un loop por proceso (`core/worker_loop`), nunca
   `asyncio.run` por tarea; `SKIP LOCKED` en los batches, recordatorios
   incluidos. (2026-09-08: el pool quedaba atado a un loop cerrado.)
   (`test_pg_lotes_skip_locked.py`, `test_pg_recordatorios_skip_locked.py`)
   El OTP va a la cola `interactive` (`core/celery_app.py::task_routes`),
   que atiende un worker aparte, `celery_worker_interactive`
   (`--concurrency=1`): su latencia no depende de los lotes de la cola
   `celery`. Los mails de la reserva pública también van ahí
   (`send_booking_email`, F2-01, 2026-09-24): al broker viajan solo ids, el
   worker relee el turno bajo bypass con `store_id` y cierra la sesión antes
   del SMTP.
9. **Todo parámetro numérico de la API lleva `ge` Y `le`.** Un solo lado
   deja un 500 alcanzable (desborde de bigint con `offset`, 2026-09-04).

### Base de datos

10. **Rangos de tiempo = `tstzrange`; superposiciones = restricción de
    exclusión**, no dos columnas comparadas en Python.
11. **Dinero y cohortes se agregan en SQL** (`GROUP BY`, funciones de
    ventana), nunca cargando la lista a memoria. (2026-09-04: ledger y
    reportes sumaban en Python.) (`test_reportes_dinero_en_sql.py`,
    `test_fiado_resumen_en_sql.py`)
12. **Un `await db.execute` dentro de un `for` es N+1 hasta demostrar lo
    contrario**; se resuelve con `in_()` o join.
    `availability.get_available_slots` se auditó el 2026-09-16: carga
    horarios, turnos y bloqueos con `in_()` y agrupa en memoria; no tiene N+1.
13. **Migraciones solo para Postgres, con `upgrade` y `downgrade` reales.**
    La suite de SQLite no corre Alembic (`create_all` en
    `tests/integration/conftest.py`): las guardas de dialecto que tienen
    algunas migraciones no prueban soporte SQLite. CI las corre desde base
    vacía hasta head y baja y vuelve a subir SOLO la última
    (`tests/postgres/test_pg_migraciones.py`); la cadena completa de
    downgrades nunca se probó. `d5ec116d06a3` es irreversible (pasa ids a
    ULID y borra columnas con datos): su `downgrade` levanta
    `NotImplementedError` y se vuelve desde backup. Head único:
    `tests/architecture/test_migrations.py` en el job
    `contract-and-migrations` (`alembic heads` solo lista). Los timeouts del
    rol de la app viven en la migración `app_role_timeouts`; los de las
    migraciones, en `alembic/env.py` (`SET lock_timeout = '3s'` y
    `transaction_per_migration=True`: una revisión que espera un lock aborta
    y no arrastra a las demás).

- **Migraciones sin corte (expand/contract).** El deploy migra ANTES de
  recrear, con el código viejo sirviendo, y el rollback vuelve al código
  anterior SIN migrar (`scripts/deploy.sh`, `docs/DEPLOY_RUNBOOK.md`): cada
  release solo agrega, y lo que quita (columna, tabla, restricción) va un
  release después. Índices sobre tablas vivas con `CREATE INDEX
  CONCURRENTLY` dentro de `autocommit_block()` y `DROP INDEX CONCURRENTLY IF
  EXISTS` antes; restricciones con `NOT VALID` y `VALIDATE` aparte; backfills
  por lotes; sin `ALTER TYPE` que reescriba la tabla. `alembic/env.py` fija
  `lock_timeout = '3s'` y una transacción por revisión (F0-06): una migración
  que espera un lock falla en vez de encolar todas las requests detrás. Un
  índice vive a la vez en el modelo y en su migración (sin `index=True` que
  la migración no cree): `tests/postgres/test_pg_modelo_y_migraciones.py`
  compara los dos como `alembic check` y fija la deriva previa como techo que
  solo baja (F1-15).
  **Excepción única, fechada (2026-09-25):** `4b6d8f0a2c13` (PV-01) quita el
  único global de `users.email` en el MISMO release que lo reemplaza por los
  únicos parciales. Se permite SOLO porque sale en el primer release de
  producción: Shifty nunca se desplegó, no hay base viva y el primer deploy
  arranca de un esquema vacío, así que no existen ni la ventana del deploy
  (código viejo sirviendo sobre el esquema nuevo) ni la del rollback (volver
  al código anterior sin migrar). Ese código anterior sí dependía del único:
  el login busca por email con `scalar_one_or_none`. Después del lanzamiento
  la regla se aplica sin excepciones.
- **Bajo RLS solo los predicados leakproof usan índices.** Postgres no
  aplica un operador que no sea `LEAKPROOF` antes de la política de fila, así
  que el filtro `store_id` explícito es el camino al índice, no solo defensa.
  Nada de `lower()`, `&&`, `timezone()` ni `ILIKE` en consultas calientes
  (R7-01: el login con `lower(email)` recorría `users` entera; hoy compara la
  columna normalizada, `tests/architecture/test_email_por_igualdad.py` y
  `tests/postgres/test_pg_email_por_igualdad.py`; R7-02: el solapamiento
  recorría toda la historia del profesional, incluso bajo `FOR UPDATE`).
  Marcar funciones `LEAKPROOF` está descartado: Postgres no lo verifica.
- **Toda consulta de solapamiento pasa por `appointment_overlap` /
  `active_block_overlap`** (`modules/appointments/repository.py`, F1-13):
  `store_id` más las dos cotas. Para turnos la inferior es
  `starts_at > inicio - MAX_APPOINTMENT_SPAN`, correcta porque la base exige
  `ends_at <= starts_at + 1 día` (`ck_appointments_max_span`); subir ese tope
  es cambiar el CHECK y la constante juntos. Para bloqueos (hasta 366 días) es
  `end_time > inicio` sobre `ix_appointment_blocks_store_staff_end`. La base
  sostiene los supuestos: `ck_services_duration_max` (1440 min) y la
  migración `c3d5e7f9a1b4` se detiene si un turno o bloqueo tiene otra tienda
  que su profesional. (`test_pg_solapamiento_con_cotas.py`,
  `test_solapamiento_por_helper.py`, que falla con un solapamiento escrito a
  mano fuera del repositorio, y `test_pg_guardas_de_datos_del_solapamiento.py`)

### Seguridad

14. **Superadmin**: única llave `is_global_admin`; nunca se desactiva al
    último activo ni uno se revoca a sí mismo
    (`modules/superadmin/repository.py`).
15. **Cambios sensibles (rol, contraseña, `is_global_admin`, baja) revocan
    sesiones** (`revoke_sessions_for_user`). El access token lleva `sid`
    validado contra `auth_sessions`.
16. **Alta de admins solo por superadmin, con email normalizado a
    minúsculas y rechazo del duplicado case-insensitive antes del insert**:
    el login busca por igualdad `users.email = normalize_email(x)` SIN
    clientes (`auth.service.login_account_email`: `role <> 'client'`) con
    `scalar_one_or_none` (bajo RLS usa `ix_users_email` o
    `uq_users_email_non_client`; `lower(email)` recorría la tabla). Todo
    camino de alta normaliza con `auth.service.normalize_email` y la base lo
    sostiene: `CHECK (email = lower(email))` (`ck_users_email_lower`, F1-12).
    **El email de quien inicia sesión (personal, admins, superadmin) es único
    GLOBAL; el de un cliente, único POR TIENDA** (PV-01, decisión del dueño
    2026-09-25, migración `4b6d8f0a2c13`): `uq_users_email_non_client`
    (`email` WHERE `role <> 'client'`) y `uq_users_client_email_per_store`
    (`store_id, email` WHERE `role = 'client'`); `ix_users_email` quedó como
    índice común y el funcional global `uq_users_email_lower` se retiró. Un
    cliente puede compartir email con clientes de otras tiendas y con una
    cuenta del personal (el barbero que es cliente de otra tienda): toda
    búsqueda de login, olvido de clave o pre-chequeo de alta del personal
    filtra `role <> 'client'`, o `scalar_one_or_none` vuelve a dar 500. Un
    email de cliente se busca SIEMPRE con su `store_id`. Un admin de tienda no crea ni asciende admins por
    `/users/` (`core/roles.py::assert_can_grant_role`), no ve ni edita la
    cuenta de un superadmin y no cambia clave, estado, rol ni email de otro
    admin (`assert_can_change_access`, también por `/staff/`).
    (`test_superadmin.py`, `test_alta_de_admin_solo_superadmin.py`,
    `test_email_unico_apoyado_en_indice.py`, `test_pg_email_por_igualdad.py`,
    `test_email_de_cliente_por_tienda.py`,
    `test_pg_email_de_cliente_por_tienda.py`,
    `test_panel_no_toca_superadmin.py`, `test_staff_no_toca_cuentas_admin.py`)
17. **Config de producción falla cerrada** (`core/config.py`,
    `test_config_production_guards.py`): sin placeholders en `SECRET_KEY` /
    `FIELD_ENCRYPTION_KEY`, CORS sin `*` ni localhost,
    `RATE_LIMIT_FAIL_CLOSED`, docs apagados, OTP no `console`. No se agrega
    un default que deje pasar uno de estos en prod. `RATE_LIMIT_FAIL_CLOSED`
    cierra por política, no en bloque (`core/rate_limit.py::ACTION_POLICIES`,
    2026-09-24): sin Redis, `auth`, `public-write`, OTP y el lockout de login
    responden 503; `public-read`, `global` y el webhook de MP (que ya tiene
    HMAC, ventana e idempotencia) siguen abiertos con aviso a Sentry. Una
    acción de `enforce_rate_limit` sin política declarada falla cerrada. La URL de la base se lee
    en un solo lugar (`core/config.py::parse_db_url`, parámetro `ssl` de
    asyncpg, `require` si la URL no dice nada); las URLs locales y de CI
    llevan `?ssl=disable` explícito y compose lo toma de `POSTGRES_SSL`.
    `APP_DB_PASSWORD` no tiene default en el repo: compose y la migración de
    RLS fallan sin ella (`test_parse_db_url_unico.py`,
    `test_app_db_password_sin_default.py`). El header `x-raw-response` se
    ignora en producción (`test_raw_response_solo_fuera_de_produccion.py`).
    La API no hace DDL al arrancar: el esquema es de las migraciones
    (`test_sin_ddl_en_el_arranque.py`).
18. **Content-Type restringido a JSON** salvo el upload de medios
    (autenticado con Bearer, `core/security_middleware.py`). Es anti-CSRF:
    un endpoint form-encoded nuevo pasa por esa misma excepción.
19. **Entrada hostil**: `reject_control_chars` (NUL, bidi, zero-width,
    `core/validation.py`) en todo texto libre que se publica, lo tipee un
    anónimo o un admin (turnos, reserva y lista de espera públicas, tienda,
    personal, catálogo), validado al escribir
    (`test_texto_publicado_sin_control_chars.py`,
    `test_servicios_control_chars.py`); imágenes por magic bytes, tope de
    bytes y de píxeles, nunca SVG; asuntos de mail sin CRLF; fórmulas
    neutralizadas en CSV/Excel.
20. **Errores neutros hacia afuera**: `IntegrityError` → 409 genérico; el
    health check no filtra excepciones; mensajes de validación crudos no
    llegan al usuario final.

### Disponibilidad, hora y avisos al cliente (Fase 0, 2026-09-10)

- **Todo camino que cambia la agenda invalida el caché con
  `core/availability_cache.invalidate_availability`** (reservar, cancelar,
  liberar, reprogramar, expirar señas, crear/editar/borrar bloqueos). La clave
  lleva versión por (tienda, día local) y una generación por tienda: lo que
  cambia todos los días (editar o borrar un servicio) usa
  `invalidate_store_availability`. Las claves de versión y generación tienen
  TTL y se leen con `GETEX`, que lo estira; nunca `delete` a mano ni
  comodines. La invalidación recibe el cliente del Redis de caché
  (`core/redis.py::get_availability_cache`), nunca el de estado.
  (`test_cache_disponibilidad.py`,
  `test_generacion_de_cache_por_tienda.py`, `test_version_de_cache_expira.py`)
- **La hora que ve el cliente es hora argentina.** `start_time`/`end_time` de
  la disponibilidad y todos los mails se formatean con `ARGENTINA_TZ`;
  `starts_at`/`ends_at` siguen en UTC y el front manda el `starts_at` del
  slot tal cual, nunca recompone fecha + hora
  (`frontend/src/shared/utils/argentinaTime.ts`). La validación del horario
  del profesional compara en hora local. (`test_hora_local_reserva_publica.py`)
- **Mails al cliente**: "reserva registrada" al crear, "turno confirmado"
  desde `confirm()` y desde el pago acreditado; siempre best-effort tras el
  commit, nunca a un email técnico `.noreply` (`is_deliverable_email`).
  La reserva pública no espera al SMTP (F2-01, 2026-09-24): encola
  `send_booking_email` (cola `interactive`, la del OTP, `max_retries=0`) con
  `enqueue_registration_email`/`enqueue_confirmation_email`; por el broker
  viajan el tipo de mail, la tienda y el id del turno, nunca el email, y el
  worker relee el turno antes de mandar. El link de MP no se difiere.
  El panel tampoco manda en el request (F2-02): reservar, confirmar,
  completar y reprogramar (y reservar desde la lista de espera) publican
  `appointment.booked_by_panel`/`confirmed`/`completed`/`rescheduled` en el
  outbox en la MISMA transacción que el cambio de estado; el lote relee el
  turno y manda solo si sigue en un estado que haga cierto el aviso (hasta un
  tick, 20 s, de demora). (`test_mails_al_cliente.py`,
  `test_mails_del_panel_sin_transaccion.py`) Los helpers de `notifications/tasks.py` que
  mandan SMTP en línea se llaman `send_*`; una función `enqueue_*` tiene que
  encolar de verdad (`test_enqueue_encola_de_verdad.py`).
- **OTP solo por email** (SMTP existente); `whatsapp`/`sms` existen solo con
  `OTP_PROVIDER=console`. El envío se despacha después de la respuesta
  (`BackgroundTasks`) y, si el teléfono ya es de un cliente de la tienda con
  email entregable, el código va SOLO a ese email. Respuesta neutra ante
  fallo de envío. El front respeta la ventana de 30 minutos.
  (`test_otp_por_email.py`, `test_otp_email_del_cliente.py`)
- La reserva pública aplica `buffer_minutes` y congela `price_amount` como el
  panel.
- **Un turno en el pasado lo agenda solo la tienda** (propuesta por Mateo,
  adoptada por el dueño el 2026-09-25). El panel (`POST /appointments/` con datos de cliente y
  `PATCH /appointments/{id}/reschedule`) y `POST /waitlist/{id}/book` aceptan un
  inicio ya pasado para registrar a quien llegó sin turno o corregirlo: pasa por
  lock, bloqueos, choques y GiST igual que cualquier alta, pero no publica mail
  de reserva, confirmación ni reprogramación y no genera recordatorios. El cliente final nunca: la reserva pública, la reprogramación
  de "Mis turnos" y anotarse en la lista de espera rechazan todo inicio pasado,
  aunque la tienda tenga `min_booking_notice_hours = 0`. Los topes de fecha de
  reservar y reprogramar son solo contra el desborde
  (`core/utils.MAX_BOOKING_AHEAD`, 2 años hacia adelante y hacia atrás en la
  tienda): los 120 días del cliente los pone la grilla de `/public/availability`.
  Un tope más estricto es una decisión de producto, no un arreglo.
  (`test_cliente_final_sin_pasado.py`, `test_alta_del_panel_para_cliente.py`,
  `test_horizonte_de_reservas.py`, `test_recordatorios_solo_turnos_futuros.py`)

### Lista de espera, suscripción y avisos (Fases 4-7, 2026-09-11)

- **Ningún consumidor del outbox manda mail dentro de su transacción.** El
  lote toma las filas con `FOR UPDATE SKIP LOCKED`: un envío adentro deja el
  estado a merced del time limit de Celery y reenvía lo ya enviado. En la
  lista de espera el trabajo devuelve el mail pendiente y el llamador lo
  despacha después del commit (`OfferResult.pending_email`). En el outbox
  (`process_outbox_batch`, `payments/jobs.py`) cada mail (aviso al dueño,
  confirmación al cliente, cancelación por bloqueo y los eventos del panel
  `appointment.booked_by_panel/confirmed/completed/rescheduled`, F2-02) es su
  propia fila `email.send`, escrita en la transacción del evento que lo
  genera (F2-03, 2026-09-24). El despacho la reclama de a una
  (`processed_at` + commit plano, `SKIP LOCKED`) y recién después manda; lo
  que excede `OUTBOX_EMAIL_BUDGET_SECONDS` queda pendiente y sale en el tick
  siguiente (cada 20 s): ningún mail se pierde por presupuesto y
  `processed_at` no se reabre nunca. La entrega es **a lo sumo una vez**: un
  proceso que muere entre el reclamo y el DATA pierde ese mail, y un envío
  fallido no se reintenta (el DATA pudo haber llegado): queda con `attempts`
  y `error` en su fila. El estado del turno se relee al planificar el mail,
  no al mandarlo: un mail diferido por presupuesto puede salir después de
  una cancelación ocurrida entre medio.
  (`test_lista_de_espera_concurrencia.py`, `test_pg_outbox_mails.py`,
  `test_outbox_mails_diferidos.py`)
- **Un teléfono sin OTP no es de nadie.** No adopta el contacto de un cliente
  existente (`get_or_create_client(adopt_contact=...)`) ni trae su historial
  para la seña (`UNKNOWN_HISTORY`, que NO es "cliente nuevo"). Sin esa
  guarda, saber un número alcanzaba para recibir los mails de otra persona y
  para preguntarle al sistema si ese número es cliente y si faltó a turnos.
  (`test_secuestro_de_contacto.py`)
- **Un cobro con `deposit_rule` conserva su importe.** Regenerar el link
  desde el panel no re-tarifa: hacerlo dejaba el snapshot mintiendo y rompía
  para siempre la validación de importe del webhook.
- **Los recordatorios tienen etapas separadas de verdad**: el piso del de 24
  horas está por encima del lead del de 2 horas, y ningún aviso al cliente
  sale sin pasar por `is_deliverable_email`. El lote reutiliza una sesión
  SMTP (`smtp_session`, sondeada con `NOOP` antes de cada envío) y un envío
  fallido no se reintenta: el turno se libera
  (`test_recordatorios_sesion_smtp.py`).
- **Un rango liberado no es un turno.** Borrar un bloqueo devuelve un rango
  cuyos extremos no caen en la grilla: ese origen avisa al dueño, no le
  ofrece al cliente un horario inexistente (`ReleasedSlot.aligned_to_grid`).
- **Una tienda suspendida no escribe.** La guarda va a nivel router
  (`block_writes_when_suspended`) en TODOS los routers del panel, pagos y
  ledger incluidos, para que un endpoint de escritura nuevo nazca bloqueado;
  usa el usuario OPCIONAL porque esos routers tienen GET públicos. Lo que
  sigue permitido es una tabla explícita por verbo y ruta
  (`modules/billing/dependencies.py::SUSPENSION_ALLOWED_WRITES`:
  housekeeping que no genera obligaciones nuevas); permitir algo es
  agregarlo ahí con su motivo. Exentos por diseño: auth, ops, superadmin y
  el portal público, que no tiene usuario: ahí solo se bloquean crear una
  reserva y anotarse en la lista de espera
  (`reject_new_public_business_when_suspended`, mismo 404 que la vitrina);
  cancelar y reprogramar siguen. (`test_suspension_por_endpoint.py`)
- **Anotarse en la lista de espera es anónimo, así que tiene topes.**
  `MAX_OPEN_ENTRIES_PER_PHONE` (3) entradas abiertas por teléfono y tienda, y
  quien deja pasar `MAX_LAPSED_OFFERS` (2) ofertas expira solo
  (`waitlist_entries.lapsed_offers`). Sin eso una cola de entradas que nunca
  reservan mataba cada cupo liberado en ofertas de 10 minutos a nadie.
  (`test_lista_de_espera_acaparamiento.py`)
- **Un teléfono identifica a UN cliente por tienda**: índice único parcial
  `uq_users_client_phone_per_store` (`role = 'client' AND phone IS NOT NULL`;
  el personal puede compartir el teléfono del local). La migración que lo crea
  se detiene con el conteo si ya hay duplicados: no borra ni elige por nadie.
  El email de un cliente también es único POR TIENDA
  (`uq_users_client_email_per_store`, PV-01, 2026-09-25): el mismo email
  reserva en todas las tiendas que quiera, cada una con su ficha, y el 409 ya
  no dice a nadie si un email existe en otra tienda. Dentro de la tienda, un
  teléfono nuevo con el email de otro cliente sigue siendo 409 neutro (no se
  adopta la ficha por email). El email del personal sigue único global (regla
  16). El downgrade de `4b6d8f0a2c13` se detiene con el conteo si un email
  quedó en dos filas.

### Configuración y despliegue

21. **Un proceso con configuración inválida se muere.** La API tolera el
    respaldo de settings solo para responder 503 con detalle
    (`main.py::BootErrorMiddleware`; con settings de respaldo el lifespan no
    toca la base, `test_boot_error_lifespan.py`); Celery aborta en
    `worker_init`/`beat_init`. (2026-09-08: worker y beat corrían "ready"
    con base inválida.) El healthcheck de los dos workers es un archivo de
    latido: `core/celery_app.py` lo toca en cada `heartbeat_sent`
    (`/var/lib/shifty/worker-heartbeat`) y más de 120 s sin tocarlo es
    `unhealthy`. El latido lo emite el consumidor sobre su conexión al broker:
    solo late mientras esa conexión vive, así que sigue detectando un worker
    vivo que dejó de consumir (AUD2-C-09) sin levantar un Python por chequeo
    como `inspect ping`.
22. **Un solo bloque `x-app-environment` en compose** para `backend`,
    `celery_worker`, `celery_worker_interactive` y `celery_beat`;
    `test_compose_contract` exige paridad. Los cuatro corren UNA imagen,
    `ghcr.io/enriquemartinez26/shifty-backend:${APP_VERSION}`, que solo
    `backend` construye; después se recrean los cuatro juntos (recrear solo
    `backend` dejó a Celery con la imagen vieja, como root). Producción nunca
    construye (`build: !reset null` en `docker-compose.prod.yml`: la imagen
    sale de GHCR) y su borde es `nginx:1.27.5-alpine` con la config montada,
    no una imagen propia. Ningún servicio de la app monta el código del
    host sobre `/app`: corre la imagen, también en producción, donde un
    `volumes: []` del override no cancelaba el montaje porque compose fusiona
    listas (2026-09-24, `test_compose_contract`). Por lo mismo, lo que el
    override quita del base va con `!reset []` (así se despublican los puertos
    internos; en producción solo nginx publica) y el servidor necesita Docker
    Compose >= 2.24.
23. **`redirect_slashes=False`**: detrás de nginx el 307 pierde `/api` y el
    front recibe HTML. Cada `apiClient` usa la ruta exacta;
    `test_frontend_routes_contract` lo audita. Los errores propios del borde
    bajo `/api` tampoco son HTML: nginx responde JSON canónico
    (`UPSTREAM_UNAVAILABLE` para 502/503/504 con `Retry-After`,
    `REQUEST_TOO_LARGE` para 413, `RATE_LIMITED` para 429;
    `tests/unit/test_nginx_contract.py`).

- **Imágenes con versión y deploy por script.** CI construye y publica
  `ghcr.io/enriquemartinez26/shifty-{backend,frontend,nginx}:<sha>`
  (`.github/workflows/build-images.yml`); el VPS no construye, hace `pull`
  del sha (todo `up` y `run` lleva `--no-build`). `make deploy
  APP_VERSION=<sha>` corre `scripts/deploy.sh`: preflight (`COMPOSE_FILE` con
  `docker-compose.prod.yml`, Compose >= 2.24, disco, backup de menos de
  24 h), imágenes verificadas con `docker image inspect`, migración con el
  código viejo sirviendo, backend nuevo al lado del viejo, `up -d --no-deps
  --remove-orphans` con lista explícita (nunca recrea db, redis, rabbitmq ni el borde),
  compuerta de 60 s y rollback automático sin migrar. En un deploy normal el
  borde (nginx) solo se RECARGA (`nginx -t && nginx -s reload`); se recrea
  únicamente con `make deploy-edge`, cuando cambió su imagen o
  `nginx/nginx.prod.conf`. `docker-compose.prod.yml` exige `APP_VERSION` en todo comando
  de compose; no se fija en el `.env` del servidor (queda en
  `.deploy/current`).
- **Toda llamada externa dentro de un request tiene un presupuesto total
  menor que el `proxy_read_timeout` de nginx (30 s)**, y la conexión de la
  base se libera con commit plano antes de salir a la red (patrón B2-08).
  Hoy la reserva con seña puede pasarlo: el cliente ve 504 y la reserva se
  crea igual (R8-01); F1-04 y F1-05 lo cierran. Es regla para todo camino
  nuevo desde ya.
- **El host se opera con scripts versionados, no a mano**
  (`docs/DEPLOY_RUNBOOK.md` §8): backup diario con copia fuera del host
  (timer de systemd, `scripts/backup.sh`), guard que reinicia contenedores
  `unhealthy` con tope de 3 por contenedor y 6 en total por hora, sin tocar
  db ni rabbitmq ni reiniciar nada con db o redis_state caídos (sin
  `autoheal` ni `docker.sock`),
  chequeos horarios de NTP, certificado, disco y memoria, y latencia por
  ruta cada 5 minutos. Se prueban con binarios falsos
  (`tests/unit/host_falso.py`).

### Tiempo

24. Persistencia y cálculo en UTC; la hora local es presentación
    (`core/utils`: `ARGENTINA_TZ`, `local_to_utc`, `today_local`,
    `local_day_start`; reportes y panel cortan el día con estos). Nunca
    `datetime.now()` sin `timezone.utc`. "Un día" de negocio es aritmética
    de calendario con zona, no `timedelta(hours=24)`; Argentina hoy no
    aplica DST y el código no debe depender de eso.

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
28. Cobertura con trinquete por capa (`jest.config.js`): se mide todo
    `src/` y cada carpeta (`domain`, `application`, `infrastructure`,
    `shared`, `presentation`) tiene su piso en lo medido; se sube, no se
    baja. `npm audit --omit=dev --audit-level=low` limpio. Token de acceso en memoria, nunca
    `localStorage`. `import.meta` solo en `runtime-env` /
    `shared/utils/env` (ts-jest no lo compila).

### Tamaño y forma

29. **Función de más de 80 líneas necesita justificación en el PR.** En el
    backend quedan 11 al 2026-09-25 (AST, `end_lineno - lineno + 1 > 80`,
    sin `tests/` ni `alembic/`): `_build_store_notification` y
    `_claim_and_expire_preferences` (`payments/jobs.py`), `book_for_client` y `_find_suggestion`
    (`appointments/service.py`), `availability.get_available_slots`,
    `ledger/router.py::get_ledger_summary`,
    `stores/router.py::update_my_store`,
    `core/security_middleware.py::__call__` y tres en `scripts/`.
    `process_outbox_batch`, `OtpService.request_code` y
    `_expire_unpaid_appointments` ya bajaron del tope.
    Son deuda, no permiso. `create_public_booking` y `client_reschedule_appointment`
    se descompusieron (B1-12). El front no está medido acá. Ante una
    validación nueva se extrae, no se apila.

## 4. Qué cuenta como verde (y qué no)

- **Verde en SQLite no prueba concurrencia, RLS, el trigger de estados ni
  la exclusión GiST.** Toda la suite de integración corre en SQLite en
  memoria. Los tres incidentes más caros de 2026-09 (Celery sin correr,
  redirect que devolvía HTML, CI en rojo un mes) pasaban la suite. El job
  `backend-postgres` corre `tests/postgres/` contra Postgres real; todo
  cambio que toque estados, disponibilidad, RLS, jobs o migraciones lleva
  su prueba ahí o se prueba además contra el contenedor local y se pega la
  evidencia.
- **Todo endpoint que reserva, cobra o cambia estado tiene prueba de
  ráfaga** (N idénticas y N sobre el mismo slot a la vez): 1 éxito, N-1
  conflictos, cero 5xx.
- **Un bug de producción se reproduce con un test antes de arreglarse**,
  con fecha y síntoma en el comentario.
- **Un pipe a `tail` esconde el exit code.** `mypy . | tail -1 && pytest`
  corre pytest aunque mypy falle: el estado del pipeline es el de `tail`.
  Los comandos del gate se encadenan sin pipe, o se lee `$?` del comando que
  importa. (2026-09-11: cuatro errores de mypy pasaron tres fases así.)
- **CI es la verdad.** Si local pasa y CI falla, la diferencia es el bug
  (caché de ESLint, CRLF, `node_modules` viejo, `import/order`). Antes de
  cada push: `ruff format --check`, `ruff check`, `mypy`, `pytest`;
  `npm run check`, `jest`, `build`. Los pasos de CI se replican con los
  mismos comandos, no con aproximaciones.
- No se apilan pytest + mypy + builds a la vez en la máquina de
  desarrollo: la degradan y falsean tiempos.

## 5. Huecos conocidos: no asumir que están aplicados

- La única protección viva de capas del front es ESLint.
  `frontend/scripts/verify-clean-architecture.ts` era código muerto (sin
  cablear y sin pasar `tsc`) y se borró el 2026-09-24 al poner `scripts/`,
  `e2e/` y las configs bajo `tsc` y ESLint (`tsconfig.node.json`, F12-04).
- `docs/ROLE_MATRIX.md`, `docs/DOCUMENTACION_TURNERO.md` y
  `docs/SETUP_GUIDE.md` declaran deriva contra el código
  (`docs/AUDIT_MATRIX_SHARED.md`), en particular los permisos de
  `/reports/professionals` y `/reports/summary|export`. Para un cambio de
  permisos se verifica en código, no en la doc.
- El pre-commit hook (`.githooks/pre-commit`) **solo corre si cada clon hace
  `git config core.hooksPath .githooks`** (activado en el clon de Enrique el
  2026-09-22; en el clon del backend no lo estaba). Corre `verify-toolchain`
  más `npm run check`; los checks de backend se omiten si `uv` no está en el
  PATH local, porque corren en Docker/CI. `verify-toolchain` acepta el
  CONJUNTO soportado, no una versión única (Node 24.18.0 o 26.5.0, npm
  11.16.0 u 11.17.0, igual que `engines` de `frontend/package.json`) y valida
  Node y npm por separado, así que también deja pasar combinaciones que CI no
  ejercita (Node 24.18.0 con npm 11.17.0). En una máquina fuera de ese
  conjunto (2026-09-16: 24.16.0) el hook bloquea todos los commits y `npm ci`
  necesita `--engine-strict=false`: el toolchain se alinea antes de
  activarlo.
- Nombres de contenedor: las réplicas del backend son
  `<proyecto>-backend-N` (sin `container_name`, F0-04); el resto,
  `${COMPOSE_PROJECT_NAME:-shifty}_<servicio>`. Scripts, docs y comandos usan
  `docker compose exec backend ...`, nunca `shifty_backend`: ese nombre ya no
  existe y con un segundo proyecto (staging) apuntaría al equivocado.
- El E2E con Playwright (`frontend/e2e/`, `npm run e2e`, workflow manual
  `e2e.yml`) corrió por primera vez el 2026-09-16 contra el stack local
  detrás de nginx (`E2E_BASE_URL=http://localhost`,
  `E2E_API_URL=http://localhost/api`, `E2E_NO_WEBSERVER=1`, tienda de
  carga `load-1789010879`). Dos trampas: el contenedor `frontend` sirve un
  **build estático** (cambios del front exigen `docker-compose build
  frontend`), y el `CORS_ORIGINS` del compose solo admite el origen de nginx,
  así que el vite dev server en :5173 ve "Negocio no encontrado".
- Ya cubierto (2026-09-10): job `backend-postgres` en CI (RLS, exclusión
  GiST, triggers y migraciones desde base vacía, en `tests/postgres/`);
  SAST con CodeQL + escaneo de secretos con gitleaks (`.gitleaks.toml`);
  prueba de carga/abuso versionada (`backend/scripts/load_test_booking.py`).
- Ya cubierto EN EL REPO (2026-09-24, Fase 0 del plan de rendimiento):
  backup diario con copia fuera del host y alerta de frescura, deploy con
  migración previa, backend gradual y rollback, guard de `unhealthy`,
  chequeos del host, latencia por ruta, imágenes por sha en GHCR
  (`docs/DEPLOY_RUNBOOK.md`); el contrato del borde vive en
  `tests/unit/test_nginx_contract.py`. En el VPS nada de eso corre hasta que
  el dueño hace la preparación de `docs/DEPLOY_RUNBOOK.md` §1: crear el
  bucket, instalar rclone y certbot, `docker login ghcr.io`, copiar
  `/etc/shifty/ops.env` y habilitar el timer y los cron. Hasta entonces el
  RPO de 24 h sigue sin cumplirse.
- Falta todavía: activar el pre-commit hook en cada clon que falte (`git
  config core.hooksPath .githooks`, con el toolchain alineado); descomponer
  las 11 funciones de más de 80 líneas que quedan en el backend (regla 29);
  zona horaria por tienda; migrar los commits de routers/repos que quedan en
  `COMMITS_DECLARADOS_FUERA_DE_SERVICE` al patrón de `appointments`; medir
  la cobertura del backend en CI (`fail_under = 80` en `pyproject.toml`,
  pero CI corre `pytest` sin `--cov`); probar la cadena completa de
  downgrades (regla 13); pasar CodeQL a bloqueante cuando el ruido inicial
  esté limpio; correr por primera vez el drill mensual de backup (secretos
  `BACKUP_DATABASE_URL`/`DRILL_DATABASE_URL` y un runner propio o staging:
  con `ports: !reset []` la base no se alcanza desde GitHub) y confirmar ahí
  el restore del rol `shifty_app` en un cluster vacío. Cerrado el
  2026-09-16: N+1 en `get_available_slots` (auditado, no había), teléfono
  único por tienda y primera corrida del E2E.
  Cerrado el 2026-09-19: descomposición de `create_public_booking` y
  `client_reschedule_appointment` y migración de `public_api` al service
  (B1-12). Cerrado el 2026-09-22: el pre-commit hook quedó activado en el
  clon de Enrique. Cerrado el 2026-09-25: email de cliente único POR tienda
  (PV-01, regla 16).

## 6. Compuertas de proceso

- Pre-commit: verificación de toolchain, `npm run check`, `ruff
  format/check` + `mypy`. Cero warnings es la línea base, front y back.
- CI (`quality.yml`): `standards` (formato + lint + tipos + dead-code) y
  `contract-and-migrations` (head único de Alembic con
  `test_migrations.py`, `app.openapi()` importa limpio) gatean a backend,
  integración, `backend-postgres` y los dos jobs de front; `dead-code`
  espera solo a `standards` y `secret-scan` (gitleaks) corre suelto. El
  front corre con cobertura; el backend no la mide (ver §5).
  `build-images.yml` publica las imágenes en cada push a `main`; no gatea
  PRs.
- **Todo cambio de endpoint regenera `docs/API_CONTRACT.md` en el mismo
  commit.** El contrato sale de `app.openapi()` con
  `backend/scripts/gen_api_contract.py`, nunca a mano;
  `tests/architecture/test_api_contract_doc.py` falla si el cuerpo commiteado
  difiere (ignora el pie con fecha y commit; en CI no se saltea) y si dos
  operaciones comparten `operationId`. Se genera desde el código del working
  tree, nunca con `docker compose exec`: los contenedores corren la imagen del
  último build, sin bind mount (§3, regla 22). Con uv, desde `backend/`:
  `uv run python scripts/gen_api_contract.py`. Sin uv, desde la raíz:
  `MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -v ./backend:/src -w
  /src backend /app/.venv/bin/python scripts/gen_api_contract.py --stdout
  --commit $(git rev-parse --short HEAD) > docs/API_CONTRACT.md`. El código se
  monta en `/src` y no en `/app` porque montarlo sobre `/app` tapa el `.venv`
  de la imagen (`/app/.venv`) y falla con `No module named 'fastapi'`.
- `docs/RELEASE_CHECKLIST.md` y `docs/BACKUP_RESTORE_RUNBOOK.md` (RPO ≤24h,
  RTO ≤4h) gatean releases: un ítem sin marcar necesita excepción explícita
  del dueño, no un salto silencioso. El deploy a producción es
  `make deploy APP_VERSION=<sha>` (`docs/DEPLOY_RUNBOOK.md`), que además se
  niega a migrar sin un backup de menos de 24 h.
