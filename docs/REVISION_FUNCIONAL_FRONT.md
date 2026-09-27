# Revisión funcional del frontend de Shifty contra el backend

- **Fecha:** 2026-09-24. **Base:** `integration/aud2` @ 9214b37. **Revisado contra el código actual**, solo lectura, sin ejecutar nada.
- **Para:** Enrique, dueño del front. Cada hallazgo dice qué ve el usuario, dónde está en el front, qué hace el backend y qué se propone.
- **Historia:** la primera versión se escribió el mismo día sobre 977cb44. Desde entonces entraron al front 24 archivos (merge ab64086 de `origin/main` e63d107: cb7e856, c0b6727, ab29b67, bd9d20b, c177f94, 2e2b218, bf5f085, 4c0e00b, b64a671) y al backend las Fases 1, 2, 3 y 5 del plan de rendimiento. Cada hallazgo se volvió a verificar y todas las referencias `archivo:línea` apuntan al código de 9214b37.
- **Contratos del backend:** el detalle de rutas, esquemas, códigos de error y permisos está en [docs/INVENTARIO_INTEGRACION.md](INVENTARIO_INTEGRACION.md). Los cambios posteriores (Fase 2 y Fases 3 y 5) están en sus dos secciones "Cambios posteriores al inventario"; acá se citan solo donde tocan un hallazgo.
- **Rutas:** las del front son relativas a `frontend/src/`. Las del back son relativas a `backend/modules/`, salvo `main.py`, `core/…` e `infrastructure/…`, que son relativas a `backend/`.

## Cómo leer los estados

| Estado | Significa |
|---|---|
| **Vigente** | El síntoma sigue igual en el código actual. |
| **Parcial** | Un commit arregló una parte del síntoma; lo que queda se describe. |
| **Resuelto en `<commit>`** | El síntoma ya no ocurre; el hallazgo queda listado como registro. |
| **No aplica** | El código o el contrato cambió y el hallazgo perdió sentido. |
| **Sin confirmar** | No se pudo verificar leyendo el código; se dice por qué. |

Etiqueta adicional: **Contrato de backend en curso (rama perf/f4-back)**. Marca la parte de la propuesta que necesita un contrato nuevo del backend. El backend lo está implementando ahora; este documento **no** describe la forma final, así que no conviene programar contra una forma supuesta.

## Resumen

36 hallazgos (FF-01 a FF-36), con sus ids y severidades originales.

| Estado | Alta | Media | Baja | Total |
|---|---|---|---|---|
| Vigente | 5 | 21 | 10 | 36 |
| Parcial | 0 | 0 | 0 | 0 |
| Resuelto | 0 | 0 | 0 | 0 |
| No aplica | 0 | 0 | 0 | 0 |
| Sin confirmar | 0 | 0 | 0 | 0 |

Qué cambió desde la primera versión:

- **Ninguno quedó resuelto.** Los commits del merge tocan código vecino sin cerrar el síntoma: cb7e856 lee bien el `errorCode` en un solo handler (FF-02, FF-17), c0b6727 tipa el `NotFoundError` del staff (FF-35), 2e2b218 mapea el alta de usuarios a camelCase pero sigue mandando `''` (FF-10), bd9d20b navega sin recarga hacia Configuración pero no al vencer la sesión (FF-36).
- **FF-04 se agravó.** Desde 0fd204f el backend exige `accepts_terms: true` en `POST /public/appointments`, y el alta del panel no lo manda: hoy **todo** "Nuevo turno" del panel responde 422.
- **Referencias corregidas.** `ReportsService.ts` (FF-18, FF-30) y `AppointmentBlocksService.ts` (FF-11) citaban líneas que no existen en esos archivos (tienen 168 y 112 líneas). La primera versión contaba 6 Alta, 22 Media y 8 Baja; el conteo real de sus propias severidades es 5, 21 y 10.
- **Contratos nuevos citados donde afectan:** 409 `PAYMENT_GATEWAY_NOT_CONNECTED`, 502 `PAYMENT_LINK_CREATION_FAILED` y 503 `PAYMENT_PROVIDER_UNAVAILABLE` (FF-02); `accepts_terms` obligatorio (FF-04); `limit` en el historial del cliente (FF-05); horizonte de 120 días en la disponibilidad pública (FF-06); 422 `EXPORT_TOO_LARGE` (FF-18); `total` y cursor en el fiado (FF-20); caché del catálogo público de hasta 60 s y subida de imagen de servicio (FF-22); `order=desc` en el resumen de reportes (FF-30).
- **Con contrato de backend en curso (rama perf/f4-back):** FF-04, FF-12 (filtro de bloqueos), FF-14, FF-16, FF-20 y FF-24.

Lo más urgente:

- **FF-04:** el alta de turnos del panel está rota (422 por `accepts_terms`) y además hereda las reglas del portal.
- **FF-01 y FF-02:** los 409 de negocio tardan 14-17 s en verse y ningún `error_code` llega a la UI; 402, 429, 502 y 503 salen como `InternalServerError`.
- **FF-03:** un profesional creado desde el panel no ofrece turnos porque no hay pantalla de horarios por profesional.
- **FF-10:** crear o editar usuarios sin nombre da 422 porque se manda `''` en vez de `null`.
- Agenda y bloqueos (FF-11 a FF-14, FF-31), portal "Mis turnos" (FF-05 a FF-07, FF-16), tienda suspendida (FF-15), fallas silenciosas (FF-17) y logout sin limpiar la caché (FF-26).

---

## Hallazgos

