# Plan de producto — septiembre 2026

Plan derivado de la autocrítica de negocio (ensayo sobre SaaS de turnos y el
mercado de Córdoba) y de un relevamiento del código, área por área, hecho el
2026-09-10. Está escrito para dos lectores: el dueño (para decidir y seguir el
avance) y el asistente de IA que lo ejecute (módulos, campos y pruebas
exactas). No contiene código.

Cada fase cierra con su matriz de pruebas por capa (unitaria, integración en
SQLite, Postgres real, front) como exige `CLAUDE.md`. Las estimaciones son
días de trabajo del asistente con el loop de verificación incluido (tests,
CI, Postgres). Donde algo es inferido y no verificado se dice.

---

## 1. Qué queda afuera y por qué

- **WhatsApp Business API (Meta o Twilio nuevo): pendiente firme, para más
  adelante.** No se paga ahora. Lo único permitido: email por el SMTP que ya
  existe, y links `wa.me` con texto prearmado que el dueño manda a mano desde
  el panel (costo cero). Cuando se retome, el diseño ya está pensado para que
  el cliente escriba primero (24 horas gratis) y el costo se traslade al plan.
- **Política de cancelación, señas "no reembolsables", saldo a favor,
  reembolsos y cualquier lógica legal: fuera de Shifty.** La deuda y la
  política son de la tienda; los pagos y sus disputas, de Mercado Pago. El
  texto libre `deposit_policy` queda como está.
- **Machine learning para no-show y overbooking algorítmico: no.** Reglas
  fijas y explicables donde haga falta.
- **Entidad "Recurso" aparte y reservas multi-recurso (persona + sala):**
  después. La versión mínima de recursos (Fase 2) cubre canchas y salas.
- **Sincronización con Google Calendar y reservas recurrentes del cliente:**
  después.

---

## 2. Orden recomendado

| Fase | Qué | Por qué en este lugar | Días |
|---|---|---|---|
| 0 | Arreglos que afectan a todo cliente hoy | Nada de lo que sigue tiene sentido si el cliente ve la hora mal, no recibe mails y el dueño no puede marcar un turno como completado | 5,5 |
| 1 | Bloqueos por vacaciones sobre turnos ya tomados | Hoy dejan turnos huérfanos; es el primer dolor operativo del dueño | 3 |
| 2 | Recursos que no son personas (canchas, salas) | Condición para vender a pádel y a cualquier rubro con espacios | 2,5 |
| 3 | Post-turno y recordatorio en dos pasos | Barato, ataca retención y ausentismo con el canal que hay | 2 |
| 4 | Lista de espera con relleno | La funcionalidad de más valor; depende de 0 y de 3 | 4 |
| 5 | Seña por antelación e historial | Cobro mejor sin tocar cancelaciones ni reembolsos | 2,5 |
| 6 | Suscripción: aviso y gracia | Importa cuando haya tiendas pagando; hoy se puede operar a mano | 2 |
| 7 | El cliente desde el teléfono | Depende de la decisión del OTP (Fase 0.3) | 2,5 |
| | **Total** | | **24** |

En calendario, con verificación entre fases, unas cinco semanas. **Rebanada
para salir a vender antes:** Fases 0, 2, 1 y 3, unos 13 días, tres semanas.
Con eso una estética, un consultorio o una cancha ya tienen algo que no
tienen con la competencia local.

La estimación anterior (13 a 17 días) era sin relevamiento. La diferencia es
casi toda la Fase 0: defectos que ya existían y que hay que arreglar antes.

---

## 3. Fase 0 — Arreglos que afectan a todo cliente hoy (5,5 días) — HECHA el 2026-09-10

**Estado:** completa en los commits `78f9303` (0.1, 0.2, 0.4, 0.5, 0.6, 0.7) y
`05ea7f3` (0.3, OTP por email por decisión del dueño). Hallazgos extra durante la
ejecución: la validación del horario del profesional en la reserva pública
comparaba en UTC (rechazaba las últimas tres horas de cada jornada); la reserva
pública tampoco invalidaba el caché; el mail de confirmación también sale cuando
se acredita la seña. Verificado: backend 341 tests, Postgres real 10, front 140.

### 0.1 La hora del turno se muestra en UTC en la reserva pública (1 día)

