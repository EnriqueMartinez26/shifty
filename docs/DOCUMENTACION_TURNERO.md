# Documentación Técnica: Módulo de Turnos (Turnero) 📅

Este documento detalla el funcionamiento, arquitectura y reglas de negocio del sistema de gestión de turnos de **Shifty**.

## 1. Introducción
El "Turnero" es el corazón de Shifty. Es un sistema **multi-tenant** diseñado para permitir que múltiples comercios (salones de belleza, barberías, etc.) gestionen sus agendas de forma independiente y segura.

---

## 2. Estados Terminales de un Turno

Los **estados terminales** son aquellos desde los cuales un turno **NO puede cambiar a otro estado**. Shifty define exactamente **tres estados terminales**:

### 1. COMPLETED (Completado)
- **Significado**: El turno se ejecutó exitosamente y el servicio fue completado
- **Terminal**: SÍ - No puede cambiar a otro estado
- **Impacto**: Genera ingresos, registra historial exitoso del cliente

### 2. CANCELLED (Cancelado)
- **Significado**: El turno fue cancelado antes de ejecutarse
- **Terminal**: SÍ - No puede cambiar a otro estado
- **Quién puede cancelar**: Cliente (con aviso mínimo) o Personal del salón (siempre)
- **Impacto**: No genera ingresos, libera el horario para otros clientes

### 3. ABSENT (Ausente - No-Show)
- **Significado**: El cliente NO asistió a un turno confirmado
- **Terminal**: SÍ - No puede cambiar a otro estado
- **Impacto**: No genera ingresos, afecta historial del cliente, puede aplicarse penalización
- **Diferencia de cancelación**: ABSENT es inasistencia (pasivo), cancelación es cancelación activa (activo)

### Resumen: Estados Terminales
```
Los ÚNICOS tres estados terminales son:
✓ COMPLETED
✓ CANCELLED
✓ ABSENT

Desde estos estados, un turno NO cambia a ningún otro estado.
```

---

## 3. Modelo de Datos Core
El modelo `Appointment` interactúa con varias entidades clave:

- **Store (Tenant):** El comercio al que pertenece el turno.
- **Staff (Profesional):** La persona que realizará el servicio.
- **Service (Servicio):** El tratamiento solicitado (define la duración y el precio).
- **User (Cliente):** La persona que reserva el turno.

### Ciclo de Vida: Estados PENDING a COMPLETED
Un turno comienza en estado **PENDING** (no-terminal) cuando el cliente lo solicita. Las reglas de transición PENDING → COMPLETED establece que NO hay transición directa: debe pasar por CONFIRMED primero.

### Atributos Destacados:
- `starts_at`: Fecha y hora de inicio.
- `ends_at`: Calculado dinámicamente (`starts_at` + `service.duration`).
- `idempotency_key`: Clave única para evitar reservas duplicadas por fallos de red.
- `notes_staff`: Notas privadas visibles solo para el equipo del comercio.
- `cancelled_at` / `completed_at`: Timestamps de auditoría para reportes de performance.

---

## 4. Política de Cancelación (Cancellation Policy)

### ¿Qué es Cancellation?

Una **cancellation (cancelación)** es la acción de anular un turno antes de que se ejecute.

Los clientes pueden solicitar **cancellation** (cancelación) bajo las siguientes condiciones:
- **Cancelación con Aviso** (Libre): Si cancela con al menos 24 horas de anticipación
- **Cancelación Tardía** (Con Penalización): Si cancela con menos de 24 horas
- **Personal del Salón**: Puede cancelar en cualquier momento

### Impacto de Cancellation en el Sistema
1. **Libera el Horario**: Otros clientes pueden reservar ese slot
2. **Registra Historial**: Se guarda cuándo/quién canceló
3. **Genera Notificaciones**: Se notifica al cliente y al personal
4. **Afecta Métrica de No-Shows**: Diferente a ABSENT (cliente no asistió)

---

---

## 5. Reglas de Negocio e Inteligencia Backend

### 🛡️ Aislamiento Multi-Tenant (RLS)
Shifty utiliza **PostgreSQL Row Level Security (RLS)**. Esto significa que el aislamiento no se hace con `WHERE store_id = ...` en cada consulta manual, sino que la base de datos bloquea automáticamente cualquier intento de acceder a turnos de otro comercio.
1. El `TenantMiddleware` extrae el `store_id` del token JWT.
2. La sesión de DB ejecuta `set_config('app.current_store_id', ...)`.
3. Postgres filtra las filas en tiempo de ejecución.

### ⚡ Idempotencia y Resiliencia
Para evitar que un cliente reserve dos veces el mismo turno si su internet falla al presionar "Confirmar", utilizamos un **Idempotency Guard** con **Redis**:
- Si llega una petición con una `idempotency_key` ya procesada, el sistema devuelve el resultado original sin re-procesar la lógica de negocio.
- Las claves de Redis del panel llevan la tienda adelante desde perf/f4-back (`panel:` y `panel-reschedule:` + `store_id`; `panel-client:` nace con ese formato y nunca existio sin el). Un reintento idempotente del auto-turno o de la reprogramacion del panel que cruza el deploy que cambio el formato no encuentra la respuesta cacheada: lo responde el chequeo del horario bajo el lock, con 409 `APPOINTMENT_CONFLICT` (o `NO_STAFF_AVAILABLE` si el profesional se elige solo), en vez del turno original. Es la ventana de un reintento en curso durante el deploy; no se pierde ni se duplica nada.