### FF-01 · Alta · Transversal (PATCH/PUT/DELETE)
**Estado: Vigente.**
- **Síntoma:** ante un 409 de negocio el usuario espera 14-17 s antes de ver el error (reintentos a los 2, 4 y 8 s, más azar), y suele volver a hacer clic. En el portal cada reintento consume rate limit de escritura pública.
- **Front:** `infrastructure/http/client.ts:79-83` (solo excluye POST; reintenta `status === 409`); `:86-95` (`retries: 3`, espera `2^n·1000` ms + hasta 1 s).
- **Back (409 que hoy se reintentan):** `appointment_blocks/service.py:308-317` (`BLOCK_HAS_APPOINTMENTS`, ahora también en el PATCH de un bloqueo); `public_api/service.py:930-941` (`CANCELLATION_WINDOW_EXPIRED`, cancelar y reprogramar desde "Mis turnos"); `public_api/service.py:975-999` (`PAID_APPOINTMENT_RESCHEDULE_DENIED`); `main.py:262-271` (`CONCURRENT_MODIFICATION`, que ahora también cubre deadlock y `lock_timeout`); `main.py:375-394` (`RESOURCE_CONFLICT`: slug o email duplicado).
- **Propuesta:** no reintentar nunca un 409; a lo sumo `CONCURRENT_MODIFICATION` en GET. Es el mismo punto que F4-04 del anexo.

### FF-02 · Alta · Transversal (mapeo de errores)
**Estado: Vigente.** cb7e856 agregó la lectura correcta (`error.context?.errorCode`) en `ForbiddenErrorHandler` para `FEATURE_DISABLED` (`shared/errors/handlers/SpecificHandlers.ts:63`), pero ese handler solo escribe en consola (FF-17) y el resto del front sigue leyendo `error.response.data`.
- **Síntoma:** nunca aparecen los mensajes de conflicto de estado, la agenda no se recarga tras un conflicto y ninguna pantalla reacciona a un `error_code`. El `message` del backend sí llega, porque `getErrorMessage` cae a `error.message`.
- **Front:** `shared/errors/getErrorMessage.ts:29-41` lee `error.response.data.error_code`; `infrastructure/http/client.ts:171-181` rechaza con `normalizeApiError(...)`, que no conserva `response` (el código queda en `context.errorCode`, `infrastructure/http/api-contract.ts:108-122`); `presentation/containers/CalendarContainer.tsx:521,558`: `isStateConflictError` siempre da false; `api-contract.ts:124-150`: 402, 429, 502 y 503 terminan en `InternalServerError`. Ningún uso de `BLOCK_HAS_APPOINTMENTS`, `CANCELLATION_WINDOW_EXPIRED`, `SUBSCRIPTION_SUSPENDED`, `UPSTREAM_UNAVAILABLE`, `RATE_LIMIT_UNAVAILABLE` ni `OTP_*`.
- **Back:** `main.py:195-207` (handler de `AppException`), `core/responses.py:51-62`. Códigos nuevos de la Fase 2 que caen en el mismo problema: 409 `PAYMENT_GATEWAY_NOT_CONNECTED`, 502 `PAYMENT_LINK_CREATION_FAILED` y 503 `PAYMENT_PROVIDER_UNAVAILABLE` en la reserva pública (`public_api/service.py:313-344`) y en el link de pago del panel (`payments/router.py:674-697`). El 503 `RATE_LIMIT_UNAVAILABLE` y los 429/503 del borde traen `Retry-After`, que `normalizeApiError` descarta.
- **Propuesta:** leer `(error as ApplicationError).context?.errorCode`; clases (o `code`) para 402, 429, 502 y 503; conservar `Retry-After` en el contexto.

### FF-03 · Alta · Personal / disponibilidad pública
**Estado: Vigente.**
- **Síntoma:** un profesional dado de alta desde el panel no tiene horario propio; el portal muestra "sin turnos" y la pestaña Horarios de Configuración no lo arregla.
- **Front:** ningún llamado a `/staff/{id}/schedules` en todo `frontend/src` (`application/services/StaffService.ts:16-108`); `presentation/pages/Settings.tsx:933-1045` solo edita `business_hours`.
- **Back:** `staff/router.py:98-179` (alta, edición y baja de franjas); `appointments/availability.py:463-475` (los slots salen solo de `Schedule` por profesional); `stores/router.py:88-111` (`business_hours` escribe `StoreSchedule`, otra tabla). Defecto latente para cuando exista el editor: `PATCH /staff/{id}/schedules/{sid}` con `start_time: null` compara `None >= time` y da 500 (`staff/repository.py:264-267`, `staff/schemas.py:36-38`).
- **Propuesta:** editor de horarios por día en el formulario de profesional, o "copiar horario del local" (`POST /staff/{id}/schedules`). Alternativa de backend, a decidir: un profesional sin horario usa el del local. El catálogo público se cachea hasta 60 s (`public_api/router.py:180`): un profesional nuevo puede tardar eso en aparecer.

### FF-04 · Alta · Agenda, "Nuevo turno" del panel
**Estado: Vigente, agravado por 0fd204f.** Contrato de backend en curso (rama perf/f4-back).
- **Síntoma:** desde 0fd204f el backend rechaza toda reserva sin `accepts_terms: true` (422 "Para reservar hay que aceptar los terminos y la politica de sena"), y el panel no lo manda: **ningún** alta desde "Nuevo turno" funciona. Aun con ese campo, el dueño seguiría sin poder cargar un cliente para "ahora" (antelación mínima), en tiendas con campos extra obligatorios ni en servicios con seña obligatoria (422), ni con la tienda suspendida ("Tienda no encontrada" en vez de 402). Le aplica el rate limit de escritura pública.
- **Front:** `infrastructure/repositories/HttpBookingRepository.ts:157-160` usa `POST /public/appointments`; `presentation/components/organisms/NewAppointmentModal.tsx:184-196` no manda `accepts_terms`, `custom_fields` ni `payment_method`; `domain/repositories/IBookingRepository.ts:9-19` (`CreateBookingInput` no tiene esos campos).
- **Back:** `public_api/schemas.py:89-92,116-122` (`accepts_terms` obligatorio); `public_api/service.py:449-459` (antelación, `BOOKING_NOTICE_REQUIRED`), `:122-169` (campos extra requeridos), `:172-206` (seña obligatoria), `:440-442` (suspendida → 404); `public_api/router.py:487-491`; `appointments/schemas.py:15-20` (`POST /appointments/` no acepta datos del cliente).
- **Propuesta:** un alta del panel propia, sin antelación, OTP ni seña obligatoria. El contrato lo está definiendo el backend; no se describe acá. Mientras tanto no hay arreglo sano del lado del front: mandar `accepts_terms: true` desde el panel registraría un consentimiento que el cliente no dio.