**Qué se vio.** El backend devuelve `start_time` de cada slot en UTC
(`availability.py`, líneas 219 a 222) y el front lo muestra tal cual: un turno
de 09:00 en Argentina se ofrece como "12:00 hs". Peor: al reservar, el front
recompone fecha local más hora UTC (`BookingWizardContainer.tsx`, línea 447),
así que un turno de 21:00 o más tarde apunta al día equivocado. **Esto es
inferido del código, no reproducido.** Es lo primero que se hace: un test que
lo reproduzca, y recién después el arreglo.

**Diseño.** El front formatea `slot.starts_at` (ISO en UTC) con la zona
`America/Argentina/Buenos_Aires` para mostrar, y manda ese mismo `starts_at`
al reservar en vez de recomponerlo. Los mails de confirmación y recordatorio
formatean con `ARGENTINA_TZ` (`core/utils.py`) en vez de imprimir el ISO.

**Pruebas.** Front: test de `BookingStepDateTime` con un slot de 00:00 UTC
que debe mostrarse como 21:00 y reservar el día correcto. Backend: test del
template de mail con hora ART. Integración SQLite: reserva pública de un slot
nocturno queda en el día elegido.

### 0.2 El caché de disponibilidad nunca se invalida (1 día)

**Qué se vio, confirmado.** La clave que escribe `AvailabilityService` tiene
seis segmentos (incluye dos flags) y todas las invalidaciones usan cuatro;
además `cancel` y `release_pending` borran con un asterisco literal que Redis
no interpreta. Resultado: cuando el dueño bloquea, cancela o libera, la
página pública sigue mostrando el estado viejo hasta cinco minutos. Ningún
test lo cubre. Es prerrequisito de la lista de espera.

**Diseño.** Un único helper de invalidación por (tienda, fecha) que borre las
cuatro variantes de la clave, llamado desde los seis caminos que cambian
disponibilidad (cancelar, liberar, reprogramar, cancelar y reprogramar del
cliente, job de expiración) y desde crear, editar y borrar bloqueos, que hoy
no invalidan nada.

**Pruebas.** Unitaria con Redis simulado: después de cada camino la clave
escrita ya no existe. Regla nueva para `CLAUDE.md`: todo camino que cambia
disponibilidad llama al helper; un test enumera los caminos.

### 0.3 El OTP no se envía por ningún canal en producción (1 día)

**Qué se vio, confirmado.** `OtpService.request_code` nunca lee
`OTP_PROVIDER` ni llama a ningún proveedor: guarda el código y devuelve
`console-dispatch`. En desarrollo el código se ve en pantalla; en producción
la configuración prohíbe ese modo y el cliente jamás recibe el código. Si el
dueño activa "OTP en reserva pública" en producción, esa tienda deja de
recibir reservas. Y los endpoints para que el cliente vea, cancele o
reprograme (que existen en el backend) son inalcanzables.

**Decisión del dueño.** Dos opciones:
- (a) **OTP por email**, con el SMTP que ya existe, fuera de cualquier
  transacción. Implica pedir email al cliente cuando la tienda activa el OTP.
  Recomendada: es la única que habilita la autogestión del cliente (Fase 7)
  sin pagar canal.
- (b) Impedir activar el flag en producción y esconder la autogestión hasta
  tener canal. Más barata, pero deja la Fase 7 sin base.

**Diseño (opción a).** Canal `email` en el pedido de OTP, despacho por
`_send_email` con respuesta neutra ante fallo (no revelar si el teléfono
existe), y el front respeta la ventana de 30 minutos que el backend ya
acepta (hoy vuelve a pedir OTP en cada corrida y agota el presupuesto de 5
por hora).

**Pruebas.** Unitaria del despacho por email y de la respuesta neutra.
Integración: flujo completo con OTP por email. Guarda de configuración:
`otp_booking` no se puede activar si no hay canal configurado.

### 0.4 El cliente no recibe ningún mail al reservar ni al ser confirmado (1 día)

**Qué se vio.** El mail de confirmación del flujo público está detrás de una
condición que nunca se cumple (el turno nace pendiente, no confirmado), y
`confirm()` no manda nada. Hoy el cliente solo recibe el recordatorio de 24
horas. Los textos dicen "desde la app", que no existe para el cliente.

**Diseño.** Mail "reserva registrada" al crear (con el link público de la
tienda y los datos del turno) y mail "turno confirmado" desde `confirm()`,
encolado después del commit como ya hace `book`. Hora en ART. Textos con el
teléfono de la tienda o el link público, nunca "la app".

