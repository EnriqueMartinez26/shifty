# Inventario de integración backend → front · `integration/aud2`

Fecha: 2026-09-24. Pedido por Enrique (dueño del front). Solo lectura sobre el repo; no se corrió ningún gate.

- **Base de comparación:** `git merge-base origin/main integration/aud2` = `e63d107` (= punta de `origin/main`). Todo diff es `e63d107..HEAD`.
- **HEAD:** `fff4a22`. 521 commits, 458 archivos. `frontend/src` **no cambia** en el rango (el front de la rama es el de `main`); el único archivo de `frontend/` tocado es `frontend/nginx.conf`.
- **Columna "Consumidor en el front":** `archivo:línea` bajo `frontend/src` (búsqueda con `rg`), o "nadie".
- **Columna "¿Front?":** `sí` (hay que cambiar el front), `no` (no le afecta), `ya lo cubre` (el front actual ya se comporta bien).
- Se reusa y verifica la devolución a Enrique del 23-09 y la revisión funcional del front (`docs/REVISION_FUNCIONAL_FRONT.md`, hallazgos `FF-xx`, re-verificada contra `9214b37`). Donde este inventario los corrige, lo dice con evidencia.

---

## 0. Lo que el front tiene que hacer (resumen)

| # | Cambio en el front | Por qué | Sección |
|---|---|---|---|
| 1 | No reintentar ningún 409 (hoy `client.ts:79-84` reintenta 409 que no sean POST, 3 veces con 2/4/8 s) | Los 409 de negocio nuevos (bloqueo con turnos, ventana de reprogramación, slug, email) tardan 14-17 s en verse (FF-01) | C |
| 2 | Leer `error_code` desde `ApplicationError.context.errorCode` y mapear 402/429/503 a clases propias | Hoy 402 `SUBSCRIPTION_SUSPENDED`, 429 `RATE_LIMITED`, 503 `UPSTREAM_UNAVAILABLE`/`RATE_LIMIT_UNAVAILABLE` salen como `InternalServerError` (FF-02) | C |
| 3 | Sacar la opción `admin` del selector de rol para el admin de tienda; tratar 409 de email duplicado | 403 `PERMISSION_DENIED` / 409 `RESOURCE_CONFLICT` | J6 |
| 4 | Horarios del local: un período por día, `open < close`, ocultar "+ Bloque" | 422 `VALIDATION_ERROR` | J1 |
| 5 | Seña: monto > 0, porcentaje ≤ 100, 2 decimales en precio y seña | 422; además hay un CHECK en la base | J3 |
| 6 | Ocultar "Exportar" al profesional | 403 `PERMISSION_DENIED` | J2 |
| 7 | Fiado: paginar con `limit`/`offset` y usar `total`; orden nuevo → viejo | Hoy se ven solo 50 sin aviso | J4 |
| 8 | Reportes: paginar el detalle con `has_more` o avisar "mostrando N de total" | Default 2000 filas | J5 |
| 9 | Editar bloqueo: manejar 409 `BLOCK_HAS_APPOINTMENTS` y reintentar con `cancel_affected: true` (solo admin) | El PATCH ahora sigue el mismo contrato que el alta | C |
| 10 | Reprogramar desde "Mis turnos": mostrar 409 `CANCELLATION_WINDOW_EXPIRED` | Reprogramar ahora respeta la ventana de cancelación | C |
| 11 | Usuarios: `''` → `null` y PATCH solo con lo que cambió | `null` ahora borra; `''` da 422 (FF-10) | E |

---

## A. Rutas

Verificación estática: se compararon las 133 rutas del backend en HEAD contra las 132 de `main` (decoradores `@router.<verbo>("…")` con su `prefix`) y se cruzaron las 116 llamadas `apiClient.*`/`this.client.*` de `frontend/src/**/*.ts` contra método + ruta del backend. **Todas las llamadas del front existen con el mismo método y la misma barra final.** Las dos que el cruce no resolvió solo son artefactos del script: `GET /me` está en `backend/main.py:535` y `` `/superadmin/stores${query}` `` normaliza a `/superadmin/stores`, que existe.

| Commit | Archivo | Cambio (antes → después) | Consumidor en el front | ¿Front? |
|---|---|---|---|---|
| 028f4b1 | `backend/modules/reports/router.py:158` | Ruta nueva `GET /reports/audit-logs` (`limit` 1..100, default 50; `offset` 0..10000; `resource_id` opcional con patrón de id público). Solo admins (`STORE_MANAGERS`). | nadie (el front usa `/superadmin/stores/{id}/audit-logs`, `SuperAdminService.ts:280`, que no cambió) | no |
| — | todas | Sin rutas borradas ni renombradas. Sin cambios de barra final. `redirect_slashes=False` sigue en `backend/main.py:170`. | — | no |
| cbc10cc | `backend/core/router.py`, `backend/core/responses.py:75-85` | `x-raw-response: true` deja de desenvolver el sobre en producción (antes lo hacía para cualquiera, en `CanonicalRoute`). | nadie (`rg x-raw-response frontend/src` vacío) | no |

**Límite del test de contrato.** `backend/tests/unit/test_frontend_routes_contract.py` (sin cambios en el rango) solo falla si una llamada del front difiere de una ruta **únicamente por la barra final**, y solo mira archivos `.ts` (no `.tsx`; hoy no hay llamadas en `.tsx`). No detecta una llamada a una ruta inexistente ni un verbo equivocado. El cruce de arriba cubre eso a mano; si se quiere como garantía, el test puede afirmar también `(método, ruta) ∈ openapi`.

---

## B. Schemas de request/response que usa el front