### FF-05 · Media · Portal, "Mis turnos" (OTP)
**Estado: Vigente.**
- **Síntoma:** si el teléfono quedó "verificado" en el asistente (sessionStorage, 30 min), "Mis turnos" entra sin pedir código y el backend responde 403; la pantalla dice "No encontramos turnos". "Salir" y volver entra otra vez por el atajo: bucle de 30 min. Igual cuando la ficha no tiene email entregable.
- **Front:** `presentation/components/organisms/ClientOtpGate.tsx:35-39,43`; `presentation/components/organisms/booking/BookingWizardContainer.tsx:170`; `presentation/containers/ClientAppointmentsContainer.tsx:123-127` (mismo texto para 403, 404, 429 y 503).
- **Back:** `public_api/service.py:209-242` (`require_recent_client_otp` exige el email de la ficha; distinto de lo que habilita reservar); `public_api/router.py:615` (403 `OTP_VERIFICATION_REQUIRED`), `:617-623` (404 `CLIENT_APPOINTMENTS_NOT_FOUND`). Nuevo (Fase 3): el historial acepta `limit` (default 50, 1..200, más recientes primero; `public_api/router.py:584-600`); el front no lo manda, así que un cliente con más de 50 turnos ve solo los 50 últimos.
- **Propuesta:** no saltar el pedido de código si el GET da 403 (`forgetOtpVerification` ante `OTP_VERIFICATION_REQUIRED`); distinguir 403, 404 y 429.

### FF-06 · Media · Portal, "Mis turnos" (reprogramar)
**Estado: Vigente.**
- **Síntoma:** el cliente elige fecha y hora libres (input `time`) sin la grilla: termina en 409 o 400.
- **Front:** `presentation/containers/ClientAppointmentsContainer.tsx:80` (`argentinaLocalToUtcIso(date, time)`), `:198-219`. Contradice CLAUDE.md ("el front manda el `starts_at` del slot tal cual").
- **Back:** `public_api/router.py:691-729`; `public_api/service.py:853-904` (ventana de cancelación, turno pagado, slot nuevo).
- **Propuesta:** reutilizar `BookingStepDateTime` y mandar `slot.starts_at`. La disponibilidad pública ahora acepta solo fechas entre ayer y hoy + 120 días (422 fuera, `public_api/router.py:265-283`); la grilla de 14 días del asistente entra en ese horizonte.

### FF-07 · Baja · Portal, cancelar sin confirmación
**Estado: Vigente.** `presentation/containers/ClientAppointmentsContainer.tsx:62-71,182-194`: un toque cancela. Agregar confirmación.

### FF-08 · Media · Configuración, Horarios
**Estado: Vigente.**
- "+ Bloque" deja cargar dos franjas por día y el guardado falla con un 422 técnico ("Por ahora cada dia admite un solo periodo de apertura"); no valida apertura < cierre; cada cambio remonta la fila y el input pierde el foco.
- **Front:** `presentation/pages/Settings.tsx:1025-1039` ("+ Bloque"), `:972` (key con `open`/`close`). **Back:** `stores/schemas.py:41-57` (`open < close`), `:147-161` (un período por día); `stores/router.py:88-111`.
- **Propuesta:** un período por día (ocultar "+ Bloque"); validar `open < close`; `key={`${day.id}-${idx}`}`.

### FF-09 · Media · Usuarios
**Estado: Vigente.** El admin de tienda ve "Administrador" y recibe 403 `PERMISSION_DENIED` (`presentation/components/organisms/UserFormModal.tsx:190`; back `core/roles.py:84-117`, `users/router.py:31,105`). Mostrar `admin` solo si `is_global_admin` o si el editado ya es admin.

### FF-10 · Alta · Usuarios
**Estado: Vigente.** 2e2b218 reemplazó el cast snake_case del alta por un mapeo explícito, pero sigue pasando `''` tal cual.
- **Síntoma:** crear sin nombre o apellido → 422; editar un usuario al que le falte nombre (para cambiar el rol) → 422; vaciar el teléfono guarda `''`.
- **Front:** `presentation/components/organisms/UserFormModal.tsx:42-44` (`|| ''`); `presentation/containers/UserManagementContainer.tsx:54-75`; `infrastructure/repositories/HttpUserRepository.ts:79-86,96-98`; `application/validators/user.validators.ts:8-9`; `domain/use-cases/user/CreateUserUseCase.ts:29-31` (`'' ?? null` sigue siendo `''`).
- **Back:** `users/schemas.py:25-26,43-44` (`min_length=1`); `users/router.py:113-118` (`exclude_unset`: `null` borra).
- **Propuesta:** `'' → null`; en PATCH mandar solo lo que cambió.

### FF-11 · Media · Agenda, editar bloqueo
**Estado: Vigente.** Cambiar el profesional no tiene efecto (y dice "actualizado"); si el bloqueo pasa a pisar turnos, llega un 409 `BLOCK_HAS_APPOINTMENTS` sin vista previa ni opción de cancelarlos. **Front:** `presentation/containers/CalendarContainer.tsx:465-477`; `application/services/AppointmentBlocksService.ts:98-107` (el tipo admite `cancel_affected`, pero nadie lo manda). **Back:** `appointment_blocks/schemas.py:116-125` (sin `staff_id`; `cancel_affected` ya existe en el PATCH); `appointment_blocks/service.py:308-324`. **Propuesta:** deshabilitar el selector de profesional al editar; `/preview` + `BlockPreviewModal` + `cancel_affected: true` (solo admin, ver FF-34).