**Pruebas.** Integración: reserva pública dispara el mail registrado;
confirmar dispara el confirmado; un SMTP caído no impide reservar ni
confirmar.

### 0.5 El dueño no puede confirmar, completar ni marcar ausente desde la agenda (1 día)

**Qué se vio.** Los endpoints existen y la capa de aplicación del front los
implementa, pero ningún componente los usa: el calendario solo ofrece
"Liberar". Sin "Completar" el flujo post-turno no existe; sin "Ausente" el
reporte de ausentismo no tiene datos.

**Diseño.** Tres botones en la tarjeta del turno del calendario, calcados
del botón "Liberar" (`useReleaseAppointment`): Confirmar (pendiente),
Completar y Ausente (confirmado y ya pasado). Visibles según estado y rol
como ya hace el backend.

**Pruebas.** Front: tests del contenedor con las transiciones. Contrato de
rutas: las llamadas ya existen en `application/services`.

### 0.6 Dos reglas que el camino público ignora (0,5 día)

- La reserva pública **no aplica `buffer_minutes`** entre turnos, mientras
  que el alta desde el panel y la disponibilidad sí. Alinear la consulta de
  conflicto del camino público con la del panel.
- La reserva pública **no congela `price_amount`**; el alta desde el panel
  sí. Un cobro manual posterior usa el precio de lista de hoy. Congelarlo en
  el camino público.

**Pruebas.** Integración: reserva pública pegada a otro turno con buffer da
409; el precio congelado sobrevive a un cambio de precio del servicio.
Postgres: la ráfaga concurrente sigue en 1 éxito, resto 409.

### 0.7 El manual del dueño promete WhatsApp automático (0,1 día)

`Manual.tsx` dice que el recordatorio llega por WhatsApp a todos. Sin
proveedor configurado es solo mail y solo para quien dejó mail. Corregir el
texto.

---

## 4. Fase 1 — Bloqueos por vacaciones sobre turnos ya tomados (3 días) — HECHA el 2026-09-10

**Estado:** completa en `7ed6f17`. Cancelado en bloque solo para
administradores; turnos con pago pendiente o seña acreditada se listan y no se
cancelan solos. Hallazgo extra: la reserva pública leía bloqueos antes del lock
del profesional (el test de carrera en Postgres lo atrapó). Verificado: backend
347, Postgres 11, front 143.

**Objetivo.** Que el dueño pueda bloquear días (vacaciones, feriado, avería
de una cancha) viendo antes qué turnos quedan adentro, cancelándolos en
bloque con aviso al cliente, sin dejar turnos huérfanos.

**Qué se vio.** Al crear un bloqueo (simple, recurrente o de toda la tienda)
el backend no mira los turnos existentes: siguen activos, aparecen en la
agenda, el recordatorio les sigue saliendo y el cliente llega a un
profesional bloqueado. El módulo no tiene service ni repository, commitea en
el router, no toma lock del profesional (un cliente puede colarse dentro de
un bloqueo recién creado: `book` lee bloqueos antes del `FOR UPDATE`), y
cualquier usuario con rol personal puede bloquear a cualquier profesional de
la tienda.

**Diseño.**
- `AppointmentBlockService` sobre el Unit of Work, dueño de la transacción
  (los commits salen del router; es la regla del módulo de referencia).
- `POST /appointment-blocks/preview` con el mismo cuerpo que el alta: devuelve
  los turnos afectados (cliente, horario, estado, si tiene seña acreditada o
  pago pendiente) sin escribir nada. Un solo SELECT con `in_()`; nada de N+1.
- Alta con `cancel_affected=true`: toma lock del profesional, lista
  afectados, inserta el bloqueo, cancela cada turno reutilizando la
  cancelación existente (guarda y auditoría por turno), publica un evento por
  turno al outbox, commit, invalida caché. Los turnos con pago pendiente en
  Mercado Pago se excluyen del cancelado automático y se listan como
  "requieren liberar" con el botón que ya existe (la llamada a Mercado Pago
  no puede ir dentro del lock). Los turnos con seña acreditada se listan
  como "con seña, decisión del dueño" y no se cancelan solos.
- `book` relee los bloqueos después de tomar el lock, para cerrar la carrera.
- Consumidor del outbox: rama nueva que manda al cliente el mail "tu turno
  fue cancelado" (plantilla nueva) y crea la notificación in-app. El outbox
  pasa a usar `SKIP LOCKED` (hoy no lo usa y puede duplicar con varios
  workers).