| Commit | Archivo | Cambio (antes → después) | Consumidor en el front | ¿Front? |
|---|---|---|---|---|
| c49539f | `backend/modules/stores/schemas.py:45-57` | `BusinessHourPeriod.open/close`: `str` con patrón `^\d{2}:\d{2}$` → `time` + `open < close` (422 si no). `"99:99"` pasaba a 500 y ahora es 422. La salida sigue siendo `"HH:MM"`. | `StoreSettingsService.ts:125` (PATCH `/stores/me`), editor en `Settings.tsx:943-1038` | sí (J1) |
| e27be5c | `backend/modules/stores/schemas.py:141-156` | `business_hours` con más de un período en un día → 422 "Por ahora cada dia admite un solo periodo de apertura" (antes guardaba solo el primero y respondía 200). | `Settings.tsx:1024-1038` ("+ Bloque") | sí (J1) |
| 20673f5, c15b801 | `backend/modules/stores/router.py` | Slug duplicado: 400 `SLUG_ALREADY_IN_USE` → 409 `RESOURCE_CONFLICT` "El registro entra en conflicto con uno existente." (lo decide el UNIQUE, no un pre-chequeo). | `StoreSettingsService.ts:125`; texto en `Settings.tsx:245-247` vía `getErrorMessage` | sí (decir "ese slug ya está en uso") |
| 839ce31 | `backend/modules/superadmin/schemas.py` | `primary_color` en alta y edición de tienda del superadmin: `max_length=20` → patrón hex `^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$`. | `SuperAdmin.tsx:298`; hay un input de texto libre en `superadmin/StoreModals.tsx:101` además del `type="color"` | sí (validar hex o mostrar el 422) |
| ae15ac8 | `backend/modules/services/schemas.py:47-64`, `services/router.py:113-131` | Terna de seña validada como un dato: `percent` ≤ 100; `deposit_mode != none` y `deposit_type != full` exige `deposit_amount > 0`. POST: 422 Pydantic; PATCH: se mezcla con la fila guardada y da 422 `VALIDATION_ERROR`. | `service.validators.ts:26-49`, `ServiceFormModal.tsx:283,310-314`, `HttpServiceRepository.ts:40,57` | sí (J3) |
| cb2cb41 | `backend/modules/services/schemas.py:32-44` | `price` y `deposit_amount` con más de 2 decimales → 422 "el importe admite hasta 2 decimales". | ídem | sí (J3) |
| a5fcd1c | `backend/modules/services/schemas.py:129-136` | PATCH: `null` en `name`, `duration_minutes`, `price`, `deposit_mode`, `deposit_type`, `is_active` → 422 "`<campo>` no puede ser null". | `HttpServiceRepository.ts:57` (manda solo lo definido, `ServiceMapper.ts:60-80`) | ya lo cubre |
| 9bdc57a, a0a2293 | `backend/modules/services/router.py` | `GET /services/` acepta `include_inactive` (default `false`; `true` solo admin → 403), `limit` 1..500 (default 500), `offset` 0..1.000.000. Sin parámetros responde lo mismo que antes. | `HttpServiceRepository.ts:22` (sin parámetros) | no (FF-22 lo propone para "Reactivar") |
| f7c8cbf | `backend/modules/ledger/router.py:175-207`, `ledger/schemas.py:28-34` | `GET /ledger/customers/{id}`: `limit` 1..200 (default 50), `offset` 0..100.000; respuesta suma `total`; orden `created_at` **descendente** (antes ascendente y sin tope). | `LedgerService.ts:43`, `Ledger.tsx:250` | sí (J4) |
| f08c516 | `backend/modules/ledger/schemas.py` | `LedgerMovementCreate.appointment_id` exige patrón de id público. | `LedgerService.ts:53` | no |
| c88d2dc, 73c31b3 | `backend/modules/reports/router.py:65-66`, `reports/schemas.py:91` | `GET /reports/summary`: `limit` 1..5000 (default 2000), `offset` 0..100.000, solo sobre `appointments`; respuesta suma `has_more`. `stats` sigue siendo del rango completo. | `ReportsService.ts:115` (no manda `limit`; `ReportSummary` en `:62-71` no declara `has_more`) | sí (J5) |
| 82106e3, ed55e25 | `backend/modules/reports/schemas.py` | `stats` suma `retained_deposit_revenue`, `absent_appointments`, `expired_appointments` (con default; aditivos). | nadie los lee en `ReportSummaryStats` | no (opcional mostrarlos) |
| 028f4b1 | `backend/modules/reports/schemas.py` | Nuevo `AuditLogItem` (`id`, `created_at`, `actor_email`, `resource_type`, `resource_id`, `action`, `payload_before`, `payload_after`). | nadie | no |
| 3009d73 | `backend/modules/appointment_blocks/schemas.py` | `AppointmentBlockUpdate` suma `cancel_affected: bool = false`. | `AppointmentBlocksService.ts:102`; edición en `CalendarContainer.tsx:465-477` no lo manda | sí (C, FF-11) |
| 764b092 | `backend/modules/appointment_blocks/schemas.py:19-36` | Un bloqueo no puede durar más de 366 días → 422. | `AppointmentBlocksService.ts:86,91,102` | no (la UI no llega; verificado en FF) |
| 363fa66 | `backend/modules/payments/schemas.py`, `payments/application.py:144-149` | `POST /payments/{id}/refund` exige `manual: true`; si no, 422 "Shifty solo registra reembolsos hechos fuera de Shifty…". | `Payments.tsx:62` manda `manual: true` | ya lo cubre |
| 71c1658 | `backend/modules/promotions/schemas.py` | `value` y `min_service_amount` con `le=10_000_000`. | `PaymentsService.ts:172,180` | no |
| 709f26d | `backend/modules/public_api/schemas.py` | `starts_at` / `new_starts_at` sin zona se toman como UTC (antes, hora local del proceso). | `PublicBookingService.ts:265,308` (manda con offset) | ya lo cubre |
| e9bbd99 | `backend/modules/public_api/schemas.py` | `ClientCancelRequest.reason` rechaza caracteres de control y ahora llega al aviso al dueño. | `PublicBookingService.ts:299` | no |
| db13227, c304cf5 | `stores`, `staff`, `services`, `superadmin`, `users` schemas | `reject_control_chars` (NUL, bidi, zero-width) en nombres y textos publicados → 422. | formularios del panel | no (texto normal no se ve afectado) |
| 7a35d70 | `backend/modules/appointments/router.py` | `/appointments/search` `page` ≤ 10.000. | `HttpBookingRepository.ts:68,179`, `PaymentsService.ts:148` (máx. 50 páginas) | ya lo cubre |
| 6260c46 | `backend/modules/payments/router.py` | `POST /payments/outbox/process` `limit` ≤ 100 (antes 500). | `Payments.tsx:72` manda 100 | ya lo cubre |
| dca1de1 | `backend/modules/superadmin/router.py` | `GET /superadmin/stores/{id}/users` `limit` 1..200 (default 50, antes sin tope); `offset` ≤ 1.000.000 en listados. | nadie llama `/superadmin/stores/{id}/users` | no |
| cd992e6 | `backend/modules/staff/router.py` | `PATCH /staff/{id}/services`: body sigue siendo un array, ahora con patrón de id y máx. 100. | nadie | no |
| 77aedd6 | `backend/modules/stores/router.py` | `GET /stores/media/{media_id}` valida el formato del id (422). | URLs de logo/portada que devuelve el backend | no |
| dbdf35c | `backend/modules/appointments/availability.py:416` | Disponibilidad sin token (portal y `/appointments/availability` anónimo): `reason` de un bloqueo sale "No disponible". Forma del slot sin cambios. | el portal solo lee `slot.status` (`BookingStepDateTime.tsx:273-277`) | no |

---

## C. Códigos de estado y `error_code`

Forma del error sin cambios: `{success:false, error_code, message, detail?}`. Conjunto de `error_code` literales del backend: sale `PAYMENT_PREFERENCE_EXPIRATION_FAILED`; entran `LAST_SUPERADMIN_DEACTIVATION_DENIED`, `LAST_SUPERADMIN_REVOCATION_DENIED`, `SELF_SUPERADMIN_DEACTIVATION_DENIED`, `SELF_SUPERADMIN_REVOCATION_DENIED`, `SERVICE_NOT_READY`; `SLUG_ALREADY_IN_USE` pasa a `RESOURCE_CONFLICT`. Los del portal (`OTP_VERIFICATION_REQUIRED`, `APPOINTMENT_CONFLICT`, `PAYMENT_PROVIDER_UNAVAILABLE`, `PAYMENT_LINK_CREATION_FAILED`, `CANCELLATION_WINDOW_EXPIRED`, `PAID_APPOINTMENT_RESCHEDULE_DENIED`, `OUT_OF_SCHEDULE`, `SCHEDULE_BLOCKED`) se movieron de `public_api/router.py` a `public_api/service.py` sin cambiar código ni status.

**Estado del front:** el único `error_code` que el front lee es `CONCURRENT_MODIFICATION` (`shared/errors/getErrorMessage.ts:22`) y `FEATURE_DISABLED` (`shared/errors/handlers/SpecificHandlers.ts:63`). Además `getErrorMessage` busca `error.response.data`, que el interceptor ya no conserva (FF-02), y `api-contract.ts:124-150` mapea 402/429/503 a `InternalServerError`. Por eso casi toda la fila de abajo dice "sí".