### FF-12 · Media · Agenda, bloqueos desactivados siguen visibles
**Estado: Vigente.** Contrato de backend en curso (rama perf/f4-back) para el filtro de bloqueos (F4-07 del anexo).
`presentation/containers/CalendarContainer.tsx:263-268, 299-313, 370-372, 1188-1256` no filtran `is_active` (solo `:776` lo hace). El backend devuelve todos, activos e inactivos, de toda la historia (`appointment_blocks/router.py:99-111`). Filtrar `is_active` en el front ya; el filtro del lado del servidor es parte del contrato en curso.

### FF-13 · Media · Agenda, series recurrentes cortadas en 5
**Estado: Vigente.** `presentation/containers/CalendarContainer.tsx:201` (y `:402`, `:416`: `max_occurrences: 5`), `:1140-1153` (input sin etiqueta, tope 60). El backend permite hasta 120 (`appointment_blocks/schemas.py:102,167`; expansión en `appointment_blocks/service.py:114-133`). Calcular desde `recurrence_until` o mostrar "Se crearán N".

### FF-14 · Media · Agenda para Recepción
**Estado: Vigente.** Contrato de backend en curso (rama perf/f4-back) para un GET de bloqueos accesible a recepción.
Recepción ve el formulario de bloqueos, pero la lista y las plantillas dan 403 (`presentation/containers/CalendarContainer.tsx:225-226, 1042-1178`; back `appointment_blocks/router.py:46-52, 104-105, 214-215`). Ocultar el formulario a recepción.

### FF-15 · Media · Panel con tienda suspendida
**Estado: Vigente.** Banner "solo lectura", pero todo sigue habilitado y cada acción falla con 402 `SUBSCRIPTION_SUSPENDED` (a veces sin aviso, FF-17). `application/services/StoreSettingsService.ts:73` (`blocks_writes` sin uso); `presentation/components/molecules/SubscriptionBanner.tsx:32-38`; `infrastructure/http/api-contract.ts:124-150` (402 → `InternalServerError`). Back: `billing/dependencies.py:39-73` (escrituras permitidas), `:89-105`. Las subidas de imagen nuevas (`POST /services/{id}/image`, `/stores/me/media`) no están en la lista: también dan 402. Exponer `blocksWrites` y deshabilitar todo salvo las escrituras permitidas.

### FF-16 · Media · Portal con tienda suspendida
**Estado: Vigente.** Contrato de backend en curso (rama perf/f4-back).
El cliente no puede entrar a "Mis turnos" para cancelar ("Negocio no encontrado"), aunque el backend le permite cancelar y reprogramar. `presentation/pages/ClientAppointments.tsx:13,23-29` depende de `GET /public/stores/{slug}`, que da 404 con la tienda suspendida (`public_api/router.py:133-145`). Hace falta resolver la tienda desde el slug aun suspendida; la forma la está definiendo el backend.

### FF-17 · Media · Fallas silenciosas
**Estado: Vigente.** cb7e856 cambió el texto del 403 por función apagada, pero `showToast` sigue siendo solo `console.warn` (`shared/errors/handlers/SpecificHandlers.ts:15-17`). Llamados sin manejo de error: `presentation/containers/UserManagementContainer.tsx:36`, `presentation/containers/ServiceManagementContainer.tsx:36`, `presentation/containers/StaffManagementContainer.tsx:147`, `presentation/containers/WaitlistContainer.tsx:249`, `presentation/components/navigation/NotificationsBell.tsx:97,122`. Back: `users/router.py:131-136` (400 al darse de baja a sí mismo), `core/roles.py:156-161` (403 sobre otro admin), `billing/dependencies.py:104-105` (402). Toast real o `mutateAsync` con catch.

### FF-18 · Media · Reportes, exportar
**Estado: Vigente.** El profesional ve los botones y recibe un 403 crudo; los errores con `responseType: 'blob'` muestran el mensaje de axios ("Request failed with status code …"). `application/services/ReportsService.ts:133-165`; `infrastructure/http/api-contract.ts:84-96,182-187`; `presentation/pages/Reports.tsx:55-70,268-307`. Back: `reports/router.py:132-145` (`REPORT_EXPORTERS`), `core/roles.py:59`. Nuevo (Fase 1): más de 20.000 turnos en el rango → 422 `EXPORT_TOO_LARGE` con el motivo (`reports/router.py:148-158`, `reports/service.py:47`), que hoy tampoco se lee por el mismo problema del blob. Ocultar los botones a quien no es admin; parsear `blob.text()`.

### FF-19 · Media · Reportes, rango inválido
**Estado: Vigente.** La pantalla de error reemplaza la página y esconde los selectores de fecha (`presentation/pages/Reports.tsx:87-119`). Back: `reports/service.py:400-409` (más de 370 días o `from > to`), `core/config.py:283`, `reports/router.py:86-87` (400). Mostrar el error debajo del encabezado y validar el rango en el front.

### FF-20 · Media · Cuentas pendientes (fiado)
**Estado: Vigente.** Contrato de backend en curso (rama perf/f4-back) para la lista o búsqueda de clientes que necesita el profesional.
El profesional no ve clientes (403 en `/users/`); el admin ve los primeros 200 usuarios de cualquier rol y los filtra en el navegador; la ficha muestra 50 movimientos sin indicar que hay más. `presentation/pages/Ledger.tsx:27-33`; `presentation/hooks/useManagedUsers.ts:5-9`; `application/services/LedgerService.ts:13-17,42-45`. Back: `users/router.py:40-63` (`get_current_admin`; ya acepta `role`, `limit` ≤ 500 y `offset`); `ledger/router.py:46-47` (página de 50, máx. 200), `:55-57`, `:192-270`; `ledger/schemas.py:28-37` (`total` y, desde la Fase 3, `next_cursor`; orden más nuevo primero). Pedir `?role=client`; usar `total` y paginar con `after`/`next_cursor`. Es F4-03 del anexo.