### 📅 Validación de Conflictos
Antes de confirmar una reserva, el `AvailabilityService` verifica:
- Que el profesional esté trabajando en ese horario (Working Hours).
- Que no existan otros turnos confirmados que se solapen.
- Que el profesional tenga el servicio asignado a su perfil.

---

## 6. Experiencia de Usuario (Frontend)

### Agenda Diaria (Dashboard)
Una vista de calendario interactiva que permite a los administradores:
- Visualizar la carga de trabajo por profesional.
- Arrastrar y soltar para reprogramar (en desarrollo).
- Cambiar estados rápidamente (Confirmar → Completar).

### Buscador Avanzado
Permite filtrar turnos por:
- Nombre o Email del cliente.
- Rango de fechas.
- Estado del turno.
- Profesional asignado.

### Portal Público de Reserva (`/booking/:slug`)
Una interfaz optimizada para móviles donde los clientes finales:
1. Eligen el servicio.
2. Seleccionan un profesional (o "Cualquiera").
3. Consultan disponibilidad en tiempo real.
4. Completan sus datos (teléfono obligatorio) y reservan.

---

## 7. Referencia de la API (Endpoints Clave)

| Método | Path | Descripción |
| :--- | :--- | :--- |
| `GET` | `/appointments/` | Agenda del día (lista turnos por fecha). |
| `POST` | `/appointments/` | Crear una reserva (requiere `idempotency_key` en el cuerpo). Sin `client_phone`: auto-turno a nombre de quien llama (`staff_id` obligatorio, `starts_at` futuro). Con `client_name` + `client_phone` (+ `client_email` opcional): turno del panel PARA ESE CLIENTE (FF-04): `staff_id` opcional (sin el, el primer profesional libre que hace el servicio; el profesional solo reserva en su agenda, 403 si no), `starts_at` UTC tal cual el slot, desde hace 2 anios (la TIENDA puede cargar un horario que ya paso, p. ej. un walk-in registrado despues: decision de Mateo, 2026-09-25; sin mail al cliente para un turno que ya empezo y sin recordatorios) hasta dentro de 2 anios (lo mismo que el auto-turno, cuyo inicio si tiene que ser futuro), sin antelacion minima, OTP, campos extra, `accepts_terms` ni sena: nace `confirmed`, sin cobro y con `terms_accepted_at` nulo; precio de lista congelado; buffer, bloqueos y choques siempre. Fuera de la jornada del profesional: 409 `OUT_OF_SCHEDULE`, salvo `allow_outside_schedule: true` (solo admin; si no, 403). Reutiliza la ficha del cliente de la tienda por telefono sin pisarla. Errores: 404 `RESOURCE_NOT_FOUND` (servicio), 422 (profesional que no hace el servicio, fuera de [-2, +2] anios, datos incompletos, caracteres de control), 409 `SCHEDULE_BLOCKED` / `APPOINTMENT_CONFLICT` / `NO_STAFF_AVAILABLE` / `IDEMPOTENCY_IN_PROGRESS`, 409 `RESOURCE_CONFLICT` neutro si el email del cliente nuevo ya es de otro cliente de ESTA tienda (el email de cliente es unico por tienda desde PV-01, 2026-09-25: el de un cliente de otra tienda o el de una cuenta del personal entra) o si la `idempotency_key` ya la uso otro turno (la idempotencia de Redis es por tienda), 402 `SUBSCRIPTION_SUSPENDED`. Respuesta: `AppointmentResponse` (201). Migracion FF-04: el modal "Nuevo turno" del panel todavia reserva por `POST /public/appointments`, que es un camino de cliente final: hasta que el front pase a este endpoint, desde ese modal la tienda no puede cargar un turno en el pasado. |
| `GET` | `/appointments/availability` | Consulta slots libres para un servicio/fecha. |
| `PATCH` | `/appointments/{id}/confirm` | Cambia estado a confirmado. |
| `PATCH` | `/appointments/{id}/cancel` | Cancela desde el panel (cualquier usuario autenticado de la tienda). Con cobro vivo (`pending_payment` o un cobro en `pending` o `rejected`: tras un rechazo el link de MP sigue pagable) lo vence en la misma transaccion y manda a vencer el link de Mercado Pago (decision de Mateo D2, 2026-09-25): ya no responde 409 `PAYMENT_APPOINTMENT_REQUIRES_RELEASE`. **Cambio de contrato para el front (revision de perf/f4-pay, 2026-09-25):** cancelar un turno que ya esta cancelado responde 409 `APPOINTMENT_ALREADY_CANCELLED` (antes 200); un doble click recibe 409 y no vuelve a publicar el cupo liberado ni la auditoria. |
| `PATCH` | `/appointments/{id}/reschedule` | Reprograma un turno (cancela el anterior y crea uno nuevo atómicamente). `new_starts_at` entre hace 2 anios y dentro de 2 anios: la tienda puede mover un turno a un horario que ya paso (decision de Mateo, 2026-09-25), sin mail `appointment.rescheduled` en ese caso; el cliente reprograma por el portal, solo al futuro. Con un link de pago del panel vivo (cobro en `pending` o `rejected` sobre un turno confirmado), la reprogramacion vence el cobro del original en la misma transaccion y el turno nuevo nace sin cobro y sigue `confirmed` (decision de Mateo, 2026-09-25; antes 409 `PAYMENT_APPOINTMENT_REQUIRES_RELEASE`). **Cambio de contrato para el front (decision de Mateo 2026-09-25: opcion A):** un turno en `pending_payment` (sena requerida pendiente) responde 409 `DEPOSIT_PENDING_RESCHEDULE_DENIED` con el mensaje "Cobrá la seña o cancelá el turno antes de moverlo" y no cambia nada (ni el turno, ni el cobro, ni su link). La sena nunca se pierde: se cobra y despues se mueve, o se cancela (cancelar vence el cobro, D2). |
| `GET` | `/appointments/search` | Búsqueda con filtros dinámicos y paginación (`page`/`page_size`). `include_total=false` no cuenta el total y devuelve `total: null` (para las paginas 2 en adelante; F3-06). Cada respuesta trae `next_cursor` (null si no hay mas); pasarlo como `after` pide la pagina siguiente por clave `(starts_at, id)` sin `OFFSET` (`after` con `page` > 1 es 422; F3-08). |
| `POST` | `/payments/preferences/{appointment_id}` | Link de pago del panel (admin, superadmin, profesional; modulo `payments`). Lockea el turno antes de tocar el cobro (orden turno -> pago) y rechaza un turno soltado: sobre uno cancelado o vencido responde 409 `APPOINTMENT_NOT_PAYABLE` y no crea cobro. Un turno completado o ausente se sigue pudiendo cobrar por link, como antes. Con `MERCADOPAGO_LINK_REF_ENABLED` apagado, regenerar el link de un cobro vencido responde 409 `PAYMENT_LINK_REGENERATION_UNAVAILABLE` sin tocar el cobro ni llamar a Mercado Pago. Con el flag prendido (default), regenerar el link de un cobro vencido (`expired`) pide a Mercado Pago un link NUEVO (el viejo se manda a vencer) y deja el cobro `pending` otra vez; antes devolvia el link viejo, ya vencido, y el cobro seguia `expired`. Un pago tardio del link viejo ya no se aplica a ese cobro: con `MERCADOPAGO_LINK_REF_ENABLED` (prendido por defecto) cada link lleva su propia `external_reference` (`<turno>:<link_ref>`) y la integridad exige la del link vigente, aunque Mercado Pago no mande `preference_id` (el pago no lo trae). Cada link retirado (regenerar un cobro vencido o re-tarifar) queda en `payment_link_history` con su referencia, preferencia, importe y moneda: un `approved` de un link retirado SE APLICA si el cobro no estaba acreditado y el pago es por el importe y la moneda de ese link (el cobro adopta ese link con su importe, promo y descuento, y el link vigente se manda a vencer). Las preferencias usan `binary_mode` (MP aprueba o rechaza en el momento, sin cupones de efectivo pendientes): lo que cubre el historial es un pago en el link retirado antes de que MP lo venza y el webhook tardio, reentregado o perdido de un pago hecho antes del retiro. La conciliacion tambien busca por las referencias de los links retirados de los ultimos 7 dias, como mucho los 2 mas recientes por cobro; el webhook reconoce un link retirado a cualquier edad. Si el cobro ya estaba acreditado es un pago duplicado, y si el importe no coincide o el link no es conocido, no se aplica. En esos casos no queda en silencio: warning en el log, evento a Sentry y un aviso al dueno ("Pago duplicado ... devolvelo desde Mercado Pago" o "Se recibio un pago sobre un link reemplazado") (una vez por pago de MP) para que lo revise en Mercado Pago y lo devuelva si corresponde. `GET /ops/slo` suma `dead_letter_webhooks_24h` (webhooks que agotaron sus reintentos en las ultimas 24 h; alerta critica `dead_letter_webhooks` con cualquiera). Si el turno se cancela mientras Mercado Pago crea el link, el link no se guarda, se manda a vencer por el outbox y tambien es 409 `APPOINTMENT_NOT_PAYABLE` (revision de perf/f4-pay, 2026-09-25). **Cambio de contrato para el front (revision de e5579b6..3b977a9, 2026-09-25):** sobre un cobro ya acreditado (`approved` o `manual_confirmed`) responde 409 `PAYMENT_ALREADY_ACCREDITED` sin tocar el cobro, cambie o no el precio: no hay nada que cobrar (antes: 200 con el link ya pagado si el precio no habia cambiado). |
| `POST` | `/payments/{appointment_id}/manual-confirm` | Registra un cobro hecho fuera del sistema (efectivo, transferencia). Lockea el turno primero y responde 409 `APPOINTMENT_NOT_PAYABLE` sobre un turno cancelado o vencido. Sobre un cobro ya acreditado (`approved` o `manual_confirmed`) es un no-op: 200 con el cobro tal como se acredito, sin re-tarifar aunque el pedido traiga `amount` y sin publicar eventos (decision de Mateo, revision de e5579b6..3b977a9, 2026-09-25; con `amount` distinto antes respondia 409 `PAYMENT_ALREADY_ACCREDITED`). |
| `GET` | `/ledger/clients` | Buscador de clientes del fiado (decision de Mateo D3, 2026-09-25): admin, superadmin y profesional (la recepcion no tiene fiado), con el modulo `ledger` activo. Devuelve SOLO clientes activos de la tienda (el rol lo fija el servidor; nunca cuentas del personal, admins ni soporte global): `[{public_id, name, email, phone}]`, mas nuevos primero. El admin y el superadmin reciben email y telefono completos; el profesional recibe el telefono enmascarado (`***` y los ultimos 3 digitos), `email` null y, si el cliente no tiene nombre, `name` cae al telefono enmascarado (L3-03, 2026-09-25; lo mismo vale para `client_name` de `/ledger/summary`). El profesional busca solo por nombre: `q` con digitos no busca por telefono para ese rol, porque ampliando `q` de a un digito reconstruia el numero enmascarado (decision de Mateo, revision de fix/legal-datos, 2026-09-25); el admin sigue buscando por telefono. `q` (2..80 caracteres, sin caracteres de control) busca igual que `GET /users/?q=` (nombre que contiene `q` o digitos del telefono); `limit` 1..100, default 50. Errores: 403 `PERMISSION_DENIED` / `FEATURE_DISABLED`, 422. |
| `GET` | `/ledger/customers/{client_id}` | Historial de fiado paginado (`limit`/`offset`). Trae `next_cursor`; pasarlo como `after` pide la pagina siguiente por clave `(created_at, id)` sin `OFFSET` (`after` con `offset` > 0 es 422; F3-08). |
| `GET` | `/reports/summary` | Resumen del rango con detalle paginado (`limit`/`offset`). `order=desc` devuelve el detalle del mas reciente al mas viejo; con `limit=6`, los 6 mas recientes (F3-06). |
| `GET` | `/appointment-blocks/` | Bloqueos de la tienda: los leen los roles que gestionan bloqueos (admin y profesional) y, solo lectura, la recepcion (FF-14); todos ven los de toda la tienda. Sin parametros: todos, activos e inactivos, de toda la historia (como siempre). F4-07 (aditivo): `from_date` + `to_date` (dias LOCALES, los dos o ninguno; `to_date >= from_date`; hasta 400 dias incluidos; una fecha sin dia siguiente, como 9999-12-31, tambien es 422) devuelven los que solapan `[medianoche local de from_date, medianoche local del dia siguiente a to_date)`; `include_inactive=false` saca los desactivados (ausente = incluirlos, el default de siempre). Orden por inicio. |
| `GET` | `/users/` | Usuarios de la tienda (solo admin; `q` no cambia los roles: el profesional busca clientes para el fiado por `GET /ledger/clients`). Filtros de siempre (`include_inactive`, `email`, `role`, `limit` 1..500 default 200, `offset` 0..1.000.000). `q` (FF-20/F4-03, aditivo; 2..80 caracteres, sin caracteres de control; si no, 422): nombre, apellido o "nombre apellido" que CONTIENE `q` sin distinguir mayusculas, o, si `q` es un telefono (digitos y `+ - ( )` o espacios, 2 o mas digitos), telefono que contiene esos digitos. Los comodines de LIKE (`%`, `_`) y la barra invertida en `q` son literales. Para Fiado: `?role=client&q=...`. La consulta queda acotada por `ix_users_store_id` (el `ILIKE` es filtro sobre las filas de la tienda; `tests/postgres/test_pg_busqueda_de_clientes.py`). |
| `GET` | `/superadmin/stores` | Listado de tiendas del soporte global (solo `is_global_admin`). `is_active`: `true` (default, igual que antes), `false` o `all` (sin filtro de estado; FF-24); `search`, `has_subscription`, `limit` (1..200, default 50), `offset` (0..1.000.000). La respuesta sigue siendo la lista; el total con los mismos filtros y sin paginar viaja en el header `X-Total-Count` (expuesto por CORS). |
| `GET` | `/public/client/{store_public_id}/{phone}/appointments` | Historial del cliente (requiere OTP reciente). Cada turno trae `can_cancel` y `can_reschedule`, calculados con las MISMAS reglas que las acciones (`client_cancel_denial` / `client_reschedule_denial` y el grafo de estados): `false` si el turno es terminal (`cancelled`, `completed`, `absent`, `expired`), si tiene un pago en curso (`pending_payment`, o un cobro vivo: un `Payment` en `pending` o `rejected` (tras un rechazo MP deja reintentar sobre el mismo link), como el link que genera el panel sobre un turno confirmado; decision de Mateo D1, 2026-09-25) o si ya esta dentro de la ventana de cancelacion de la tienda; `can_reschedule` es ademas `false` con un pago acreditado (aprobado o confirmado a mano; un pago devuelto no cuenta). Las acciones responden 409 `PAYMENT_APPOINTMENT_REQUIRES_RELEASE`, `CANCELLATION_WINDOW_EXPIRED` o `PAID_APPOINTMENT_RESCHEDULE_DENIED` con mensajes para el cliente. |
| `GET` | `/public/legal/versions` | Versiones vigentes de los terminos y de la politica de privacidad: `{terms_version, privacy_version}` (settings; anonimo, `public-read`). El portal las manda al aceptar; ver "Contratos pendientes del front (auditoria legal...)". |
| `GET` | `/public/unsubscribe?token=` | Baja del mail promocional "volve a reservar" (art. 27 Ley 25.326): el link va en ese mail, firmado (HMAC con clave derivada de `SECRET_KEY`) y valido 90 dias, por cliente y tienda. 200 `{status: "unsubscribed"}` neutro e idempotente; link adulterado o vencido: 400 `UNSUBSCRIBE_LINK_INVALID`. Rate limit `public-read`. Los mails transaccionales no cambian. |
| `GET` | `/users/{client_id}/export` | Derecho de acceso (PV-05, 2026-09-25): datos del cliente y sus turnos, cobros, fiado y lista de espera (con las versiones aceptadas) de ESTA tienda en JSON, mas `marketing_opted_out_at` (baja del mail promocional). Solo admins; solo cuentas con rol cliente de la tienda (otra tienda, personal o admins: 404 `RESOURCE_NOT_FOUND`). Deja una fila de auditoria (`export`) sin datos personales. Procedimiento: `docs/DERECHOS_DE_LOS_TITULARES.md`. |
| `POST` | `/users/{client_id}/anonymize` | Supresion (PV-05): reemplaza nombre, telefono, email, notas, `notes_staff` y respuestas de la reserva por valores neutros (email `anonimo-<id>@anonimizado.noreply`, no entregable), cierra sus entradas abiertas de la lista de espera, borra las notas de su fiado y deja al cliente inactivo; conserva importes, fechas y estados. Neutraliza tambien el cuerpo de los avisos del panel ligados a sus turnos. 409 `CLIENT_HAS_LIVE_CHARGE` con un cobro vivo, 409 `CLIENT_HAS_ACTIVE_APPOINTMENTS` con un turno activo que no empezo, 409 `CLIENT_HAS_DEBT` con saldo distinto de cero en el fiado. Mismos permisos y 404 que la exportacion; permitido con la tienda suspendida. Auditoria `anonymize` sin datos personales. Irreversible. |
| `POST` / `GET` | `/stores/me/terms-acceptance` | Aceptacion de los terminos B2B (`STORE_TERMS_VERSION`): `POST` solo admin de la tienda (201; guarda tienda, usuario, version, fecha y HMAC de la IP), permitido con la tienda suspendida; `GET` admins: `{current_version, current_version_accepted, latest}`. No bloquea el panel. |
| `GET` | `/public/stores/{slug}/ref` | Referencia minima para "Mis turnos" (FF-16): `{store_public_id, name, accepts_new_bookings}`. Responde tambien con la suscripcion suspendida (`accepts_new_bookings: false`), para que el cliente llegue a cancelar o reprogramar; `GET /public/stores/{slug}` sigue dando 404 en ese caso. 404 `STORE_NOT_FOUND` (el mismo de la vitrina) si la tienda no existe o esta dada de baja. Slug sin distinguir mayusculas. `Cache-Control: no-store`; rate limit `public-read`. |
| (varias) | Horizontes y fechas extremas | Cotas de las fechas que manda un request (revision de perf/f4-back); fuera de ellas, 422. **Regla del dueno (2026-09-25):** la TIENDA puede reservar un horario que ya paso; el CLIENTE FINAL nunca, aunque la tienda no pida antelacion (`POST /public/appointments`, la reprogramacion de "Mis turnos" y anotarse en la lista de espera con la ventana vencida dan 422). Reservar y reprogramar (portal, panel, alta para un cliente): hasta 2 anios hacia adelante (`MAX_BOOKING_AHEAD`); al cliente lo limita a 120 dias solo la grilla de `/public/availability`, no la reserva. Caminos de la tienda con inicio en el pasado (alta para un cliente, reservar desde la lista de espera y reprogramar desde el panel, p. ej. para corregir un walk-in): desde hace 2 anios, sin mail al cliente ni recordatorios para un inicio que ya paso. Lista de espera: el inicio de la ventana dentro de `BOOKING_HORIZON_DAYS` (120 dias locales). Disponibilidad sin token de `/appointments/availability`: el horizonte de `/public/availability` (de ayer a +120 dias; comparten claves de cache); con token no tiene horizonte. Bloqueos: cada extremo cuyo VALOR cambia, entre hace 2 anios y dentro de 2 anios mas 366 dias; `recurrence_until` no tiene cota pero no puede desbordar (solo corta la expansion, que ya tiene tope de 120 ocurrencias). Periodo de una suscripcion del superadmin: +-5 anios. Filtros de dia (agenda, busqueda, reportes, bloqueos): sin 9999-12-31, y un reporte sin `from_date` con `to_date` en el primer mes representable da 422. Grilla de `/appointments/availability`: sin 0001-01-01 ni 9999-12-31. Filas imposibles ya guardadas (un bloqueo en 9999): editarlas o borrarlas invalida el cache de la tienda entera en vez de dar 500. |