| Commit | Archivo | Status / `error_code` / mensaje (antes → después) | Consumidor en el front | ¿Front? |
|---|---|---|---|---|
| 50d8eea | `backend/main.py` (handler de `DBAPIError`) | Deadlock (40P01), serialización (40001) y `lock_timeout` (55P03): 500 → **409 `CONCURRENT_MODIFICATION`** "Alguien mas modifico este registro mientras lo editabas. Actualiza la vista y volve a intentar." | `getErrorMessage.ts:22` tiene el texto, pero no le llega el código (FF-02); `client.ts:79-84` lo reintenta | sí |
| 35839e2 | `backend/main.py` (`LastResortErrorMiddleware`) | El 500 no manejado ahora sale con CORS y headers de seguridad (antes el navegador veía un error de CORS). Mismo cuerpo `INTERNAL_SERVER_ERROR`. | — | no (mejora) |
| 90295b7 | `backend/core/roles.py:98-116`, `users/router.py:31,105` | Admin de tienda que crea o asciende a `admin`: 201 → **403 `PERMISSION_DENIED`** "Solo el soporte global puede otorgar ese rol". | `UserFormModal.tsx:190` ofrece "Administrador" | sí (J6) |
| e31cec5 | `backend/core/roles.py:125-160`, `users/router.py:107,144`, `staff/router.py:228` | Admin de tienda que cambia clave, estado, rol o email de **otro** admin (por `/users/` o `/staff/`): **403 `PERMISSION_DENIED`** "Solo el soporte global puede cambiar el acceso de otro administrador". Cuenta con `is_global_admin`: **404** para el admin de tienda. | `HttpUserRepository.ts:103,111`, `HttpStaffRepository.ts:47,52` | sí (mostrar el mensaje) |
| e6ba357, f7f5219 | `backend/modules/users/service.py`, `users/repository.py` | `POST /users/` email duplicado (sin distinguir mayúsculas): 400 "Ya existe un usuario con ese email" → **409 `RESOURCE_CONFLICT`** "El registro entra en conflicto con uno existente." PATCH con choque de índice: 400 → 409. | `HttpUserRepository.ts:79,103`, `UserFormModal.tsx:72` | sí (J6, FF-29) |
| 2f3d783 | `backend/modules/users/guards.py:97-134` | Superadmin: desactivar/revocar el último o a uno mismo sigue en **400** pero ahora con código propio (`SELF_SUPERADMIN_*`, `LAST_SUPERADMIN_*`; antes `APP_ERROR`). Vale también por `/users/`. | `SuperAdminService.ts:317,325` | no (mismo status y mensaje) |
| 3009d73 | `backend/modules/appointment_blocks/service.py:396-428` | `PATCH /appointment-blocks/{id}` que pasa a cubrir turnos: 200 → **409 `BLOCK_HAS_APPOINTMENTS`** `detail:{affected:N}`; reintento con `cancel_affected:true` (profesional → 403). | `AppointmentBlocksService.ts:102`, `CalendarContainer.tsx:465-477` | sí (FF-11) |
| 42562c9 | `backend/modules/public_api/service.py:810,874-885` | Reprogramar desde el portal dentro de la ventana de cancelación: 200 → **409 `CANCELLATION_WINDOW_EXPIRED`** "Solo se puede cancelar con {N}h de anticipación". | `PublicBookingService.ts:308`, `ClientAppointmentsContainer.tsx` | sí |
| 67cc847 | `backend/main.py:500-523`, `billing/dependencies.py` | Tienda suspendida: **402 `SUBSCRIPTION_SUSPENDED`** "Tu suscripcion esta suspendida: renovala para volver a operar. Podes seguir viendo tu informacion mientras tanto." ahora también en escrituras de `dashboard`, `users`, `reports`, `payments`, `notifications`, `ledger`. Permitidas (`SUSPENSION_ALLOWED_WRITES`): marcar notificaciones, exportar, baja de usuario, config/OAuth de MP, link de pago, confirmar y devolver a mano, procesar outbox. Portal: 404 `STORE_NOT_FOUND` solo al crear reserva o anotarse en lista de espera. | `api-contract.ts:124-150` (402 → genérico), `SubscriptionBanner.tsx` | sí (FF-15) |
| 481d109 | `backend/core/rate_limit.py` | Redis del limitador caído con `RATE_LIMIT_FAIL_CLOSED`: el middleware respondía **503 con `error_code:"RATE_LIMITED"`** → **503 `RATE_LIMIT_UNAVAILABLE`** "Rate limit temporalmente no disponible" + `Retry-After: 5`. El 429 `RATE_LIMITED` de la app no cambia. | `api-contract.ts` (503 → genérico) | sí (tratar como "reintentar en N s") |
| 8ae48df | `nginx/nginx.conf`, `nginx/nginx.prod.conf:268-305` | Errores **del borde** bajo `/api` en JSON canónico (antes HTML de nginx): 502/503/504 → **503 `UPSTREAM_UNAVAILABLE`** "El servicio no está disponible. Intentá nuevamente en unos segundos." + `Retry-After: 5`; 429 → **`RATE_LIMITED`** "Demasiadas solicitudes. Intentá nuevamente más tarde." + `Retry-After: 1`; 413 → **`REQUEST_TOO_LARGE`**. Un 503 de la app pasa tal cual (`proxy_intercept_errors off`). | ninguno los distingue | sí |
| 5ed39f4 | `backend/modules/reports/router.py:114-124` | `POST /reports/export` para profesional: 200 → **403 `PERMISSION_DENIED`** "No tenés permiso para realizar esta acción: exportar reportes." | `ReportsService.ts:138`, botones en `Reports.tsx:273,283,297` | sí (J2) |
| c0b69e1 | `backend/modules/promotions/router.py:142` | `GET /promotions/preview` (panel) ahora solo admin → 403 para el resto. | nadie (el front usa `/public/promotions/preview`, `PublicBookingService.ts:285`) | no |
| 9bdc57a | `backend/modules/services/router.py` | `GET /services/?include_inactive=true` para no admin → 403. | nadie lo manda | no |
| 92bb592 | `backend/modules/ledger/service.py` | Fiado contra cliente o turno de otra tienda: 409 → **404**. | `LedgerService.ts:53` | no (caso anómalo) |
| 4a7e364 | `backend/modules/auth/service.py` | `DELETE /auth/sessions/{id}` inexistente: 404 `USER_NOT_FOUND` → **404 `RESOURCE_NOT_FOUND`** ("Sesión"). | nadie | no |
| 7180c43 | `backend/modules/appointments/service.py` | Liberar un turno pendiente ya no llama a Mercado Pago: desaparece el **502 `PAYMENT_PREFERENCE_EXPIRATION_FAILED`** (el link lo vence el outbox). | `HttpBookingRepository.ts:128` | no (un error menos) |
| 39f2ed2, 2c81ae9 | `backend/modules/ops/router.py:103-109` | `GET /ops/health/ready`: si la base o Redis no responden → **503 `SERVICE_NOT_READY`**; en producción el detalle por componente se cierra por default. | nadie | no |
| e436627 | `backend/core/exceptions.py` | Mensajes de `APPOINTMENT_CONFLICT` y `SCHEDULE_BLOCKED` con horas en hora argentina (antes UTC). `detail` sigue en ISO UTC. | se muestran vía `getErrorMessage` | no |

---

## D. Permisos por rol

Fuente: `backend/core/roles.py` (`STORE_MANAGERS = {super_admin, store_admin}`, `REPORT_VIEWERS` suma `professional`, `REPORT_EXPORTERS = STORE_MANAGERS`) y `docs/ROLE_MATRIX.md` (re-verificado el 2026-09-19, commit d803f30).

| Rol | Pierde | Gana | Commit | ¿Front? |
|---|---|---|---|---|
| `store_admin` | Crear o ascender usuarios a `admin` (403). Cambiar clave, estado, rol o email de otro admin por `/users/` o `/staff/` (403). Ver o editar cuentas con `is_global_admin` (desaparecen del listado; 404 en detalle, edición y baja). | — | 90295b7, e31cec5, 0c21109 | sí (FF-09) |
| `professional` | `POST /reports/export` (403). `GET /promotions/preview` del panel (403). `cancel_affected` en PATCH de bloqueo (403). No accede a `GET /reports/audit-logs` (nuevo, solo admins). | — | 5ed39f4, c0b69e1, 3009d73, 028f4b1 | sí (FF-18, FF-34) |
| `super_admin` | Vista consolidada de todas las tiendas en `/reports/*` y `/dashboard/summary`: ahora ve **su** tienda (`store_scope_for`). | `PATCH /stores/me`, `PUT /stores/me/feature-flags`, `POST /stores/me/media` aunque su `role` persistido no sea `admin` (antes comparaba `user.role == ADMIN`). | 8252eb5, 20673f5 | no |
| `receptionist` | Sin cambios de código en el rango. `ROLE_MATRIX.md` ahora documenta lo que ya pasaba: no cobra, no toca fiado, no gestiona bloqueos, no confirma/completa/marca ausente, no ve reportes. | — | d803f30 (doc) | sí, ya pendiente (FF-14, FF-21) |
| cualquiera con tienda suspendida | Escrituras en 6 routers más (402). | — | 67cc847 | sí (FF-15) |

---

## E. Semántica de PATCH (`exclude_unset`, `null` borra)

`apply_patch` (`backend/infrastructure/persistence/patch.py`, 5cdca00): aplica solo las claves enviadas; `null` borra si la columna admite NULL y se **ignora** si es NOT NULL.