### FF-21 · Media · Cobros online, para el profesional
**Estado: Vigente.** Pantalla con contadores en cero; "Actualizar" y "Registrar devolución" dan 403. `App.tsx:136-147`; `presentation/components/navigation/Sidebar.tsx:89-94`. Back: `payments/router.py:141-150` (guardas), `:741` (devolución), `:875` (estadísticas del outbox), `:909` (conciliación), `:977` (procesar outbox), todas `_require_payment_admin`. Quitarle la pantalla al profesional o mostrarle solo la configuración.

### FF-22 · Media · Servicios
**Estado: Vigente.** Un servicio borrado o desactivado desaparece y no se puede reactivar. `infrastructure/repositories/HttpServiceRepository.ts:21-24` (sin `include_inactive`); `presentation/components/molecules/ServiceCard.tsx:45-53` (solo muestra el estado). Back: `services/router.py:50-80` (`include_inactive=true`, solo admin). Listar con `include_inactive=true` y agregar "Reactivar". Relacionado, de la Fase 2: el backend ahora sube la imagen del servicio (`POST`/`DELETE /services/{id}/image`, `services/router.py:153-190`) y el front no lo usa; una `image_url` externa no se ve porque la CSP solo permite imágenes propias (`img-src 'self' data: blob:`, `frontend/security-headers.conf:10`). El catálogo público se cachea hasta 60 s (`public_api/router.py:180`): un servicio reactivado tarda eso en verse en el portal.

### FF-23 · Media · Promociones, editar
**Estado: Vigente.** No se puede quitar vigencia, tope, mínimo ni descripción: un campo vacío manda `undefined` (`presentation/pages/Promotions.tsx:64-80`). Back: `promotions/service.py:200-245` (`exclude_unset`; `null` borra). Mandar `null`.

### FF-24 · Media · Superadmin, listado
**Estado: Vigente.** Contrato de backend en curso (rama perf/f4-back) para "todas".
"Todas" muestra solo activas y corta en 50 (`presentation/pages/SuperAdmin.tsx:97-103`, `application/services/SuperAdminService.ts:257-268`: con "todas" no manda `is_active`; back `superadmin/router.py:86-102`, `is_active` con default `True`, `limit` default 50 y máx. 200, `offset`). Paginar con `offset` (F4-10 del anexo); el filtro "todas" espera el contrato.

### FF-25 · Media · Portal, lista de espera sin email
**Estado: Vigente.** Se anota sin email, se le ofrece el cupo igual, nadie recibe el aviso y la oferta vence; tras dos ofertas vencidas (`MAX_LAPSED_OFFERS`) la entrada expira sola. `presentation/components/organisms/booking/WaitlistJoinForm.tsx:57-60,93,135-144`. Back: `waitlist/offers.py:107-145` (no filtra por email), `:273-283` (ofrece a la primera entrada), `:367-377` (sin email entregable no arma el mail); `waitlist/schemas.py:34` (email opcional). Exigir email en el front; en el backend, saltear las entradas sin email entregable (decisión de backend).

### FF-26 · Media · Cambio de usuario en el mismo equipo
**Estado: Vigente.** Tras logout y login con otro usuario se ven datos del anterior (caché de react-query). `presentation/context/AuthContext.tsx:92-103` (logout) y `:68-76` (`SESSION_EXPIRED_EVENT`) no llaman `queryClient.clear()`. Hacerlo en los dos.

### FF-27 · Baja · Agenda, OTP en "Nuevo turno"
**Estado: Vigente.** "Teléfono validado" nunca aparece: `presentation/components/organisms/NewAppointmentModal.tsx:513` compara cadenas crudas contra el teléfono normalizado que devuelve el backend (`otp/service.py:53-62`), aunque `:137` ya usa `phoneDigits`. El texto de `:454` dice que el código va al email tipeado, pero si el teléfono ya es de un cliente con email entregable va a ese email. Usar `phoneDigits` y copiar el texto del asistente. Hoy queda tapado por FF-04.

### FF-28 · Baja · Configuración, Funciones
**Estado: Vigente.** "Reportes avanzados" y "Agenda nueva" no cambian nada (`presentation/pages/Settings.tsx:84-93`; `core/feature_flags.py:9-10`: ningún código del backend los lee); el de OTP dice "SMS o WhatsApp" pero va por email (`Settings.tsx:94-98`). Ocultar los dos primeros y corregir el texto.

### FF-29 · Baja · Duplicados
**Estado: Vigente.** "El registro entra en conflicto con uno existente" sin decir qué campo (`presentation/components/organisms/UserFormModal.tsx:72`; `presentation/pages/Settings.tsx:245-247`). Back: `main.py:375-394` (409 `RESOURCE_CONFLICT` neutro para email y slug); `users/service.py:30-50`; `stores/router.py:249`. El alta de admin del superadmin sigue respondiendo 400 "Ya existe un usuario con ese email" (`superadmin/repository.py:438-443`, `superadmin/router.py:277-278`). Traducir `RESOURCE_CONFLICT` por formulario ("ese email ya existe", "ese slug ya está en uso").

### FF-30 · Baja · Reportes, detalle cortado en 2000
**Estado: Vigente.** `application/services/ReportsService.ts:62-71` (`ReportSummary` sin `has_more`) y `:114-119` (sin `limit` ni `offset`); la tabla de `presentation/pages/Reports.tsx:504` muestra lo que llega. Back: `reports/router.py:62-88` (`limit` default 2000, máx. 5000; `offset`; desde la Fase 3, `order=asc|desc`), `reports/schemas.py:91` (`has_more`). Paginar o mostrar "mostrando N de total".