### Contratos pendientes del front (perf/f4-pay, 2026-09-25)

Cambios del backend que el front todavia tiene que tomar. Cada uno esta en su
fila de la tabla de arriba.

- **Fiado (pantalla "Cuentas pendientes"):** elegir el cliente con `GET /ledger/clients?q=` en vez de `GET /users/`. `/users/` es solo de admins y el profesional recibe 403: hoy la pantalla no le sirve. La respuesta es `[{public_id, name, email, phone}]`, solo clientes.
- **Cancelar desde el panel un turno `pending_payment` (o con un link de pago vivo):** ya no responde 409 `PAYMENT_APPOINTMENT_REQUIRES_RELEASE`. Responde 200 y vence el cobro. El boton "Cancelar" ya no tiene que derivar a "Liberar" ni esconderse para el profesional. Reprogramar desde el panel un turno CONFIRMADO con link tampoco da ese 409: vence el link y el turno nuevo nace sin cobro.
- **Reprogramar un turno con sena pendiente (decision de Mateo 2026-09-25: opcion A):** `PATCH /appointments/{id}/reschedule` sobre un turno `pending_payment` responde 409 `DEPOSIT_PENDING_RESCHEDULE_DENIED` ("Cobrá la seña o cancelá el turno antes de moverlo"). El panel muestra ese mensaje tal cual y ofrece las dos salidas: cobrar la sena (link o cobro manual) y recien despues mover, o cancelar. No es un error del sistema: no reintentar.
- **Segunda cancelacion:** cancelar un turno ya cancelado responde 409 `APPOINTMENT_ALREADY_CANCELLED` (antes 200). Un doble click, o dos pestañas, ven 409: mostrarlo como "ya estaba cancelado" y refrescar, no como un error.
- **Portal ("Mis turnos") y turnos terminales (revision de perf/f4-pay, 2026-09-25):** cancelar un turno que ya esta cancelado responde 409 `APPOINTMENT_ALREADY_CANCELLED` (antes 200 y un segundo aviso al dueno), el mismo codigo que el panel. Reprogramar un turno terminal (`cancelled`, `expired`, `completed`, `absent`), desde el portal o desde el panel, responde 409 `APPOINTMENT_NOT_ACTIVE` (antes el portal devolvia a la vida un turno cancelado por el personal, y el panel respondia 422 `INVALID_STATUS_TRANSITION` para los demas terminales). Mostrarlo como "este turno ya no esta activo" y refrescar la lista.
- **Link de pago del panel y cobro manual:** sobre un turno soltado (cancelado o vencido), o si el turno se cancela mientras se genera el link, `POST /payments/preferences/{id}` responde 409 `APPOINTMENT_NOT_PAYABLE`. Lo mismo `POST /payments/{appointment_id}/manual-confirm` sobre un turno cancelado o vencido (revision de perf/f4-pay, 2026-09-25). Un turno completado o ausente se sigue pudiendo cobrar (link o efectivo registrado a mano despues de atender), como antes.
- **Cobros sobre un turno ya pagado (revision de e5579b6..3b977a9, 2026-09-25):** `POST /payments/preferences/{id}` sobre un cobro acreditado (`approved` o `manual_confirmed`) responde 409 `PAYMENT_ALREADY_ACCREDITED`: la pantalla de Cobros tiene que mostrarlo como "ya pagado" y no ofrecer el link. `POST /payments/{appointment_id}/manual-confirm` sobre un cobro acreditado responde 200 con el cobro como estaba (el importe no cambia aunque se mande otro): no es un error.
- **Email de cliente por tienda (PV-01, decision de Mateo 2026-09-25):** `POST /public/appointments`, `POST /appointments/` con cliente, `POST /public/waitlist` y `POST /users/` con `role: client` aceptan el email de un cliente de OTRA tienda (antes 409 `RESOURCE_CONFLICT`): cada tienda tiene su ficha. El 409 neutro queda solo para el email de otro cliente de la MISMA tienda (un telefono nuevo con ese email). El front no tiene que cambiar nada: si traducia ese 409 a "ese email ya existe", el mensaje sigue valiendo, pero ahora solo aparece dentro de la tienda. El email del personal y de los admins sigue unico global: el alta de staff o de un admin con el email de otra cuenta del personal sigue en 409 (o 422/400 con el mensaje amable si la cuenta es de la misma tienda). Un profesional o admin PUEDE tener el mismo email que un cliente. Cambios de rol (revision de PV-01, 2026-09-25): pasar un cliente a un rol del personal con el email de otra cuenta del personal responde 409 `RESOURCE_CONFLICT` por `PATCH /users/{id}`, `PATCH /superadmin/users/{id}` (antes 400 "No se pudo actualizar el usuario") y `PATCH /superadmin/users/{id}/global-admin`; pasar a `role: client` una cuenta con `is_global_admin` responde 409 `GLOBAL_ADMIN_ROLE_LOCKED` ("Esta cuenta no puede pasar a cliente") por `/users/` y por `/superadmin/users/{id}`: primero se le quita el soporte global.
- **Fiado sobre el personal:** leer o cargar fiado sobre una cuenta del personal o de un admin responde 404 `RESOURCE_NOT_FOUND`. Revertir un movimiento viejo que quedo cargado a una cuenta del personal (`POST /ledger/customers/{id}/movements/{movement_id}/reverse`) si se puede: sirve para limpiar lo cargado antes del cierre.

