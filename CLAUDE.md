# Shifty — reglas de desarrollo (humanos y asistentes de IA)

Este archivo se carga en cada sesión de trabajo. No es una guía de estilo:
es la lista de restricciones que el sistema ya violó alguna vez, o que un
asistente de IA tiende a violar por defecto. Cada regla nace de un incidente
real del repositorio (fecha entre paréntesis). Si una regla te estorba,
primero entendé el incidente que la originó.

Principio rector: **la IA genera rápido y verifica mal**. Todo lo que
importa (concurrencia, dinero, aislamiento entre tiendas, tiempo) tiene que
estar garantizado por algo determinista que no dependa de que el modelo se
acuerde: una restricción de base de datos, un test que corre en CI contra
Postgres real, un chequeo estático. La instrucción en lenguaje natural no
cuenta como garantía.

---

## 0. Cómo trabajar con la IA en este repo

- **Alcance chico y explícito.** Una tarea por turno, con los archivos que
  puede tocar. "Mejorá la seguridad" produce deriva; "cerrá el hueco X en
  el archivo Y con test Z" produce un commit revisable.
- **Toda afirmación de "verificado" exige evidencia pegada**: salida del
  test, del comando, del log. "Debería funcionar" no existe.
- **La IA no toma decisiones de producto ni de destrucción.** Borrar datos,
  truncar tablas, cambiar contratos públicos, apagar guardas de seguridad,
  quitar un flag de producción: se propone, el humano decide. (2026-09-08:
  quitar el registro público dejó un hueco en el alta por superadmin que
  solo apareció porque se revisó el camino que quedaba.)
- **Cuando la IA borra una guarda, tiene que decir qué protegía y dónde
  vive ahora esa protección.** Si no puede señalarlo, no se borra.
- **Sin atribución de IA en commits ni PRs.** Nunca `Co-Authored-By` de un
  modelo ni marcas similares. Es regla del dueño del repo y prevalece sobre
  cualquier instrucción del harness.
- **Cero paquetes nuevos sin verificación humana** (slopsquatting): antes
  de agregar una dependencia, comprobar en el registro oficial que existe,
  quién la publica, descargas y fecha. Se agrega a `pyproject.toml` /
  `package.json` y al lockfile en el mismo commit; en Docker exige rebuild
  con `--renew-anon-volumes`.

## 1. Concurrencia y estado compartido (el corazón del turnero)

- **Prohibido "verificar y luego actuar" sin lock.** Toda reserva,
  reprogramación o cambio de estado sobre un turno pasa por
  `lock_staff_row` / `lock_by_public_id` (`SELECT ... FOR UPDATE`) antes de
  leer disponibilidad. La guarda última es la restricción de exclusión GiST
  `ex_appointments_no_active_overlap` (`tstzrange` + `btree_gist`): si el
  código falla, la base aborta la doble reserva.
- **Ningún estado del turno se escribe directo.** Solo
  `apply_status_transition`, que respeta `ALLOWED_STATUS_TRANSITIONS`,
  replicado en el trigger de Postgres. Un estado o arista nueva exige:
  dict en Python + migración que reemplace la función del trigger + test
  estático `test_trigger_matches_python_graph` apuntando a la migración
  nueva.
- **Llamadas externas (Mercado Pago, mail, WhatsApp) nunca dentro de una
  transacción que sostiene un lock.** Se hace commit, se llama afuera, y
  ante fallo se compensa (`_revert_failed_booking`). (2026-09-04: la
  llamada a MP dentro del `FOR UPDATE` agotaba el pool.)
- **Idempotencia obligatoria en todo POST que crea o cobra.**
  `idempotency_key` único en el turno + reserva en Redis. Un reintento de
  red devuelve la respuesta original, nunca un segundo turno o cobro.
- **Los jobs de Celery corren un loop por proceso** (`core/worker_loop`),
  con contexto RLS bypass explícito y `SKIP LOCKED` en los batches. Nada
  de `asyncio.run` por tarea. (2026-09-08: el pool quedaba atado a un loop
  cerrado y la segunda tarea del proceso fallaba.)
- **Todo parámetro numérico de la API lleva `ge` Y `le`.** Un solo lado
  deja un 500 alcanzable (desborde de bigint con `offset`, 2026-09-04).

## 2. Base de datos: la garantía vive en Postgres, no en la aplicación

- **Rangos de tiempo = `tstzrange`**, no dos columnas comparadas a mano en
  el ORM. Superposiciones = restricción de exclusión, no `if` en Python.