### FF-31 · Media · Agenda, transiciones que faltan
**Estado: Vigente.** No se puede cancelar un turno confirmado ni reprogramar desde el panel (`presentation/components/molecules/AppointmentActions.tsx:31-75`; `AppointmentService.cancel` y `.reschedule`, `application/services/AppointmentService.ts:75-79,108-112`, no tienen llamadores). El backend permite `confirmed → cancelled` (`infrastructure/persistence/models/appointment.py:45-53`) y expone `PATCH /appointments/{id}/cancel` y `/reschedule` (`appointments/router.py:235-249, 316-357`). Agregar "Cancelar" y "Reprogramar".

### FF-32 · Baja · Portal, paso final (seña)
**Estado: Vigente.** Con menos de 6 dígitos la vista previa da 422 y el botón de MP parpadea (`presentation/components/organisms/booking/BookingStepConfirmation.tsx:130-145`; back `public_api/router.py:333`, `client_phone` con `min_length=6`). Mandar `client_phone` solo con 6 dígitos o más y `placeholderData`/`keepPreviousData`. F4-06 del anexo cubre además la request por tecla.

### FF-33 · Baja · Portal, después de un 409
**Estado: Vigente.** El horario ocupado sigue viéndose libre al volver al paso 2 (`presentation/components/organisms/booking/BookingStepConfirmation.tsx:225-229`; `presentation/hooks/usePublic.ts:62`, `staleTime` de 30 s; `useCreatePublicBooking` en `:65-68` no invalida nada). `invalidateQueries(['public-availability'])` ante un error de reserva.

### FF-34 · Baja · Bloqueo del profesional sobre turnos
**Estado: Vigente.** El profesional ve "Cancelar N turnos y bloquear" y recibe 403 (`presentation/components/organisms/BlockPreviewModal.tsx:133-139`; back `appointment_blocks/service.py:320-324`). Reemplazar por "Pedile al administrador".

### FF-35 · Baja · Código muerto de 404
**Estado: Vigente.** c0b6727 hace que `StaffService.updateStaff` lance `NotFoundError` cuando `findById` devuelve `null`, pero las ramas "404 devuelve `null`" de los repositorios nunca se ejecutan, porque el error que llega ya no tiene `response` (`infrastructure/repositories/HttpUserRepository.ts:69-72`, `infrastructure/repositories/HttpServiceRepository.ts:31-33`, `infrastructure/repositories/HttpStaffRepository.ts:31-33`). Usar `instanceof NotFoundError`.

### FF-36 · Baja · Volver adonde estaba al vencer la sesión
**Estado: Vigente.** bd9d20b cambió a `navigate` el salto de Cobros a Configuración, no el de sesión vencida. `presentation/pages/Login.tsx:31` va siempre a la ruta por defecto del rol; `shared/errors/handlers/SpecificHandlers.ts:46-52` usa `window.location.href` (recarga completa). Guardar `location` y volver ahí, sin recargar.

---

## Verificado sin hallazgo

Re-verificado el 2026-09-24 sobre 9214b37.

- La devolución manda `manual: true` (`presentation/pages/Payments.tsx:62`).
- El `starts_at` del asistente se toma del slot tal cual (`presentation/components/organisms/booking/BookingStepDateTime.tsx:286`, `presentation/components/organisms/booking/BookingWizardContainer.tsx:337-339`).
- La tira de días del asistente muestra 14 días, dentro del horizonte nuevo de 120 días de la disponibilidad pública. Solo un deep-link con una fecha más lejana cae fuera y recibe 422 (`BookingStepDateTime.tsx:60-67`).
- El canal del OTP está limitado a `email`; los textos del OTP son correctos en el asistente y en "Mis turnos".
- Clave de idempotencia: una por corrida, renovada tras el éxito; MP con seña 0 lo rechaza el backend.
- Doble envío protegido en la reserva pública y en el alta del panel.
- El 409 en "Nuevo turno" se detecta (`application/services/BaseService.ts:128-133` preserva `originalError`).
- Fechas de promociones con zona horaria.
- Vista previa de promociones por el endpoint público.
- Auditoría del superadmin: `public_id` string.
- Los contratos del Dashboard y de Notificaciones coinciden; las consultas del Dashboard respetan el rol.
- La búsqueda de turnos respeta `page_size ≤ 100` y pagina (`infrastructure/repositories/HttpBookingRepository.ts:58-85`). Los parámetros nuevos (`include_total`, `after`, `next_cursor`) son opcionales: sin mandarlos, `total` sigue siendo un número.
- Configuración: PATCH parcial por borrador.
- Terna de seña sin `undefined`; "full" limpia el monto.
- Recursos sin nombre ni email vacíos.
- Login: el 401 del login no se trata como sesión vencida (`infrastructure/http/client.ts:137,169-180`); refresh single-flight por pestaña (`:100-125`).
- El logout usa la cookie.
- El tope de 366 días de un bloqueo no es alcanzable desde la UI.
- Horas de bloqueos y del alta del panel convertidas desde hora argentina.
- Feature flags de la vitrina: solo `payments` y `otp_booking`.
- Las rutas sin barra final coinciden con `redirect_slashes=False` (`backend/main.py:186`).

## Sospechas no verificadas

- **Dispositivo fuera de la hora argentina:** la tira de días y la agenda usan la zona del navegador (`BookingStepDateTime.tsx:60-67,192-195`; `presentation/containers/CalendarContainer.tsx:217-219,337`). 4c0e00b corrigió un caso parecido (`HttpBookingRepository.findAllImpl`), no estos.
- **Reprogramar con seña acreditada: ya confirmada en el código.** `can_reschedule` es igual a `can_cancel` (`public_api/router.py:656`) y no mira el pago; el service rechaza con 409 `PAID_APPOINTMENT_RESCHEDULE_DENIED` (`public_api/service.py:975-999`). Lo mismo pasa con un turno `pending_payment`: `can_cancel` lo incluye (`public_api/router.py:636-645`), pero cancelar o reprogramar responde 409 `PAYMENT_APPOINTMENT_REQUIRES_RELEASE` con un texto pensado para administradores (`appointments/guards.py:18-34`). El cliente ve "Cambiar" y "Cancelar" y recibe el 409. Es un ajuste de `can_cancel`/`can_reschedule` en el backend; queda acá hasta decidirlo. Corrección de backend en curso (rama perf/f4-back): `can_cancel`/`can_reschedule` calculados con las mismas guardas que las acciones y mensaje de 409 para el cliente.
- `retry: 1` global reintenta GET con 403/429 y duplica el consumo de rate limit (`main.tsx:68`).
- Doble navegación al vencer la sesión (`SESSION_EXPIRED_EVENT` + `window.location.href`).
- `void mutateAsync` sin catch → `unhandledrejection` → handler global (`main.tsx:50-52`) → recarga a `/login` ante un 401, incluso fuera del panel.