### Contratos pendientes del front (auditoria legal y de privacidad, 2026-09-25)

Todo es aditivo: el front actual sigue funcionando sin tocar nada.

- **Versiones de los textos legales:** `GET /public/legal/versions` (anonimo, rate limit `public-read`) devuelve `{terms_version, privacy_version}` (settings `LEGAL_TERMS_VERSION` y `LEGAL_PRIVACY_VERSION`, hoy `"2026-09-25"`). Los textos de `/legal` tienen que mostrar esas versiones, y quien cambie un texto sube su version en settings.
- **Reserva publica (`POST /public/appointments`):** mandar `terms_version` y `privacy_version` tal como los dio el endpoint anterior junto a `accepts_terms: true`. Quedan en el turno (`appointments.terms_version`/`privacy_version`) al lado de `terms_accepted_at`. Opcionales: sin ellos la reserva sigue y no se guarda version. Si vienen y no son las vigentes: 409 `LEGAL_VERSION_MISMATCH` con las vigentes en `detail`; el front vuelve a mostrar la casilla con los textos nuevos. Si viene una sola de las dos: 422 `VALIDATION_ERROR` (pedido mal armado). El control corre despues del replay de idempotencia: el reintento de una reserva ya hecha devuelve la original aunque los textos hayan cambiado. Formato: 1..20 caracteres `[A-Za-z0-9._-]` (si no, 422). El alta del panel para un cliente no registra consentimiento ni versiones: el personal no es el cliente aceptando.
- **Lista de espera (`POST /public/waitlist`):** campos nuevos `accepts_terms`, `terms_version` y `privacy_version`; se guardan en la entrada (`terms_accepted_at` y las dos versiones). Hoy son opcionales; `accepts_terms: false` es 422 siempre, y versiones viejas son 409 `LEGAL_VERSION_MISMATCH`. **Cuando el front tenga la casilla** se prende `LEGAL_WAITLIST_CONSENT_REQUIRED=true` y pasan a ser obligatorios (sin casilla o sin versiones: 422). Prender el flag antes de que el front mande los campos rompe el alta de la lista de espera.
- **Baja del mail "volve a reservar":** el mail trae un link a `GET {PUBLIC_API_URL}/public/unsubscribe?token=...` que responde JSON (`{status: "unsubscribed"}` o 400 `UNSUBSCRIBE_LINK_INVALID`). Si el front quiere una pantalla propia ("Te diste de baja"), puede servir `/baja?token=` y llamar a ese endpoint; en ese caso el link del mail pasa a apuntar al front (cambio en `modules/legal/unsubscribe.py::unsubscribe_url`).
- **Derechos del titular:** el panel puede ofrecer en la ficha de un cliente "Exportar datos" (`GET /users/{id}/export`, descarga el JSON) y "Anonimizar" (`POST /users/{id}/anonymize`, con confirmacion fuerte: no se deshace). Mostrar los 409 `CLIENT_HAS_LIVE_CHARGE` / `CLIENT_HAS_ACTIVE_APPOINTMENTS` / `CLIENT_HAS_DEBT` con su mensaje.
- **Terminos B2B de la tienda:** `POST /stores/me/terms-acceptance` (solo el admin de la tienda; el soporte global y el resto del personal reciben 403; permitido con la tienda suspendida) registra la aceptacion de `STORE_TERMS_VERSION` y responde 201 `{terms_version, accepted_at, accepted_by}`. `GET /stores/me/terms-acceptance` (admins) devuelve `{current_version, current_version_accepted, latest}`. El backend NO bloquea el panel: si `current_version_accepted` es `false`, que hacer (aviso, modal bloqueante) lo decide el front.