- Front: en `CalendarContainer`, antes de crear el bloqueo se llama al
  preview; si hay afectados, un modal con la lista, botón "Avisar por
  WhatsApp" (link `wa.me` con texto prearmado, patrón que ya existe en la
  pantalla de confirmación) y confirmación explícita "Cancelar N turnos y
  bloquear". Al guardar, invalidar también la agenda.

**Modelo y migración.** Ninguna tabla nueva. Evento nuevo en el outbox y tipo
nuevo de notificación.

**Pruebas.** Integración SQLite: preview lista el turno; alta con cancelado
deja el turno cancelado, auditado y con mensaje en outbox; recurrencia
semanal con turnos en varias fechas; turno con pago pendiente no se cancela
y se reporta; ráfaga de N altas idénticas. Postgres: carrera bloqueo contra
reserva (un bloqueo y una reserva concurrentes sobre el mismo rango: solo
una gana); el trigger de estados acepta el cancelado masivo; RLS de
`appointment_blocks`. Front: modal de preview y confirmación.

**Decisiones del dueño.**
- Cancelar en bloque solo para rol administrador (recomendado; hoy cualquier
  personal puede bloquear a cualquiera).
- Qué hacer con turnos con seña acreditada: listar y decidir a mano
  (recomendado), nunca automático.
- Texto del mail de cancelación.

**Riesgos.** `cancelled` es terminal: si el dueño borra el bloqueo después,
los turnos no vuelven; por eso el preview y la confirmación son obligatorios.
El formulario de bloqueos manda la hora tipeada como UTC (deriva probable de
tres horas, inferida): arreglarlo junto con la Fase 0.1.

---

## 5. Fase 2 — Recursos que no son personas (2,5 días) — HECHA el 2026-09-10

**Estado:** completa en `a478fb4` (migración `d3f5a7b9c1e2`). `kind` es
inmutable desde el front (el formulario solo lo ofrece en el alta). Nota de
implementación: zod 4 no aplica el default del discriminador cuando falta la
clave, por eso el validador es objeto + `superRefine` y no una unión
discriminada. Verificado: backend 351, Postgres 11 (migración ida y vuelta),
front 150.

**Objetivo.** Canchas, salas, boxes y sillones reservables sin inventar un
email.

**Qué se vio.** "Profesional" es una fila en `staff` más un usuario con rol
personal creados juntos, con email obligatorio y único global (la unicidad
vive en `users.email`). Ese email no alimenta ninguna notificación ni
reporte; solo sirve como identidad de un login que nadie usa (el usuario
nace con contraseña inutilizable y nadie manda invitación). Toda la
maquinaria de concurrencia, exclusión, bloqueos y reportes está indexada por
`staff_id`, no por nada humano. Conclusión: la tabla `staff` ya es "un
calendario reservable"; lo único que la ata a persona es el alta que crea
el usuario y el texto de la interfaz.

**Diseño (opción mínima, recomendada).**
- Columna `kind` en `staff` (`person` o `resource`, con CHECK), `email`
  opcional. Para `resource` no se crea usuario, no se sincroniza nada hacia
  `users`. `kind` es inmutable después del alta.
- `StaffService` dueño de la transacción (el repositorio hoy commitea; al
  tocarlo se migra al patrón, no se extiende la excepción). `soft_delete`
  pasa a buscar el usuario por id, no por email (arregla de paso que con
  email nulo nunca matcheaba).
- Respuesta pública expone `kind`; el mail de confirmación dice "en Cancha 2"
  en vez de "con Cancha 2" (el tipo viaja en el payload del outbox).
- Front: entidad `Staff` con email nulo (hoy `Email.create` explota con vacío
  y tira abajo la página entera de personal, así que backend y front se
  despliegan juntos); formulario con selector "Persona / Recurso" que oculta
  email y nombre; tarjeta del cliente con `display_name` como título (hoy usa
  nombre y apellido, que para un recurso serían vacíos) y textos por tipo
  ("Elegí cancha" en vez de "Quién te atiende"). Se quita la heurística que
  colorea la tarjeta según si el email contiene "admin"; solo daba color.

**Modelo y migración.** `kind` con CHECK y `email` nullable; downgrade real
que rellena vacío antes de reponer el NOT NULL. La tabla ya tiene RLS y ya
está en el registro de modelos.