---

## Anexo · Rendimiento del front (Fase 4 del plan)

Sale del plan de corrección de rendimiento (Fase 4, "Frontend") y de la auditoría de rendimiento del 2026-09-24. Esos documentos no se versionan: acá va cada ítem con su origen resuelto en una línea, re-verificado contra 9214b37. Ninguno está hecho todavía en el front. La columna "Parte de backend" dice qué hizo o está haciendo el backend para ese ítem.

Dos de severidad Alta **no son de velocidad**: F4-01 y F4-03 cierran sesiones y esconden datos.

| Id | Qué (front) | Origen | Parte de backend |
|---|---|---|---|
| F4-01 | **Refresh coordinado entre pestañas**: un solo `refreshAccessToken` (también para `AuthContext`), `navigator.locks` + `BroadcastChannel`, con el token solo en memoria (regla 28). | Alta: el refresh no se coordina entre pestañas (`infrastructure/http/client.ts:100-125`; `presentation/context/AuthContext.tsx:42-45` no pasa por él). La rotación revoca la sesión anterior y un "reuso" revoca **todas** las del usuario: dos refresh en un RTT (dos pestañas, restaurar sesión, `StrictMode` en dev) cierran la sesión en todos los dispositivos. | Ninguna: la rotación con detección de reuso se mantiene (regla 15). |
| F4-02 | Solo el 401 cierra la sesión; 429, 503, 5xx y errores de red reintentan respetando `Retry-After`. `AuthProvider` solo en el árbol autenticado. | Alta: cualquier fallo del refresh (429, 503, 5xx, red) cierra la sesión (`client.ts:116-119,171-180`; `AuthContext.tsx:51-56`); el bucket de `/auth/` es por IP y lo comparten login y refresh, así que una oficina detrás de NAT se desloguea. Media: `AuthProvider` envuelve todo y el portal público hace un `POST /auth/refresh` inútil (401) en cada visita. | Hecho: 503 `RATE_LIMIT_UNAVAILABLE` con `Retry-After: 5`; errores del borde (429/503) en JSON con `Retry-After`; el limitador cierra por política (auth, escritura pública, OTP) y deja abierta la lectura pública. `/auth/refresh` sigue en el bucket de `/auth/`. |
| F4-03 | **Fiado y Usuarios cortan en 200** sin paginar ni filtrar: `?role=client&include_inactive=false` + autocompletado; Usuarios con `offset`. Ver FF-20. | Alta (dato invisible): el listado de usuarios corta en 200 por default y el front no manda `role` ni `offset`; `presentation/pages/Ledger.tsx:27-33` filtra clientes en el navegador con `include_inactive=true`. En una tienda con más de 200 usuarios los clientes viejos no aparecen y no se les puede cargar fiado. | `GET /users/` ya acepta `role`, `include_inactive`, `limit` (≤ 500) y `offset`. Búsqueda por nombre y acceso del profesional: Contrato de backend en curso (rama perf/f4-back). |
| F4-04 | `axios-retry`: no reintentar 409 en PATCH/PUT/DELETE (hoy 14-17 s para ver "ocupado", ver FF-01); reintentar solo GET/HEAD ante red/502/503/504; `timeout` de 15 s en lecturas y 30 s en escrituras; `AbortSignal` en los servicios; clave de idempotencia del asistente en `sessionStorage`. react-query: `retry` solo ante errores transitorios, con `Retry-After`. | Media: `axios-retry` reintenta 409 en PATCH/PUT/DELETE (reprogramar, bloqueos, reprogramar público): 4 transacciones con lock por clic y 4 escrituras públicas contra el rate limit; sin `timeout`. Media: `retry: 1` de react-query reintenta 400/403/404/422 e ignora `Retry-After` (`normalizeApiError` descarta los headers). Media: sin `timeout` ni `AbortSignal`, una reserva queda colgada en red mala y al recargar se regenera la clave de idempotencia: 409 sobre su propio turno. | No requiere. Deadlocks y `lock_timeout` ahora salen como 409 `CONCURRENT_MODIFICATION`. |
| F4-05 | Vuelta de MP: sondeo 2 s → 5 s → 15 s, corte a `PAYMENT_HOLD_MINUTES`, respetar `Retry-After`. | Media: la vuelta de MP consulta el estado cada 2 s sin tope (`presentation/hooks/usePublic.ts:141-155`): 30 por minuto por pestaña, cientos por pestaña abandonada; pocas pestañas detrás de un NAT agotan el límite de lectura pública. | Hecho (Fase 2): conciliación a demanda al consultar un cobro pendiente de más de 20 s (`public_api/router.py:567`); "pagué y sigue pendiente" baja a menos de 30 s. |
| F4-06 | `/public/deposit/preview` con 8 dígitos o más y 400 ms sin tipear, o en `blur`. | Alta: `/public/deposit/preview` se pide en cada tecla del teléfono (`usePublic.ts:71-96`, `BookingStepConfirmation.tsx:130-136`). | No requiere (`client_phone` exige 6 caracteres o más, ver FF-32). |
| F4-07 | Agenda: `from_date`/`to_date`/`include_inactive` en `GET /appointment-blocks/` (back + front); `keepPreviousData` + prefetch del día vecino; modal de nuevo turno montado solo abierto; `total` de la página 1 y el resto de las páginas en paralelo. | Alta: `GET /appointment-blocks/` trae todos los bloqueos históricos de la tienda y se filtran en memoria (`appointment_blocks/router.py:99-111`; `CalendarContainer.tsx:263-268`). Media: la búsqueda pagina en serie e ignora `total` (`HttpBookingRepository.ts:58-85`). Media: la agenda del día no tiene `keepPreviousData` ni prefetch (`presentation/hooks/useCalendarAgenda.ts:8-14`). Media: `NewAppointmentModal` montado siempre pide servicios, staff y flags aunque no se abra (`NewAppointmentModal.tsx:77-80`; `CalendarContainer.tsx:1280`). | Filtro de bloqueos por fecha e `include_inactive`: en curso, rama perf/f4-back. Búsqueda: `include_total=false` y cursor `after`/`next_cursor` ya disponibles (Fase 3). |
| F4-08 | Vista mes: `dayKey` una vez por evento + `Map`; extraer `BlockForm`. Sin memo. | Media: la vista mes llama a `Intl.formatToParts` días × turnos veces en cada render (~77.000 con 2480 eventos; `CalendarContainer.tsx:322-328,869-873`). Baja: el formulario de bloqueos vive en `CalendarContainer` y cada tecla re-renderiza toda la agenda. | No requiere. |
| F4-09 | Dashboard: flags desde `/stores/me` (ya los trae), `limit=6` + `order=desc`; reportes con `has_more`. Ver FF-30. | Alta: el Dashboard espera `/stores/me/feature-flags` para pedir pagos, outbox y fiado aunque `/stores/me` ya trae `feature_flags`, y pide `/reports/summary` sin `limit` (hasta 2000 filas) para mostrar 6 (`presentation/pages/Dashboard.tsx:401-413`). Baja: la tabla de Reportes muestra hasta 2000 filas e ignora `has_more` (`Reports.tsx:504`; `ReportsService.ts:62-71`). | Hecho: `order=desc` + `limit` en `/reports/summary` (Fase 3); `has_more` ya existía; `/stores/me` ya trae `feature_flags` (`stores/schemas.py:229`). |
| F4-10 | Superadmin: "cargar más" con `offset`, búsqueda con debounce por timer, `keepPreviousData`, quitar el `useMemo` defensivo. Ver FF-24. | Media: el listado de tiendas corta en 50 y la búsqueda no tiene debounce: hasta 3 requests por tecla (lista, overview y auditoría por el reset de la selección; `presentation/pages/SuperAdmin.tsx:75-134`); `useMemo` defensivo (regla 27). | `/superadmin/stores` ya acepta `limit` (≤ 200) y `offset`. `is_active=all`: Contrato de backend en curso (rama perf/f4-back). |
| F4-11 | OTP en el celular: espera de 60 s para reenviar, `inputMode="numeric" autoComplete="one-time-code" maxLength={6}`; `autoComplete` en teléfono, nombre y email. | Media: el OTP no tiene espera para reenviar (quema los 5 pedidos por hora y queda bloqueado una hora) ni `inputMode`/`autoComplete`/`maxLength`. | No requiere (tope de 5 pedidos por hora, `core/config.py:224`). |
| F4-12 | `vite:preloadError` → recargar una vez. | Media: un deploy rompe los chunks lazy en las pestañas abiertas (404 del chunk viejo, pantalla en blanco) y no hay listener de `vite:preloadError`; recargar una vez con marca en `sessionStorage` (cada recarga suma un refresh, ver F4-02). | No requiere (`/assets/` con hash ya sale `immutable`, `frontend/nginx.conf:35`). |
| F4-13 | `recharts` con `lazy` + `Suspense` o SVG propio; Sentry diferido tras `load`, `browserTracingIntegration` para Web Vitals con muestreo 0,05-0,1, y `tunnel` o host en la CSP. | Alta (panel): el Dashboard baja un chunk de 427 KB por `recharts` (dos gráficos importados de forma estática). Media: Sentry (~45 KB) va en el entry y `tracesSampleRate` está inerte sin `browserTracingIntegration`. Media: nada mide LCP/INP/CLS y la CSP `connect-src 'self'` bloquea el envío al ingest de Sentry. | Ninguna todavía: la CSP (`frontend/security-headers.conf:10`) sigue con `connect-src 'self'`; falta decidir `tunnel` por `/api` o abrir el host. |
| F4-14 | Prefetch del chunk `PublicBooking` según la URL; servicios junto con la tienda. | Media: el portal encadena html → entry → chunk `PublicBooking` → API. Media: la reserva pública hace 2 idas y vueltas antes del paso 1 (tienda → servicios). | Servicios junto con la tienda: sin contrato por ahora (la tienda es `no-store` y los servicios se cachean 30 s en el borde; juntarlos pierde ese caché). Prefetch del chunk: solo front. `/public/services` y `/public/staff` ya salen con `s-maxage=30, stale-while-revalidate=30` (`public_api/router.py:180`): un cambio tarda hasta 60 s en verse. |
| F4-15 | `<img>` con `width`/`height`/`loading="lazy"`/`decoding`; `og:*` en `index.html`; `staleTime` de 5 min en `/stores/me`; paso del asistente en la URL; `react-query-devtools` a `devDependencies`; quitar las clases `animate-in` muertas. | Baja: `<img>` sin tamaño ni carga diferida (4 lugares). Baja: sin `og:*` en `index.html` (la vista previa en WhatsApp sale vacía). Baja: `/stores/me` sin `staleTime` propio, se vuelve a pedir en cada navegación. Baja: el paso del asistente no está en la URL y "atrás" en Android saca del portal. Baja: `@tanstack/react-query-devtools` está en `dependencies` (`frontend/package.json:61`) y hay 27 usos de `animate-in`/`fade-in` sin el plugin que los define. | Hecho (Fase 1): medios con `immutable`, `ETag` y 304. |