---

## 8. Política de Cancelación (Cancellation Policy)

### ¿Qué es Cancellation?

Una **cancellation (cancelación)** es la acción de anular un turno antes de que se ejecute.

Los clientes pueden solicitar **cancellation** (cancelación) bajo las siguientes condiciones:

1. **Período Mínimo de Aviso**: El cliente debe dar aviso con **al menos 24 horas** de anticipación (configurable por salón)
   - Campo: `store_config.min_cancellation_notice_hours`
   - Valor por defecto: 24 horas

2. **Estado del Turno**: El turno debe estar en estado `PENDING` o `CONFIRMED`
   - No se pueden cancelar turnos ya `COMPLETED`
   - No se pueden re-cancelar turnos ya `CANCELLED`

3. **Turno Futuro**: El turno no debe haber comenzado aún
   - Validación: `appointment.starts_at > now()`

### Proceso de Cancelación
```
1. Cliente solicita cancellation del turno
   ↓
2. Sistema valida requisitos:
   - ¿Turno futuro?
   - ¿Al menos 24h de aviso?
   - ¿Estado PENDING o CONFIRMED?
   ↓
3. Si cumple todos → Estado cambia a CANCELLED
4. Si falla validación → Error específico, turno NO cambia
   ↓
5. Notificación al personal del salón
6. Horario queda disponible para otros clientes
```