**Pruebas.** Integración SQLite: recurso sin email crea 201 y cero filas
nuevas en `users`; persona sin email da 422; disponibilidad y reserva sobre
un recurso; baja de recurso no toca `users`; los tests de colisión de email
y de login del profesional siguen verdes. Postgres: migración y CHECK; la
ráfaga concurrente sobre una cancha. Front: formulario en ambos modos y
tarjeta del cliente por tipo.

**Decisiones del dueño.** Ninguna bloqueante. Aviso: los reportes de
"profesionales" contarán canchas; se etiqueta por tipo. Un servicio que
necesite persona y recurso a la vez queda para la versión completa.

---

## 6. Fase 3 — Post-turno y recordatorio en dos pasos (2 días)

**Objetivo.** Menos ausencias y más re-reservas con el canal que hay.

**Qué se vio.** Hay un solo recordatorio (24 horas antes) cuya única marca
de "ya enviado" es una clave en Redis con vencimiento de siete días: si
Redis se reinicia, se reenvían hasta dos días de recordatorios; si el turno
se reprograma, el movido no recibe recordatorio nuevo. No tiene piso: un
turno reservado para dentro de una hora también recibe el "mañana". Al
completar un turno no pasa nada. La reserva pública no acepta preselección
por URL, así que hoy no se puede armar un link "reservá de nuevo".

**Diseño.**
- Dos columnas en `appointments` (`reminder_24h_sent_at`,
  `reminder_2h_sent_at`) en vez de la clave en Redis: marca durable, visible
  al dueño, y el reclamo `UPDATE ... WHERE ... IS NULL` es seguro entre
  workers sin lock nuevo. Reprogramar las deja en nulo. Piso para el de 24
  horas (más de dos horas de antelación) para que una reserva de último
  momento reciba solo el de 2 horas. El cron cada 15 minutos ya alcanza. La
  función del job se parte en etapas para no pasar de 80 líneas.
- Al completar (`AppointmentService.complete`), después del commit, mail
  "reservá tu próximo turno" con deep-link `/b/{slug}?service=&staff=`,
  best-effort. Requiere cargar servicio, profesional y tienda en una consulta
  explícita del repositorio (hoy solo carga el turno).
- Deep-link en el front: `PublicBooking` lee `service` y `staff` de la URL,
  los valida contra las listas públicas y arranca el wizard en el paso que
  corresponda. Sin `useEffect`: se calcula en el inicializador.
- Botón "Mandar por WhatsApp" del dueño en la tarjeta del turno: link
  `wa.me` con texto según estado (recordatorio o invitación post-turno con el
  deep-link). Requiere exponer el teléfono del cliente en los DTOs del panel
  (`AppointmentListItem`, `AppointmentSearchResult`): la fila ya está unida,
  solo falta mapearla.

**Modelo y migración.** Dos columnas nullable en `appointments`, downgrade
real. Sin tabla nueva.

**Pruebas.** Unitaria: turno a 23 horas recibe solo el de 24; a 1 hora y
media solo el de 2; reclamo fallido no reenvía; tienda con recordatorios
apagados se saltea. Postgres: dos workers reclaman el mismo recordatorio y
solo uno envía; la migración. Integración: completar dispara el mail con el
deep-link y un SMTP caído no impide completar. Front: el deep-link
preselecciona solo ids válidos.

**Decisiones del dueño.**
- Exponer el teléfono del cliente en el panel a todo el personal o solo a
  administradores (es un dato personal visible).
- Texto de los tres mensajes (24 horas, 2 horas, reservá de nuevo).

---

## 7. Fase 4 — Lista de espera con relleno (4 días)

**Objetivo.** Que un cupo liberado no se pierda ni le cueste tiempo al dueño.

**Qué se vio.** Hay seis caminos que liberan un cupo (cancelar, liberar,
reprogramar, cancelar y reprogramar del cliente, y el job que expira señas
impagas) más borrar un bloqueo. Solo uno publica un evento, con datos
insuficientes, y el consumidor lo descarta. No existe entidad, tabla ni
pantalla de lista de espera. Hay dos limitaciones que condicionan el diseño:
el OTP no tiene canal en producción (Fase 0.3) y muchos clientes no tienen
email real (se les genera uno técnico `.noreply`).

**Diseño.**
- Tabla `waitlist_entries` (tienda, cliente, teléfono, servicio, profesional
  opcional o "cualquiera", ventana deseada, estado, `notified_at`,
  `offer_expires_at`), con RLS forzada, registrada en el registro de modelos,
  índice por (tienda, estado, ventana) y unicidad parcial para evitar
  duplicados.