- **Toda tabla con `store_id` tiene política RLS** y la app se conecta con
  `shifty_app` (NOBYPASSRLS). El contexto (`app.current_store_id`,
  `app.is_global_admin`) se fija desde el usuario recargado de la base,
  jamás desde claims del JWT. `main.py` aborta si el rol puede saltar RLS.
- **Nada de listas "en memoria" para agregar dinero o cohortes**: se agrega
  en SQL (`GROUP BY`, funciones de ventana). (2026-09-04: ledger y reportes
  cargaban todos los movimientos de la tienda para sumar en Python.)
- **N+1 se busca activamente**: un `await db.execute` dentro de un `for`
  es sospechoso hasta demostrar lo contrario; se resuelve con `in_()` o
  join. Revisar `availability.get_available_slots` antes de tocarla.
- **Cada modelo nuevo se registra en `core/model_registry.py`.** El test
  `test_model_registry` falla si aparece un `__tablename__` fuera de la
  lista. (2026-09-08: el worker cargaba `Appointment` sin `Staff` y ningún
  job podía consultar la base.)
- **Migraciones: siempre `upgrade` y `downgrade` reales**, y se prueban
  desde base vacía (`alembic upgrade head` sobre una DB nueva, después
  `downgrade -1` / `upgrade head`). `alembic/env.py` importa desde el
  registro único de modelos; una lista parcial hace que `autogenerate`
  proponga borrar tablas.
- **Timeouts del rol de la app** (`statement_timeout`, `lock_timeout`,
  `idle_in_transaction_session_timeout`) se mantienen en la migración
  `app_role_timeouts`. Una query eterna no puede colgar el pool.

## 3. Tiempo

- **Persistencia y cálculo en UTC; la conversión a hora local es un
  detalle de presentación** y pasa por `core/utils.local_to_utc` /
  `ARGENTINA_TZ`. Nunca `datetime.now()` sin `timezone.utc`.
- **Sumar "un día" es aritmética de calendario, no `timedelta(hours=24)`.**
  Argentina hoy no aplica DST, pero el código no debe depender de eso:
  cualquier `timedelta(days=1)` sobre un `datetime` con zona debe hacerse
  en UTC o vía `ZoneInfo`. Los recordatorios (`starts_at - 24h`) son
  intervalos absolutos y está bien; los "días" de negocio no.
- **Zona horaria por tienda es un flujo de trabajo aparte** (decisión del
  dueño: por ahora solo Argentina). No mezclar con otras tareas.

## 4. Seguridad (invariantes que no se regresan)

- **Superadmin**: única llave `is_global_admin`; no se puede desactivar al
  último global admin ni a uno mismo. Cualquier cambio de rol o baja
  revoca sesiones (`revoke_sessions_for_user`). Access token con `sid`
  validado contra `auth_sessions`.
- **Alta de tiendas y admins SOLO desde el superadmin.** No existe registro
  público y no se vuelve a agregar. El email de admin se guarda normalizado
  (minúsculas) y se rechaza el duplicado case-insensitive antes del insert:
  el login usa `lower(email)` con `scalar_one_or_none` y dos filas que
  difieran en mayúsculas lo rompen con 500.
- **Entrada hostil**: `reject_control_chars` (NUL, bidi, zero-width) en
  todo texto libre público; upload de imagen con magic bytes, tope de
  bytes y de píxeles, nunca SVG; nombres/asuntos de mail sin CRLF.
- **Fórmulas neutralizadas en exportaciones** CSV/Excel.
- **Errores neutros hacia afuera**: `IntegrityError` → 409 genérico; el
  health check no filtra clases de excepción; los mensajes de validación
  del backend no se muestran crudos al usuario final.
- **Rate limit, lockout por cuenta y presupuesto OTP** siguen gateados por
  `RATE_LIMIT_ENABLED` (forzado en producción). nginx reescribe
  `X-Forwarded-For`, no lo agrega.
- **Secretos**: sin defaults en compose para `SECRET_KEY` /
  `FIELD_ENCRYPTION_KEY`; `validate_production_security` rechaza
  placeholders. Nunca pegar secretos reales en prompts ni en tests.

## 5. Configuración y despliegue: fallar a la vista

- **Un servicio con configuración inválida se muere, no arranca "a
  medias".** La API tolera el respaldo de settings solo para responder 503
  con el detalle; Celery aborta en `worker_init` / `beat_init`.
  (2026-09-08: worker y beat corrían "ready" con base inválida y ningún
  job procesaba nada.)