### Cancelación Tardía
Si cliente intenta cancelar **dentro del período crítico** (< 24 horas):
- Se permite la cancelación
- Se registra como "cancelación última hora"
- Puede aplicarse penalización según política del salón
- Personal es notificado inmediatamente

### Cancelación Administrativa
El personal del salón **SIEMPRE puede cancelar** sin límites de tiempo:
- Con motivo documentado (enfermedad personal, cambio de servicio, etc.)
- Se registra quién canceló y cuándo
- Cliente recibe notificación
- Se ofrece opción de re-booking

### Diferencias Clave: Cancellation vs ABSENT vs COMPLETED

| Aspecto | Cancellation | ABSENT | COMPLETED |
| :--- | :--- | :--- | :--- |
| **Cliente se presentó** | N/A (antes de hora) | NO | SÍ |
| **Servicio se ejecutó** | NO | NO | SÍ |
| **Cuándo ocurre** | Antes de hora de inicio | Después de hora sin presentarse | Después de ejecutar |
| **Quién lo marca** | Cliente o Personal | Personal/Sistema | Personal |
| **Genera ingresos** | NO | NO | SÍ |
| **Penalización cliente** | NO | Posible | NO |

---

## 9. Manejo del Estado ABSENT (No-Show)

### ¿Qué es ABSENT?