- `POST /public/waitlist`: el cliente se anota desde la página pública cuando
  no hay cupo, sin OTP para anotarse (rate limit por teléfono, como ya existe)
  y con OTP solo para ver o borrar su entrada. Se liga al usuario cliente por
  teléfono con la función que ya lo crea.
- Evento `appointment.slot_released` (profesional, servicio, inicio, fin,
  motivo) publicado en la misma transacción en los seis caminos y en el
  borrado de bloqueos.
- Consumidor en el outbox (con `SKIP LOCKED`): busca entradas que encajen,
  ofrece el cupo **a una sola persona por vez**: le manda el mail con el
  deep-link al slot (Fase 3) y marca `notified_at` y `offer_expires_at` a N
  minutos. Si pasa la ventana y el cupo sigue libre, pasa a la siguiente. La
  exclusividad es blanda: el cupo sigue publicado para cualquiera; quien
  reserva primero gana por el lock y la exclusión que ya existen. No hay
  endpoint de "reclamar": reservar es reservar, y así no se reinventa la
  concurrencia.
- Los cupos dentro de la antelación mínima (dos horas) no se ofrecen a
  clientes por mail (no pueden reservarlos por el portal): se le muestran al
  dueño con el botón `wa.me` y "reservar para este cliente" (el alta desde el
  panel no exige antelación).
- Notificación in-app "se liberó un hueco: N en espera" y una pantalla
  "Lista de espera" en el panel con teléfono, botón `wa.me` con texto
  prearmado y alta directa. Esta pantalla es el canal principal, no el
  secundario: el mail llega solo a quien dejó un mail real.

**Modelo y migración.** Tabla nueva con RLS, registro y downgrade. Tipo
nuevo de notificación.

**Pruebas.** Integración SQLite: anotarse, duplicado rechazado, cada uno de
los seis caminos publica el evento, el consumidor ofrece a uno solo, la
ventana vence y pasa al siguiente, cupos dentro de la antelación mínima no
se mailean. Postgres: RLS de la tabla nueva (el test de registro obliga);
dos anotados reservan a la vez el mismo cupo y solo uno gana; dos workers
del outbox no duplican el aviso. Front: pantalla de lista de espera y el
formulario de anotarse.

**Decisiones del dueño.**
- Regla de encaje: mismo servicio y mismo profesional o "cualquiera"; ¿se
  ofrece un cupo de otra duración?
- N minutos de la ventana (propuesta: 10).
- Anotarse sin OTP (propuesta: sí, con rate limit) o con OTP por email.
- Unicidad de teléfono por tienda: hoy dos clientes con el mismo teléfono
  rompen la identificación con un 500. Conviene resolverlo en esta fase.

---

## 8. Fase 5 — Seña por antelación e historial (2,5 días)

**Objetivo.** Cobrar más seña donde el riesgo de ausencia es mayor, con
reglas fijas que el dueño entiende. Solo el cálculo del monto; nada de
cancelaciones ni reembolsos.

**Qué se vio.** El cálculo puro vive en una función sin contexto
(`calculate_service_payment_amount`) que solo mira el servicio. La decisión
"se cobra y cuánto" se evalúa tres veces dentro de `create_public_booking`
(331 líneas). En ese punto ya están la antelación (el mismo lugar donde se
aplica la antelación mínima) y el teléfono. Las columnas
`Store.requires_deposit` y `deposit_percentage` están muertas. No hay
consulta de historial del cliente. No se sabe quién canceló un turno (el
cancelado público no audita), así que "cancelación tardía del cliente" no es
derivable con certeza: la regla no debe usarla.

**Diseño.**
- Función pura y sin framework (`payments/deposit_rules.py`): recibe
  servicio, precio base, antelación, reglas de la tienda y un resumen del
  historial; devuelve monto y motivo. Se evalúa **una sola vez** por reserva
  y el resultado viaja hasta el pago y la respuesta (hoy se recalcula tres
  veces con `now` distinto; con umbrales de antelación darían resultados
  distintos en el mismo pedido). Sacar esa evaluación del router es además
  el primer recorte a las 331 líneas.
- Historial en una sola consulta agregada (turnos completados, ausentes),
  antes del lock, con `store_id` explícito. Cliente nuevo: historial vacío
  sin crear el usuario todavía.