| Módulo / endpoint | `exclude_unset` | Qué hace un `null` | Cambió en el rango | Commit | ¿Front? |
|---|---|---|---|---|---|
| `PATCH /users/{id}` | **sí** (nuevo) | Borra `phone`, `first_name`, `last_name`; se ignora en `role`, `is_active`. `''` en nombres → 422 (`min_length=1`). | antes `model_dump()` + `if value is not None` | 5cdca00 | sí (FF-10: mandar `null`, no `''`) |
| `PATCH /services/{id}` | **sí** (nuevo) | Borra opcionales (`description`, `color`, `image_url`, `youtube_trailer_url`, `deposit_amount`); en NOT NULL → **422** (distinto de users, que ignora). | antes `model_dump()` completo | ae15ac8, a5fcd1c | ya lo cubre (`image_url: null` sirve para quitar imagen) |
| `PATCH /superadmin/stores|users|plans|coupons/{id}` | sí (ya en main) | Ahora borra en columnas NULL (antes `if value is not None`); se ignora en NOT NULL. | repositorio | 33c04b9 | revisar si algún formulario manda `null` sin querer borrar |
| `PATCH /promotions/{id}` | sí (ya en main) | `setattr` directo: borra lo que admite NULL. | sin cambio de semántica (solo pasó al service, b260563) | — | sí (FF-23: el front manda `undefined`, no `null`) |
| `PATCH /stores/me` | sí (ya en main) | `setattr` directo; en columnas NOT NULL (`name`, `slug`, `primary_color`, horas) un `null` termina en 409 `RESOURCE_CONFLICT`. | sin cambio | — | no |
| `PATCH /appointment-blocks/{id}` | sí (ya en main) | Se **ignora** (`if changes.get(key) is not None`): no se puede borrar `reason`. | sin cambio de semántica | — | no |
| `PATCH /staff/{id}/schedules/{sid}` | sí (ya en main) | `null` en `start_time`/`end_time` compara `None >= time` → **500** (defecto latente, `staff/repository.py:253-256`). | sin cambio | — | no (el front no llama horarios, FF-03) |
| **`PUT`/`PATCH /staff/{id}`** | **no** | `null` = "no cambiar" (`staff/repository.py:318-347`, `if x is not None`). PUT y PATCH son el mismo handler. | sin cambio | — | ver Q1 |
| `PATCH /appointments/{id}/*` | no aplica | Son acciones, no ediciones parciales. | — | — | no |

---

## F. Migraciones y datos

### Cadena de Alembic (verificada por `down_revision`, no por el docstring)

```
c9e1f3a5b7d9 (main) → b8d1c4f70a25 (main) → d2f4a6b8c0e2 → e7b9d1f3a5c7 → f8c0e2a4b6d8 → a1c3e5b7d9f2 → c5e7a9b1d3f4 → d1f3b5a7c9e2 (head)
```

La reordenó `fff4a22`. **Ojo:** los docstrings quedaron desalineados con el código: `b8d1c4f70a25` dice "Revises: d1f3b5a7c9e2" (el código dice `c9e1f3a5b7d9`) y `d2f4a6b8c0e2` dice "Revises: c9e1f3a5b7d9" (el código dice `b8d1c4f70a25`). Alembic usa las variables, así que funciona, pero confunde a quien lea el archivo; conviene corregirlos.

### Qué hacer con cada base

Una base que vino de `main` y una que vino de la rama del backend (orden viejo, `b8d1` arriba de `d1f3`) muestran **la misma** `alembic_version = b8d1c4f70a25`. Se distinguen por los objetos de las migraciones del backend:

```sql
SELECT version_num FROM alembic_version;
SELECT to_regclass('public.uq_users_email_lower') IS NOT NULL                                  AS tiene_d2f4,
       EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_services_deposit_percent_max')  AS tiene_d1f3,
       EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'otp_verifications' AND column_name = 'email')               AS tiene_b8d1;
```

| Resultado | Origen | Acción |
|---|---|---|
| `b8d1c4f70a25`, `tiene_d2f4 = false` | main | `alembic upgrade head` (aplica las seis del backend) |
| `b8d1c4f70a25`, `tiene_d2f4 = true`, `tiene_d1f3 = true` | rama del backend | `alembic stamp d1f3b5a7c9e2` (no correr `upgrade`: intentaría recrear índices y CHECK) |
| `d1f3b5a7c9e2`, `tiene_b8d1 = false` | backend anterior al merge con main | caso no cubierto por `fff4a22`: Alembic cree que `b8d1` ya está y el INSERT del OTP falla por la columna. Aplicar la columna de `b8d1c4f70a25` a mano o volver a `c5e7…` con cuidado; decidirlo antes de tocar la base |

### Restricciones nuevas que pueden rechazar datos o escrituras del front

| Commit | Migración | Qué agrega | Datos existentes | Escrituras del front | ¿Front? |
|---|---|---|---|---|---|
| f7f5219 | `d2f4a6b8c0e2` | Índice único `uq_users_email_lower` sobre `lower(email)` | La migración **se detiene** con el conteo si hay emails repetidos salvo mayúsculas; no elige cuál conservar | Alta/edición con email que ya existe en otra capitalización → 409 | sí (J6) |
| 846d7a3 | `e7b9d1f3a5c7` | `outbox_messages.attempts` (NOT NULL, default 0) | Ninguno | Ninguna | no |
| 8ad2684 | `f8c0e2a4b6d8` | Borra el UNIQUE `uq_store_promotions_store_code` y crea `uq_store_promotions_active_code` (único solo entre activas) | Ninguno | Un código de una promoción dada de baja vuelve a poder usarse | no |
| 676ceca | `a1c3e5b7d9f2` | `audit_logs.created_at` → `timestamptz` (`AT TIME ZONE 'UTC'`) | Reescribe la tabla (lock durante el `ALTER`) | Ninguna | no |
| 5099603 | `c5e7a9b1d3f4` | `audit_logs.store_id` + índice `ix_audit_logs_store_id`, con backfill | Ninguno | Ninguna | no |
| 41a40c8 | `d1f3b5a7c9e2` | CHECK `ck_services_deposit_amount_presente` y `ck_services_deposit_percent_max` | La migración **se detiene** si hay servicios con seña obligatoria/opcional sin monto o porcentaje > 100 | Si una validación se saltea (carrera de dos PATCH) → 409 `RESOURCE_CONFLICT` | sí (J3) |
| (main) | `c9e1f3a5b7d9` | `uq_users_client_phone_per_store` (ya estaba en main) | — | Teléfono de cliente repetido en la tienda → 409 | no nuevo |
| 40535e1 | `c3d4e5f6a7b8` (editada) | `APP_DB_PASSWORD` sin default: la migración de RLS falla si no está | — | — | no (operación) |
| 6f6ecf7 | `d5ec116d06a3` (editada) | `downgrade` levanta `NotImplementedError` (antes `pass`) | — | — | no |
| d86bf44 | `backend/alembic/env.py` | `lock_timeout = '3s'` y una transacción por revisión | Una migración que espera un lock aborta | — | no |

Nota de despliegue: `f8c0e2a4b6d8` (borra una restricción), `a1c3e5b7d9f2` (reescribe una tabla) y `d2f4a6b8c0e2` (índice sin `CONCURRENTLY`) no cumplen la regla expand/contract que la propia rama agrega a CLAUDE.md. Son anteriores a la regla; para este primer deploy conviene correrlas en una ventana de poco tráfico.

---

## G. Configuración y despliegue

### G1. docker-compose

| Commit | Archivo | Cambio (antes → después) | Impacto para el front / operación |
|---|---|---|---|
| 6a689c6 | `docker-compose.yml`, `docker-compose.prod.yml` | Un `redis` → dos: `redis_cache` (puerto 6380, `volatile-ttl`, sin persistencia, solo caché de disponibilidad) y `redis_state` (6379, `noeviction`, RDB, volumen `redis_state_data`: rate limit, idempotencia, lockout, OTP, OAuth, resultados de Celery) | El servicio `redis` ya no existe. En el primer deploy `redis_state` arranca vacío: se pierden lockouts, replays de idempotencia y OTP pedidos justo antes (docs/RELEASE_CHECKLIST.md) |
| c90d844 | `docker-compose.yml:230-394` | `backend`, `celery_worker`, `celery_worker_interactive`, `celery_beat` corren una sola imagen `ghcr.io/enriquemartinez26/shifty-backend:${APP_VERSION:-dev}`; solo `backend` la construye | Cambiar el backend exige `docker compose build` y recrear los cuatro juntos |
| ed82d67 | `docker-compose.yml` | Se quitan los bind mounts `./backend:/app` y `./frontend:/app` (y sus volúmenes anónimos) | En desarrollo tampoco hay recarga en caliente dentro de compose: todo cambio del front exige `docker compose build frontend` |
| f6a585c | `docker-compose.prod.yml:97-111` | `backend` con `deploy.replicas: 3` (un uvicorn por réplica), sin `container_name` | nginx reparte por DNS de Docker |
| 8e57677 | ambos | `container_name: ${COMPOSE_PROJECT_NAME:-shifty}_<servicio>`; producción con `build: !reset null` (nunca construye) | Réplicas: `<proyecto>-backend-N`. `shifty_backend` deja de existir: usar `docker compose exec backend …` |
| 6e5cae5 | `docker-compose.prod.yml` | `ports: []` → `ports: !reset []` (exige Compose ≥ 2.24) | Producción deja de publicar db/redis/rabbitmq/backend/frontend en el host; solo nginx |
| 5a47116 | `docker-compose.yml:336-371` | Servicio nuevo `celery_worker_interactive` (cola `interactive`, `--concurrency=1`, para el mail del OTP); `celery_worker` pasa a `-Q celery --concurrency=2` | Nuevo nombre de servicio |
| bc935e2, 27078a5 | `docker-compose.yml` | Healthcheck de worker y beat por archivo de latido | — |
| 1caad17, 7db1add | ambos | Versiones menores fijas (`postgres:16.14-alpine`, `redis:7.4-alpine`, `rabbitmq:3.13.7`, `nginx:1.27.5-alpine`); Postgres dimensionado y con slow log | — |
| b4d5104 | `docker-compose.yml` | `stop_grace_period`: backend 35 s, worker 60 s, interactivo 30 s | Apagados más lentos a propósito |
| 1b155fa | `docker-compose.prod.yml:236+` | Volumen `pg_backups` (bind a `BACKUP_DIR` del host, que tiene que existir antes del `up`) | Operación |
| 87c51e2 | ambos | Rotación de logs `json-file` 20m × 5 en todos los servicios; logs JSON de la app | — |
| f540975, 8703267 | ambos | RabbitMQ con `hostname` fijo, 384M y alarma de memoria en 280 MiB | Con la alarma activa se frenan los publicadores (mails de OTP) |
| — | `docker-compose.prod.yml:216-229` | El borde de producción es `nginx:1.27.5-alpine` oficial con la config montada (no la imagen propia) | `make deploy` solo lo recarga; se recrea con `make deploy-edge` |