**ABSENT** (Ausente) es un estado **terminal** que se asigna cuando un cliente **NO ASISTIÓ** a un turno confirmado.

### Cómo Llega a ABSENT

```
CONFIRMED → ABSENT
```

Un turno en estado `CONFIRMED` transiciona a `ABSENT` cuando:
1. Llega la hora de inicio del turno
2. El cliente **no se presenta** 
3. Personal marca como "cliente no presentado" O sistema marca automáticamente tras cierto tiempo

### Proceso de Marcado como ABSENT

**Opción 1: Manual por Personal**
- Personal llega al horario del turno
- Cliente no asiste y no se comunica
- Personal marca: "Cliente no presentado"
- Estado cambia a ABSENT automáticamente

**Opción 2: Automático por Sistema**
- Se configura: `auto_absent_minutes` (ej: 15 minutos)
- Si cliente no asiste después de esa espera, sistema marca automáticamente
- Personal recibe notificación

**Opción 3: Cierre de Día**
- Al finalizar el día, turnos confirmados no completados pueden marcarse ABSENT
- Según política del salón

### Impacto de ABSENT

**Para el Cliente:**
- Se registra como "no-show" en historial
- Visible en perfil del cliente
- Posibles penalizaciones:
  - Bloqueo temporal de bookings
  - Depósito requerido para próximas reservas
  - Aviso al personal del salón