- Reglas por tienda en columnas con CHECK (patrón de `deposit_policy`),
  editables desde ajustes con mínimo y máximo: días de antelación a partir
  de los cuales sube la seña y en cuánto; recargo para cliente sin historial;
  recargo para cliente con ausencias. Las columnas muertas se dejan y se
  documentan como muertas (limpieza aparte).
- `GET /public/deposit/preview` (molde: el preview de promociones) para que
  el front muestre la seña real antes de confirmar; hoy infiere "hay seña"
  desde los campos crudos del servicio y divergiría.
- El motivo de la seña aplicada se guarda en el pago como snapshot.
- El link que genera el dueño desde el panel y el cobro manual siguen usando
  la seña base, documentado. Es decisión del dueño cambiarlo.

**Modelo y migración.** Columnas nuevas en `stores` con CHECK y downgrade.
`min_booking_notice_hours` pasa a ser editable por API (hoy no lo es; los
tests que creen configurarlo no hacen nada).

**Pruebas.** Unitaria pura de la regla y de los bordes (fijo mayor que el
precio, porcentaje sobre precio con promo, redondeo; hoy no hay ninguna).
Integración SQLite: montos y "requiere pago" según antelación e historial;
un reintento con la misma clave de idempotencia devuelve el mismo monto.
Postgres: migración y CHECK; ráfaga que confirme que la consulta de
historial no serializa reservas.

**Decisiones del dueño.** Umbral de días y recargo; recargo por cliente
nuevo; recargo por ausencias previas; si aplica al link del panel. Aviso: el
texto de `deposit_policy` que el cliente acepta lo redacta la tienda; si la
seña varía y el texto no lo dice, es problema de la tienda, no del sistema.

---

## 9. Fase 6 — Suscripción: aviso y gracia (2 días)

**Objetivo.** Que el dueño de la tienda sepa cuándo vence su plan antes de
que pase nada, y que Shifty pueda cobrar sin cortar de golpe.

**Qué se vio.** La suscripción es un registro informativo: cuando vence no
pasa nada (ni login, ni panel, ni página pública), no hay job que la evalúe,
no hay aviso, el dueño no ve su plan en ninguna pantalla y el estado es texto
libre (el front ofrece valores que el backend no conoce). Además: reasignar
un plan por API sin fechas borra el período vigente (el modal lo enmascara),
y el modal del superadmin probablemente corre el vencimiento tres horas
(inferido).

**Diseño.**
- Máquina de estados de la suscripción (`active`, `past_due`, `suspended`,
  `cancelled`) con diccionario de transiciones, CHECK en la base y `Literal`
  en el schema, espejo de la de pagos. Constante de días de gracia.
- Job diario en `billing/tasks.py` (patrón de la purga de sesiones, con
  bypass RLS explícito y `SKIP LOCKED`): aviso N días antes, `active` a
  `past_due` al vencer, `past_due` a `suspended` al agotar la gracia. Aritmética
  de calendario en zona Argentina.
- Aviso por notificación in-app (la campanita ya renderiza cualquier tipo) y
  mail a los administradores por el outbox, idempotente por día.
- `GET /stores/me/subscription` (estado, vencimiento, días restantes, plan).
  Ojo: la tabla de planes es solo para superadmin en RLS; el nombre del plan
  se lee con bypass acotado o se copia a la suscripción.
- Banner en el panel (donde hoy hay un "Estado: En línea" fijo) con link
  `wa.me` al soporte de Shifty.
- Arreglar el bug de reasignación (`exclude_unset`) y la deriva de tres horas
  del modal. Superadmin ve "vence en N días" y ordena por vencimiento.

**Modelo y migración.** CHECK sobre `status` compatible con las filas
existentes; columna `grace_until` o constante.

**Pruebas.** Integración SQLite: el job avisa, transiciona y no duplica;
reasignar plan sin fechas conserva el período. Postgres: RLS (un pedido de
tienda lee su suscripción y no lee planes); migración con CHECK. Front:
banner por estado.

**Decisiones del dueño.**
- Días de aviso (propuesta: 7) y de gracia (propuesta: 7).
- Qué significa "suspendida" (propuesta: se esconde la página pública y se
  bloquean las escrituras del panel; el login sigue para que pueda pagar).
  Bloquear la página pública castiga a los clientes de la tienda, así que es
  decisión de negocio.

---

## 10. Fase 7 — El cliente desde el teléfono (2,5 días)