### G2. Variables de entorno

Fuente: `backend/core/config.py` y los archivos de ejemplo (`.env.example`, `backend/.env.production.example`, `deploy/ops.env.example`). Ningún `.env` real fue leído.

| Commit | Variable | Cambio | Front / build |
|---|---|---|---|
| 40535e1, c097d18 | `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `RABBITMQ_DEFAULT_PASS` | Pasan a obligatorias, sin default (`:?Falta … en .env`) | `docker compose up` falla en un clon sin `.env` completo |
| 6a689c6 | `REDIS_CACHE_URL` (nueva) | URL del Redis de caché; vacía usa `REDIS_URL` | no |
| 7e8b16f | `POSTGRES_SSL` (nueva); `DATABASE_URL`/`MIGRATION_DATABASE_URL` | URLs con `?ssl=…` explícito; sin nada se asume `require` | no |
| c90d844 | `APP_VERSION` | Tag de las imágenes. En dev default `dev`; en prod **obligatoria y fuera del `.env`** (la pasa `scripts/deploy.sh`) | sí, si se construye con compose |
| 87c51e2 | `LOG_LEVEL` (nueva) | Default `INFO`; solo en el ejemplo de producción | no |
| 0abc878 | `OTP_MAX_FAILURES_PER_HOUR` → `OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR` | Renombrada (acepta el nombre viejo como alias); default 10 | no |
| ac8aaaf | `TWILIO_SMS_FROM` | Eliminada | no |
| 03f64ba | `RUN_RUNTIME_CONTRACTS_ON_STARTUP` | Eliminada (la API ya no hace DDL al arrancar) | no |
| 2c81ae9 | `OPS_ENABLE_PUBLIC_HEALTH` | En producción queda `false` por default y falla el arranque si es `true` | no |
| 5741ef8, 52d02fd | `REDIS_SOCKET_TIMEOUT_SECONDS`, `REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS`, `RATE_LIMIT_WINDOW_SECONDS`, `MAX_UPLOAD_BODY_BYTES` | Pisos mínimos validados al arrancar | no |
| 1b155fa | `BACKUP_DIR` | Directorio de backups del host | no |
| 193fa1b | `vars.VITE_SENTRY_DSN` (variable del repo en GitHub) | Build-arg de la imagen del front en CI | sí: el DSN del bundle publicado sale de la variable del repo |
| — | `VITE_*`, `CORS_ORIGINS`, `FRONTEND_URL`, `PUBLIC_API_URL` | Sin cambios | no |
| 9071fa1 | `deploy/ops.env.example` (archivo nuevo) | Configuración de los scripts del host (`DOMAIN`, `BACKUP_REMOTE`, alertas, umbrales); va a `/etc/shifty/ops.env`, no es el `.env` de la app | no |

### G3. nginx y CSP

| Commit | Archivo | Cambio | Impacto para el front |
|---|---|---|---|
| 8ae48df | `nginx/nginx.conf`, `nginx/nginx.prod.conf` | Errores del borde en JSON canónico (ver sección C) | El front puede tratar igual un 503/429 del borde y uno de la app |
| 5eeb423, 137f04f | ambos | `limit_req` por IP. **Prod:** `/api/` 20 r/s burst 40; `/api/auth/` 3 r/s burst 6; webhook de MP 10 r/s burst 60 (zona propia); `limit_conn` 40 por IP. **Dev:** 200/30/100 r/s, 400 conexiones | Con el reintento de 409 (FF-01) y `retry: 1` global en GET, una ráfaga en `/api/auth/` puede dar 429 |
| e72b3ed | ambos | `gzip` en el borde (JSON, JS, CSS, SVG) salvo `/api/auth/` (BREACH); buffers de proxy de 16k | no |
| a173cde | ambos | Log JSON sin query string; `X-Edge-Request-Id: $request_id` **solo hacia el backend** (`proxy_set_header`) | El cliente no lo recibe: no hay `add_header` y `expose_headers` de CORS (`backend/main.py:485`) solo tiene `X-Idempotency-Key` y `Content-Disposition`. Si soporte lo quiere en pantalla, falta cablearlo |
| b3a11e2 | ambos | `upstream` con `resolve` y keepalive (sigue las 3 réplicas sin reload) | no |
| b6afcc8 | `nginx/nginx.prod.conf:85` | `/.well-known/acme-challenge/` servido en el :80 antes del redirect a HTTPS | no |
| ca4da92 | `frontend/nginx.conf` | `/assets/` (hash de Vite): `public, max-age=31536000, immutable`; otros estáticos sin hash: `max-age=3600`; un solo `Cache-Control` | no (ya es lo esperado) |
| — | `nginx/nginx*.conf` | `client_max_body_size` de `/api/stores/me/media`: 3m → 3200k | no |
| — | `frontend/security-headers.conf` | **CSP sin cambios** en el rango | no |

### G4. Makefile

| Commit | Target | Cambio |
|---|---|---|
| ed82d67, d582e67 | `dev` | `up --build --remove-orphans` (limpia el `redis` viejo) |
| 33d2e39 | `makemigrations` | Copia solo revisiones nuevas al host y aborta si el contenedor tiene una revisión que el host no tiene |
| a5cfa21 | `test`, `shell` | Corren en el host con `uv run --frozen --group dev` (la imagen ya no trae `tests/` ni el grupo dev) |
| bd75b67, 03a5fd5 | `deploy`, `rollback`, `deploy-edge`, `backup` (nuevos) | `make deploy APP_VERSION=<sha>` migra antes de recrear; `rollback` vuelve a `.deploy/previous` sin migrar; `deploy-edge` recrea nginx; `backup` corre `scripts/backup.sh` |

### G5. CI

| Commit | Archivo | Cambio |
|---|---|---|
| 193fa1b | `.github/workflows/build-images.yml` (nuevo) | En cada push a `main` publica `shifty-backend`, `shifty-frontend`, `shifty-nginx` en GHCR con tag `<sha>` y `latest`; conserva las últimas 5. No gatea PRs |
| 0396f20 | `.github/actions/setup-python-uv/action.yml` (nuevo) | Python 3.14.6 y uv 0.11.29 en un solo lugar |
| varios | `.github/workflows/quality.yml` | Usa la acción compuesta; head único con `pytest tests/architecture/test_migrations.py` (no `alembic heads`); `backend-postgres` con `?ssl=disable` y contraseña de prueba propia |
| — | `.github/workflows/e2e.yml` | Fija npm 11.17.0 antes de `npm ci` |
| — | `.github/workflows/monthly-backup-drill.yml` | Runner configurable (`vars.BACKUP_DRILL_RUNNER`) y chequeo temprano de secretos |
| 53e1908 | `.github/dependabot.yml` (nuevo) | PRs semanales agrupados para `uv`, `npm` y `github-actions` |
| — | `.pre-commit-config.yaml` | Solo un comentario: la compuerta no está activa hasta `core.hooksPath` |
| **e68100e** | `.github/workflows/security-scan.yml` | **Pendiente de merge**: vive solo en `perf/cve-ci`. `pip-audit` sobre `uv.lock`, Trivy sobre las 3 imágenes, `npm audit` semanal |

### G6. Scripts y archivos de host

| Archivo | Para qué | Qué hace el operador |
|---|---|---|
| `scripts/deploy.sh` | Preflight (Compose ≥ 2.24, disco, backup < 24 h) → `pull` por `APP_VERSION` (nunca construye) → migra con el código viejo sirviendo → backend nuevo al lado del viejo → compuerta de 60 s → rollback automático sin migrar | `make deploy APP_VERSION=<sha>` |
| `scripts/backup.sh` + `deploy/systemd/shifty-backup.{service,timer}` | Backup diario 03:00 ART con el rol dueño, zstd, SHA256SUMS, copia fuera del host con rclone, retención 7+4 | Habilitar el timer; completar `BACKUP_REMOTE` |
| `scripts/backup-check.sh` | Alerta si el último backup tiene más de 26 h (crítico a 48 h) | cron |
| `scripts/guard.sh` + `deploy/cron/shifty-guard` | Reinicia contenedores `unhealthy` (tope 3 por contenedor y 6 por hora; no toca db ni rabbitmq) | Instalar el cron |
| `scripts/latency-check.sh` + `backend/scripts/latency_report.py` + `deploy/cron/shifty-latency` | p95 por ruta y tasa de 5xx cada 5 min desde el log JSON de nginx | Instalar el cron |
| `scripts/checks.sh` | NTP, vencimiento del certificado, disco, memoria por contenedor | Parte del cron del guard |
| `scripts/cert-deploy-hook.sh` | Hook de certbot: copia el certificado y recarga nginx | `--deploy-hook` de certbot |
| `scripts/lib/common.sh` | Lee `/etc/shifty/ops.env`, resuelve el clon, alertas | — |
| `deploy/logrotate/shifty`, `deploy/rabbitmq/rabbitmq.conf` | Rotación de `/var/log/shifty`; watermark de RabbitMQ | Instalar / ya montado |
| `backend/scripts/backup_db.py`, `backup_restore_drill.py`, `restore_backup.py` | Exigen el rol dueño, no `DATABASE_URL`; el drill se niega a restaurar sobre el origen | — |
| `backend/scripts/bootstrap_superadmin.py`, `seed_simulation.py` | Cargan el registro de modelos; el seed ya no imprime la URL con credenciales | — |
| `backend/Dockerfile`, `backend/run_migrations.py` | Usuario no-root dueño de `/var/lib/shifty/beat`; uvicorn sin `uv run`; `parse_db_url` único | — |

---

## H. Dependencias

| Archivo | Cambio en el rango |
|---|---|
| `backend/uv.lock` | Ninguno |
| `frontend/package.json`, `frontend/package-lock.json` | Ninguno |
| `backend/pyproject.toml` | Solo `ruff`: se quitan excepciones `F401` de `alembic/env.py` y tres `model.py` (no son dependencias) |

**Bumps de CVE pendientes de OK del dueño** (no hay commit que los haga en ninguna rama; `perf/cve-ci` solo trae el escaneo):

| Paquete | Versión en `backend/uv.lock` hoy | Cómo entra | Estado |
|---|---|---|---|
| anyio | 4.13.0 | transitiva (starlette/httpx) | pendiente de OK |
| cryptography | 48.0.0 | **solo** por el extra `python-jose[cryptography]` (`uv.lock:1452-1454`) | pendiente de OK (ver Q3) |
| ecdsa | 0.19.2 | transitiva (python-jose) | pendiente de OK |
| pillow | 12.2.0 | transitiva (reportlab) | pendiente de OK |
| pyasn1 | 0.6.3 | transitiva (python-jose, rsa) | pendiente de OK |
| pydantic-settings | 2.14.1 | directa (`>=2.2.0`) | pendiente de OK |
| starlette | 1.0.0 | transitiva (fastapi) | pendiente de OK |

Recordatorio de CLAUDE.md §1: toda dependencia nueva o bump va con verificación humana en el registro oficial, el lockfile en el mismo commit y rebuild de todas las imágenes que la usan.

---

## I. CLAUDE.md y docs que contradicen a `main`

| Commit | Archivo | `main` dice | La rama dice | Acción |
|---|---|---|---|---|
| 870e194, 58b0953 | `CLAUDE.md` §1 | Dependencia nueva: rebuild con `--renew-anon-volumes`; un `restart` deja el contenedor no-root en crash-loop | Rebuild con `docker compose build`; ya no hay bind mount ni volumen anónimo; un `restart` sigue con la imagen vieja | Queda la de la rama (el compose cambió) |
| 870e194 | `CLAUDE.md` §2 | `appointments` es el único con "commit solo en service"; lista 4 archivos que commitean | La lista viva es `COMMITS_DECLARADOS_FUERA_DE_SERVICE` en `tests/architecture/test_boundaries.py` | Queda la de la rama |
| 870e194 | `CLAUDE.md` §2 | Un Redis; rate limit envuelve MP | **Dos Redis** con papeles fijos; rate limit por IP con política propia para `/auth/` y `/public/` | Queda la de la rama |
| 870e194 | `CLAUDE.md` §3 reglas 13, 21, 22, 23 | Migraciones probadas con `downgrade -1`; compose con build por servicio | Expand/contract, `lock_timeout 3s`, imagen única, prod sin build, `!reset []`, errores del borde en JSON | Queda la de la rama |
| 870e194 | `CLAUDE.md` §3 regla 29 | "Hay 19; `create_public_booking` tiene 331" | Quedan 8 (lista explícita) | Queda la de la rama |
| 870e194 | `CLAUDE.md` §4 | "Hasta que exista el job de CI con Postgres…" | `backend-postgres` existe | Queda la de la rama |
| 870e194 | `CLAUDE.md` §5 | Pre-commit hook "activado en este clon" | Solo corre si cada clon hace `git config core.hooksPath .githooks` (activado en el clon de Enrique el 2026-09-22) | Queda la de la rama; cada clon lo verifica |
| 870e194 | `CLAUDE.md` §5 | `ROLE_MATRIX.md` declara deriva | `ROLE_MATRIX.md` re-verificado el 2026-09-19 | Queda la de la rama |
| 870e194 | `CLAUDE.md` §5 | — | Nombres de contenedor: `shifty_backend` ya no existe | Revisar scripts y docs del front que lo nombren |
| d803f30 | `docs/ROLE_MATRIX.md` | "Endpoints clave" como objetivo; receptionist con cobros y bloqueos | Separa objetivo de producto y código real; receptionist sin cobros, fiado, bloqueos ni reportes | Queda la de la rama |
| cbc10cc, 0c3f396, 481d109 | `docs/API_EXTERNAL_CLIENT_TEMPLATE.md` | `x-raw-response` opcional para clientes | Solo tests; ignorado en producción. Suma `RATE_LIMIT_UNAVAILABLE` (503) | Queda la de la rama |
| b89ce61 | `docs/SCALING_AND_HARDENING_PLAYBOOK.md` | PgBouncer `transaction` | Sin PgBouncer (rompe el advisory lock de Celery) | Queda la de la rama |
| 9071fa1, 5baf5f5, 7b0ca03 | `docs/BACKUP_RESTORE_RUNBOOK.md`, `docs/RELEASE_CHECKLIST.md`, `docs/DEPLOY_RUNBOOK.md` (nuevo) | Backup y deploy manuales | Backup diario en el host, `make deploy`, prerequisitos del VPS, Compose ≥ 2.24 | Queda la de la rama |

Ninguno de estos cambios contradice una decisión del dueño listada en CLAUDE.md §1 (alta solo por superadmin, zona horaria aparte, consolidado del panel en espera).

---

## J. Los 7 impactos que detectó Enrique

| # | Afirmación de Enrique | Veredicto | Evidencia | Qué hacer en el front |
|---|---|---|---|---|
| 1 | Horarios: un período por día y `open < close` → 422 | **Confirmado, con dos agregados.** También `"99:99"` o una hora vacía → 422 (antes 500), y `open == close` → 422. Un horario que cruza la medianoche (20:00-02:00) no se puede cargar. Los días cerrados siguen siendo lista vacía. | `stores/schemas.py:45-57` (`time` + `validate_time_order`, c49539f), `:141-156` (`reject_extra_periods`, e27be5c). Mensajes: `business_hours: Value error, Por ahora cada dia admite un solo periodo de apertura`; `…: Value error, open debe ser anterior a close` | Ocultar "+ Bloque" (`Settings.tsx:1024-1038`), validar `open < close` antes de guardar, `key` estable (FF-08) |
| 2 | `/reports/export` solo admin → 403 para profesional | **Confirmado.** | `reports/router.py:114-124` usa `REPORT_EXPORTERS = {super_admin, store_admin}` (5ed39f4). 403 `PERMISSION_DENIED` "No tenés permiso para realizar esta acción: exportar reportes." | Ocultar los tres botones (`Reports.tsx:273,283,297`) si el rol no es admin; parsear el blob de error (FF-18) |
| 3 | Seña: monto > 0, percent ≤ 100, 2 decimales | **Confirmado, con precisiones.** "Monto > 0" aplica solo si `deposit_mode != none` y `deposit_type != full`. "2 decimales" aplica a `deposit_amount` **y a `price`**. Hay un CHECK en Postgres además del schema. | `services/schemas.py:32-64` (ae15ac8, cb2cb41), PATCH mezclado con la fila en `services/router.py:113-131`, CHECK en `d1f3b5a7c9e2` (41a40c8) | `service.validators.ts:26-31` hoy permite `min(0)` y no tiene tope de 100 (el comentario de `:52-57` dice que el tope "va en el backend": ya está). Cambiar a `> 0`, `≤ 100` si `percent`, múltiplo de 0,01 en precio y seña |
| 4 | `GET /ledger/customers/{id}` pagina de a 50 con `total` | **Confirmado, con un agregado:** el orden se invirtió (más nuevo primero; antes más viejo primero). `limit` máx. 200, `offset` máx. 100.000. | `ledger/router.py:175-207` (f7c8cbf), `ledger/schemas.py:28-34` | `LedgerService.ts:42-44` sin `limit`/`offset` y `CustomerLedger` sin `total`; paginar o "ver más"; revisar el orden en `Ledger.tsx:250` (FF-20) |
| 5 | `/reports/summary` `limit=2000` por defecto con `has_more` | **Confirmado.** `limit` 1..5000, `offset` 0..100.000, solo sobre `appointments`; `stats` y los top siguen siendo del rango completo. | `reports/router.py:37,65-66` (c88d2dc), `reports/schemas.py:91`, cálculo en `reports/service.py:831` (73c31b3) | Declarar `has_more` en `ReportSummary` (`ReportsService.ts:62-71`) y paginar o avisar (FF-30) |
| 6 | Alta de admin solo superadmin (403) y email duplicado → 409 | **Confirmado para `/users/`; corregido para `/superadmin/`.** Por `POST /users/`: `role=admin` de un admin de tienda → 403; email duplicado → 409 `RESOURCE_CONFLICT`. Por `POST /superadmin/stores/{id}/admins` el duplicado sigue siendo **400 `APP_ERROR` "Ya existe un usuario con ese email"** (pre-chequeo sin distinguir mayúsculas); solo una carrera llega al índice y da 409. | `users/router.py:31` + `core/roles.py:98-116` (90295b7); `users/service.py` (e6ba357); `superadmin/repository.py:426-431` + `superadmin/router.py:268-269` | `UserFormModal.tsx:190`: mostrar `admin` solo si `is_global_admin` o el editado ya es admin (FF-09). Traducir 409 en usuarios y 400 en el alta del superadmin a "ese email ya existe" |
| 7 | Señuelo de OTP con `OTP_DEBUG_EXPOSE_CODE` | **Confirmado.** Con el flag activo (solo fuera de producción; en prod falla el arranque), `debug_code` es un código **falso** siempre que el canal sea email y el destino real no sea el email tipeado (tipee algo o no). Con `whatsapp`/`sms` (solo `OTP_PROVIDER=console`) sigue siendo el real. | `otp/service.py:187-209,373-379` (4f2e743, 31facf5); guarda de prod en `core/config.py:134-138` | `NewAppointmentModal.tsx:485-494` y `BookingStepConfirmation.tsx:456-465` muestran "Código debug": puede no verificar en dev si el teléfono ya es de un cliente con email. No es un bug; conviene aclararlo en el texto o no mostrarlo |

---

## K. Las 3 preguntas

### Q1. ¿Se aplica `exclude_unset` al update de staff (F10-08)?

**No.** `PUT` y `PATCH /staff/{id}` comparten el handler (`staff/router.py:231-270`), que pasa cada campo como keyword a `StaffService.update_profile`, y el repositorio aplica solo lo que no es `None` (`staff/repository.py:318-347`). Un `null` significa "no cambiar". F10-08 quedó hecho en `users`, `services` y `superadmin`, no en `staff`.

Lo que cambiaría en la práctica es poco: en `staff`, `first_name`, `last_name`, `display_name` e `is_active` son NOT NULL (`infrastructure/persistence/models/staff.py:30-35`); el único campo que se podría borrar es `email`, y en una persona es su email de login. Y el front manda el objeto completo por **PUT** (`HttpStaffRepository.ts:45-48`, `Staff.toPrimitives()` con `email: null` cuando no hay): aplicar `exclude_unset` en ese handler haría que ese `null` empezara a significar "borrar".

**Recomendación:**
1. Separar los handlers. `PUT /staff/{id}` queda como está, compatible con el front actual.
2. `PATCH /staff/{id}` pasa a `model_dump(exclude_unset=True)`, con 422 ante `null` en campos NOT NULL, igual que `services` (`services/schemas.py:129-136`). `email: null` en una persona → 422.
3. El front migra a PATCH mandando solo lo que cambió. Cuando nadie use PUT, se retira.

Cambia el contrato, así que va con acuerdo previo. Si no hay un caso real de "borrar un campo de un profesional", también es válido dejarlo como está y documentarlo en la tabla E.

### Q2. ¿Sigue haciendo falta `PUT /payments/gateway-config` si el panel conecta por OAuth?

**Evidencia:**
- Front: `paymentsService.upsertGatewayConfig` (`PaymentsService.ts:123-126`) solo lo usa `useUpsertGatewayConfig` (`usePayments.ts:32-41`), que **nadie importa**. El hook lleva `eslint-disable import/no-unused-modules` y un comentario "PENDIENTE DE DECISION DEL DUEÑO (2026-09-21)". El panel conecta por OAuth (`Settings.tsx:1342-1396`, `useStartMercadoPagoOAuth`).
- Backend: `payments/router.py:398-458`. **En producción ya responde 422** "En produccion, la cuenta de Mercado Pago se configura exclusivamente mediante OAuth". Fuera de producción carga un access token a mano y pone `connection_mode = "manual"`, borrando los datos de OAuth.
- Está en `SUSPENSION_ALLOWED_WRITES` (`billing/dependencies.py:48`) y lo usan unos 14 archivos de tests de integración y Postgres como atajo para dejar una tienda con gateway configurado (p. ej. `test_payments_and_public_paths.py`, `test_cobro_del_panel_dos_fases.py`, `test_pg_vencimiento_preferencia.py`, `test_gateway_config_sin_secretos.py`).

**Recomendación: retirarlo del front, conservarlo en el backend solo fuera de producción.** En producción ya no existe de hecho, y el front no tiene ningún camino que lo use. En el backend sigue siendo la forma barata de montar una tienda de prueba sin pasar por OAuth. Borrarlo obliga a reescribir unos 14 archivos de tests con un fixture que escriba `PaymentGatewayConfig` directo; eso se puede hacer después, sin apuro. Pasos:

1. Front: borrar `useUpsertGatewayConfig` y `upsertGatewayConfig` en el mismo commit (se cae el `eslint-disable`).
2. Backend: dejar el 422 de producción como está y documentar en el endpoint que es herramienta de desarrollo.
3. Si más adelante se quiere retirarlo del todo: fixture de tests primero, después borrar la ruta y su fila en `SUSPENSION_ALLOWED_WRITES`.

### Q3. ¿Declarar `cryptography` explícito en `pyproject.toml`?

**Confirmado que hace falta.** `backend/core/crypto.py:6` hace `from cryptography.fernet import Fernet` (cifrado de secretos del gateway), pero `cryptography` no está en `[project].dependencies`: entra solo por el extra `python-jose[cryptography]` (`uv.lock:1452-1454`). Si mañana se reemplaza `python-jose` (que sigue trayendo `ecdsa` y `pyasn1`, dos de los CVE pendientes) o se le quita el extra, el import de `core/crypto.py` se rompe sin que el lock lo avise.

**Recomendación:** declararla en el **mismo commit** que el bump de CVE, con el piso en la versión que corrige el CVE (la 50.x que se elija), no `>=48.0.0`. Un piso en 48 deja que el resolver conserve una versión vulnerable si otra restricción lo empuja. Ese commit lleva `pyproject.toml` + `uv.lock` y el rebuild de las cuatro imágenes que usan `shifty-backend` (CLAUDE.md §1, regla 22). Otra opción para más adelante, fuera de este commit: reemplazar `python-jose` por `PyJWT` elimina `ecdsa` y `pyasn1` del árbol, pero cambia el código de auth y necesita su propio PR.

---

## L. Cómo verificar

No se corrió nada; el coordinador pega los exit codes. Los comandos son los de CI (`.github/workflows/quality.yml`). Sin pipes a `tail` (CLAUDE.md §4) y sin correr backend y front a la vez en la misma máquina.

**Backend** (en `backend/`):

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
uv run pytest tests/architecture/test_migrations.py
uv run pytest tests/unit/test_frontend_routes_contract.py
# Postgres real (mismas variables que el job backend-postgres):
APP_DB_PASSWORD=<prueba> \
TEST_POSTGRES_MIGRATION_URL='postgresql+asyncpg://<dueño>:<clave>@localhost:5432/shifty_test?ssl=disable' \
TEST_POSTGRES_URL='postgresql+asyncpg://shifty_app:<prueba>@localhost:5432/shifty_test?ssl=disable' \
uv run pytest tests/postgres -p no:cacheprovider
```