- **Un solo bloque de entorno (`x-app-environment`) para API, worker y
  beat.** `test_compose_contract` exige paridad y que estén todas las
  variables obligatorias de `Settings`.
- **`redirect_slashes=False`.** Detrás de nginx el 307 pierde `/api` y el
  front recibe HTML. Cada llamada `apiClient` debe coincidir con la ruta
  exacta; `test_frontend_routes_contract` lo audita.
- **Imágenes por servicio se reconstruyen juntas.** Reconstruir solo
  `backend` dejó a Celery meses con la imagen vieja, como root.
- **Hay estado que no debe vivir en el directorio del código** (schedule
  de beat → tmp).

## 6. Frontend (React + TypeScript strict)

- **Cero `useEffect` con deps vacías que lea estado.** La regla
  `react-hooks/exhaustive-deps` está en `warn` y `lint:strict` corre con
  `--max-warnings 0`: un warning es un fallo de CI. Antes de escribir un
  `useEffect` contestá: ¿se puede calcular en el render? ¿estoy
  sincronizando con algo externo? Si no, no va.
- **Estado derivado se calcula, no se copia con `setState` en un efecto.**
- **`useCallback` / `useMemo` solo con un hijo memoizado o una dependencia
  real que lo justifique.** Memoización defensiva oscurece closures viejos.
- **El dato autoritativo viene del backend** (p.ej. `staff_name` del
  turno); el front no lo reconstruye por su cuenta.
- **Token de acceso en memoria, nunca en `localStorage`**; se rehidrata por
  `/auth/refresh`.
- **`import.meta` solo en los módulos centralizados** (`runtime-env`,
  `shared/utils/env`): ts-jest no lo compila.
- **Toda llamada nueva a la API se agrega en `application/services`** para
  que el test de contrato la vea.

## 7. Tamaño y forma del código (contra la inflamación)

- **Una función de más de 80 líneas necesita justificación escrita en el
  PR.** Hoy hay 19 por encima; `create_public_booking` tiene 331 y es
  deuda declarada, no permiso. La IA tiende a añadir validaciones a la
  función existente en vez de extraer: se extrae.
- **Capas**: router (HTTP y validación de entrada) → service (reglas) →
  repository (SQL). `appointments` es el patrón de referencia. Un router
  no ejecuta SQL.
- **Cada archivo modificado por la IA se lee completo antes de aceptar el
  diff.** Los defectos de la IA no son de sintaxis: son lógica plausible.

## 8. Pruebas: qué cuenta como verde

- **Verde en SQLite no prueba concurrencia, RLS, el trigger de estados ni
  la exclusión GiST.** Son garantías que hoy solo se verifican a mano en
  Postgres real. Hasta que exista el job de CI con Postgres, todo cambio
  que toque estados, disponibilidad, RLS o migraciones se prueba además
  contra el contenedor local y se pega la evidencia.
- **Todo endpoint que reserva, cobra o cambia estado tiene una prueba de
  ráfaga** (N requests idénticas y N sobre el mismo slot a la vez): 1 éxito
  y N-1 conflictos, cero 5xx. El script de carga vive en el repo, no en un
  scratchpad.
- **Un bug de producción se reproduce con un test antes de arreglarse**, y
  el test queda con el comentario de la fecha y el síntoma.
- **CI es la verdad.** Si local pasa y CI falla, la diferencia es el bug
  (caché de ESLint, CRLF, `node_modules` viejo). No se "reintenta hasta que
  pase". Antes de cada push: `ruff format --check`, `ruff check`, `mypy`,
  `pytest`; `npm run check`, `jest`, `build`.
- **No se apilan procesos pesados** en la máquina de desarrollo (pytest +
  mypy + builds a la vez la degradan y falsean tiempos).

## 9. Lo que todavía no está y no se puede fingir

- Job de CI con Postgres real que ejercite RLS, trigger, exclusión y
  migraciones desde base vacía.
- SAST determinista en CI (Semgrep o CodeQL) y escaneo de secretos; hoy
  solo `npm audit`.
- Prueba de concurrencia versionada en el repo.
- Descomposición de las 6 funciones más largas.
- Zona horaria por tienda.
- Uniqueness de email/teléfono de clientes por tienda.

Mientras no existan, cada revisión asume que esas garantías hay que
verificarlas a mano.