**Para el Personal:**
- Tiempo se marcó como ocupado pero sin servicio efectivo
- Afecta métricas de ocupación
- Se registra como "tiempo perdido"

**Para el Salón:**
- Horario ocupado sin generar ingresos
- Afecta reportes de utilización (ocupancy rate)
- Impacta estadísticas de performance

### Diferencia: ABSENT vs CANCELLED

| Aspecto | ABSENT | CANCELLED |
| :--- | :--- | :--- |
| **Definición** | Cliente NO asiste (no-show) | Cliente o Salón anula activamente |
| **Cándo ocurre** | Después de hora de inicio | Antes de hora de inicio |
| **Acción** | Pasiva (inasistencia) | Activa (cancelación) |
| **Tipo de Estado** | Terminal | Terminal |
| **Penalización** | Posible al cliente | NO |
| **Auditoría** | Registra "no-show" | Registra "cancelación" |

### Configuración por Salón

Cada salón puede configurar:
- `auto_absent_minutes`: Minutos de espera antes de marcar automáticamente (default: 15)
- `absent_penalty_type`: Tipo de penalización (NONE, WARNING, TEMPORARY_BLOCK, DEPOSIT_REQUIRED)
- `absent_penalty_duration`: Cuántos días dura la penalización
- `notify_on_absent`: Enviar notificación inmediatamente al marcar

---

## 10. Máquina de Estados: Transiciones Permitidas

### Diagrama de Estados

```
PENDING → CONFIRMED (confirmación)
PENDING → CANCELLED (cancelación previa)
CONFIRMED → COMPLETED (servicio realizado)
CONFIRMED → CANCELLED (cancelación tardía)  
CONFIRMED → ABSENT (cliente no asistió)
COMPLETED (estado terminal - fin)
CANCELLED (estado terminal - fin)
ABSENT (estado terminal - fin)
```

### Tabla Completa de Transiciones

| Estado Actual | Estados Permitidos | Significado |
| :--- | :--- | :--- |
| PENDING | CONFIRMED, CANCELLED | Turno puede confirmarse o cancelarse |
| CONFIRMED | COMPLETED, CANCELLED, ABSENT | Turno puede completarse, cancelarse o marcarse como no-asistencia |
| COMPLETED | (ninguno) | Terminal - no hay más cambios |
| CANCELLED | (ninguno) | Terminal - no hay más cambios |
| ABSENT | (ninguno) | Terminal - no hay más cambios |

---

## 11. Reglas de Transición: PENDING → COMPLETED

### ¿Puede pasar un turno directamente de PENDING a COMPLETED?

**RESPUESTA: NO. Es prohibido.**

### Flujo Obligatorio

```
PENDING
  ↓
CONFIRMED (paso obligatorio)
  ↓
COMPLETED (solo después de CONFIRMED)
```

### Por Qué Esta Restricción

1. **Auditoría**: Asegura que hubo confirmación previa
2. **Validación**: Se verifica disponibilidad del personal
3. **Seguridad**: Previene cambios de estado inesperados
4. **Integridad**: Cumple con máquina de estados estricta

### Proceso Correcto

1. Cliente reserva → Estado: `PENDING`
2. Personal confirma → Estado: `CONFIRMED`
3. Se realiza el servicio → Estado: `COMPLETED`

### Validación en Sistema

```python
if appointment.status == AppointmentStatus.PENDING and new_status == AppointmentStatus.COMPLETED:
    raise ValidationError("Turno debe estar CONFIRMED antes de COMPLETED")
```

---

> [!TIP]
> Para depurar problemas de disponibilidad, revisá siempre los logs de Redis (Memurai) para ver si hay bloqueos de idempotencia activos o errores de caché en los slots calculados.