**Frontend** (en `frontend/`):

```bash
npm ci
npm run check
npm run test:coverage -- --watchAll=false
npm run build
```

| Gate | Exit code |
|---|---|
| `ruff format --check` | |
| `ruff check` | |
| `mypy` | |
| `pytest` | |
| `pytest tests/postgres` | |
| `npm run check` | |
| `npm run test:coverage` | |
| `npm run build` | |

---

## M. Hallazgos laterales

1. **Docstrings de migraciones desalineados** (`b8d1c4f70a25`, `d2f4a6b8c0e2`; sección F). Cosmético, pero es lo primero que lee quien estampa una base.
2. **`PATCH /staff/{id}/schedules/{sid}` con `start_time: null` da 500** (`staff/repository.py:253-256`: `None >= time`). Ya estaba en `main`; nadie del front lo llama hoy (FF-03), pero se vuelve alcanzable cuando exista el editor de horarios por profesional.
3. **`X-Edge-Request-Id` no llega al navegador** (sección G3). Si soporte lo necesita para cruzar un error con los logs, hay que agregar el `add_header` y exponerlo en CORS.
4. **El test de contrato de rutas solo mira la barra final** (sección A). Un endpoint borrado o un verbo cambiado no lo hace fallar.
5. **Base que vino del backend antes del merge con main** (`alembic_version = d1f3b5a7c9e2` sin la columna `otp_verifications.email`): `fff4a22` no la contempla (sección F).