**Objetivo.** Que reservar y autogestionarse desde el celular sea corto, y
que exista una prueba que lo recorra como un cliente.

**Qué se vio.** Reservar son cinco pasos (seis con OTP) en un wizard cuyo
estado se pierde con recargar o volver atrás. No existe pantalla del cliente
para ver, cancelar o reprogramar: los tres endpoints del backend no tienen
consumidor en el front. El teléfono de la tienda en el encabezado es texto,
no link. Cero tests del flujo público (ni Jest ni E2E). En 360 píxeles el
contenido útil queda en unos 216 (inferido).

**Diseño.**
- Página "Mis turnos" del cliente (teléfono más OTP por email, Fase 0.3):
  ver, cancelar y reprogramar con los endpoints existentes. La cancelación
  del cliente pasa a avisar a la tienda (hoy no publica nada).
- Menos pasos: saltar "Profesional" cuando hay uno solo (o "Servicio" cuando
  hay uno solo); deep-links `?service=&staff=&date=`; paso sincronizado con
  la URL para que atrás y recargar no pierdan todo; respetar la ventana OTP
  de 30 minutos que el backend ya acepta.
- Encabezado con link `wa.me` a la tienda con texto prearmado, y en la
  pantalla de éxito un segundo link "quiero cambiar mi turno" mientras la
  autogestión madura.
- Botón "Copiar link / compartir" en ajustes, con links por servicio, para
  que el dueño los mande a mano.
- Pruebas: tests Jest del wizard con los hooks simulados (hoy cobertura
  cero) y un E2E con Playwright en viewport móvil contra el stack local.
  Playwright es una dependencia nueva: verificación humana en el registro y
  lockfile en el mismo commit; primero como script local, después como job.

**Decisiones del dueño.** "Recordarme en este teléfono" (nombre y teléfono
en el dispositivo, opt-in): sí o no; es dato personal en celulares
compartidos.

---

## 11. Resumen de estimaciones

| Fase | Días |
|---|---|
| 0. Arreglos que afectan a todo cliente | 5,5 |
| 1. Bloqueos sobre turnos tomados | 3 |
| 2. Recursos que no son personas | 2,5 |
| 3. Post-turno y dos recordatorios | 2 |
| 4. Lista de espera con relleno | 4 |
| 5. Seña por antelación e historial | 2,5 |
| 6. Suscripción: aviso y gracia | 2 |
| 7. Cliente desde el teléfono | 2,5 |
| **Total** | **24** |

Sumar un 50% a la Fase 4 si la regla de encaje termina siendo más rica que
"mismo servicio y profesional". Cada fase entra con su test contra Postgres
y CI verde antes de la siguiente.

---

## 12. Invariantes nuevas para `CLAUDE.md` (al implementar cada fase)

- Todo camino que cambia disponibilidad llama al helper único de
  invalidación de caché y publica `appointment.slot_released`; un test
  enumera los caminos.
- El outbox usa `SKIP LOCKED`; cualquier consumidor nuevo es idempotente por
  fila (`notified_at`, `sent_at`) y nunca manda dentro de una transacción.
- Toda hora que ve un cliente (pantalla, mail, link) se formatea con
  `ARGENTINA_TZ`; el front manda el `starts_at` ISO del slot, nunca
  recompone fecha y hora.
- Un flag de tienda que dependa de un canal externo (OTP) no se puede activar
  si el canal no está configurado.
- `kind` de un recurso es inmutable; un recurso nunca tiene usuario.
- La seña se evalúa una sola vez por reserva y el resultado viaja hasta el
  pago; el motivo queda como snapshot.
- Reglas fijas de negocio (seña, suscripción) viven en columnas con CHECK,
  no en JSON de vitrina.

---

## 13. Lo que no se verificó y conviene mirar primero

- La hora en UTC en la reserva pública y el día equivocado para turnos
  nocturnos: inferido del código, reproducir con test antes de tocar.
- La deriva de tres horas al editar bloqueos desde el calendario y al cargar
  vencimientos en el superadmin: inferidas.
- Si en producción existen filas de `staff` cuyo id no coincide con su
  usuario (el seed las crea así).
- El impacto de las canchas en los reportes de ocupación por profesional.
- La pantalla de reserva a 360 píxeles de ancho.
- El panel del profesional: hoy ve la agenda entera de la tienda (solo los
  reportes se acotan a lo propio). No es parte de este plan pero el dueño
  debe saberlo.