## Cómo verificar

Resultado del gate sobre `integration/aud2` @ 6786cef (2026-09-24, un comando por vez, sin pipes):

| Comando | Exit | Salida |
|---|---|---|
| `uv run ruff format --check .` | 0 | formateado |
| `uv run ruff check .` | 0 | All checks passed |
| `uv run mypy .` | 0 | sin errores |
| `uv run pytest` (SQLite) | 0 | 3352 passed, 99 skipped |
| `uv run pytest tests/postgres` | 0 | 99 passed |
| `alembic downgrade -1` / `upgrade head` | 0 | roundtrip ok; `alembic heads` = `d4e6f8a0b2c5` |
| `npm run check` | 0 | ok |
| `npm run test:coverage` | 0 | 328 passed; 92,69 % líneas |
| `npm run build` | 0 | built in 9.19s |


## Cambios posteriores al inventario (Fase 2, 2026-09-24, `integration/aud2` @ 04bc98f)

| Área | Antes | Después | ¿El front tiene que hacer algo? |
|---|---|---|---|
| Imagen de servicio | solo `image_url` externa | `POST /api/services/{public_id}/image` (multipart `file`, admin, guarda de suspensión) → `image_url` absoluta `{PUBLIC_API_URL}/stores/media/{id}`; `DELETE /api/services/{public_id}/image` → `image_url: null`. La URL externa sigue aceptada. | **Sí**: subir imagen desde el panel; `z.string().url()` acepta la absoluta. |
| URLs de medios en PATCH | — | Se acepta la URL propia (absoluta o relativa); otra media URL → 422; crear con media URL → 422; vaciar o reemplazar borra la imagen en el servidor. Aplica a `/services/{id}`, `/stores/me` (logo y portada) y `/superadmin/stores/{id}` (logo). | Mandar la URL actual sin cambios o subir. |
| Topes de imagen | 25 MP para todo | logo 2048 px/lado y 1 MB; portada 3840×2160 (vertical permitida) y 2 MB; servicio 1600 px/lado y 1 MB; `INVALID_IMAGE` (422) si no se pueden leer las dimensiones; JPEG sin Exif salvo Orientation. | Validar del lado del cliente con los mismos topes. |
| Caché de medios | `max-age=86400`, sin ETag | `public, max-age=31536000, immutable`, `ETag`, `Last-Modified`, 304 desde el edge, HEAD; la query string se ignora. | No. |
| Catálogo público | `no-store` | `/public/services` y `/public/staff`: `s-maxage=30, stale-while-revalidate=30` (hasta 60 s para ver un cambio). `/public/stores/{slug}`, disponibilidad, previews, OTP y `/client/*` siguen `no-store`. | Saber que el catálogo puede tardar hasta 60 s. |
| Mails | SMTP dentro del request | La reserva pública y las transiciones del panel responden sin esperar al mail; el mail sale por Celery/outbox con hasta ~20 s de demora. | No (solo expectativa de tiempos). |
| "Pagué y sigue pendiente" | hasta 5-6 min | conciliación a demanda al consultar el estado pendiente > 20 s; el sondeo del front debería usar backoff (R12-05). | Recomendado: backoff 2 → 5 → 15 s. |
| Errores de MP al cliente | texto crudo del proveedor | 503 `PAYMENT_PROVIDER_UNAVAILABLE`, 502 `PAYMENT_LINK_CREATION_FAILED`, 409 `PAYMENT_GATEWAY_NOT_CONNECTED`, mensajes fijos. | Mostrar `message`. |
| `/ops/slo` | — | métricas de atraso (`oldest_pending_*`, `oldest_pending_email_send_seconds`). | No. |

## Cambios posteriores al inventario (Fase 3 y 5, 2026-09-24, `integration/aud2` @ 9214b37)

Todos aditivos; ninguna ruta cambia; `test_frontend_routes_contract.py` intacto.

| Área | Antes | Después | ¿El front tiene que hacer algo? |
|---|---|---|---|
| `GET /appointments/search` | `total` siempre; solo `page`/`page_size` | `include_total` (default `true`; con `false` → `total: null`, para páginas > 1); `after` (cursor opaco ≤ 200 chars) y `next_cursor` en toda respuesta (`null` en la última página); `after` con `page > 1` o cursor inválido → 422; orden estable `(starts_at DESC, id DESC)`. | Tipo TS `total: number \| null` (solo null si mandó `include_total=false`); opcional: paginar por cursor. |
| `GET /reports/summary` | solo `asc` | `order=asc\|desc` (default `asc`); `order=desc&limit=6` = los 6 más recientes; valor inválido → 422. | Opcional. |
| `GET /ledger/customers/{id}` | `offset` | `after` cursor sobre `(created_at, id)` + `next_cursor`; `after` con `offset > 0` → 422; sin acceso financiero → 403 antes de mirar el cursor. | Opcional. |
| `GET /public/client/{store}/{phone}/appointments` | sin tope | `limit` (default 50, 1..200, 422 fuera), más recientes primero. | Saber que sin `limit` corta en 50. |
| Disponibilidad | recalculada por request | HIT sin tocar la base; agenda del día cacheada (300 s, invalidada por los mismos caminos que antes); tras editar tienda/servicio/bloqueo o reservar, la grilla cambia en el mismo request siguiente. | No. |
| Panel | 31 sentencias al abrir | 15; mismos números en pantalla (tests de equivalencia sobre fixtures con historial). | No. |

