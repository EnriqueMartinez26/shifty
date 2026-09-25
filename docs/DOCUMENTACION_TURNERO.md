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
| `POST` | `/appointments/` | Crear una reserva (requiere `idempotency_key` en el cuerpo). Sin `client_phone`: auto-turno a nombre de quien llama (`staff_id` obligatorio, `starts_at` futuro). Con `client_name` + `client_phone` (+ `client_email` opcional): turno del panel PARA ESE CLIENTE (FF-04): `staff_id` opcional (sin el, el primer profesional libre que hace el servicio; el profesional solo reserva en su agenda, 403 si no), `starts_at` UTC tal cual el slot, hasta 5 minutos en el pasado y hasta 120 dias locales hacia adelante (el horizonte del portal; el auto-turno, hasta 2 anios), sin antelacion minima, OTP, campos extra, `accepts_terms` ni sena: nace `confirmed`, sin cobro y con `terms_accepted_at` nulo; precio de lista congelado; buffer, bloqueos y choques siempre. Fuera de la jornada del profesional: 409 `OUT_OF_SCHEDULE`, salvo `allow_outside_schedule: true` (solo admin; si no, 403). Reutiliza la ficha del cliente de la tienda por telefono sin pisarla. Errores: 404 `RESOURCE_NOT_FOUND` (servicio), 422 (profesional que no hace el servicio, pasado, mas alla del horizonte, datos incompletos, caracteres de control), 409 `SCHEDULE_BLOCKED` / `APPOINTMENT_CONFLICT` / `NO_STAFF_AVAILABLE` / `IDEMPOTENCY_IN_PROGRESS`, 409 `RESOURCE_CONFLICT` neutro si el email del cliente nuevo ya es de otro usuario (unico global) o si la `idempotency_key` ya la uso otro turno (la idempotencia de Redis es por tienda), 402 `SUBSCRIPTION_SUSPENDED`. Respuesta: `AppointmentResponse` (201). |
| `GET` | `/appointments/availability` | Consulta slots libres para un servicio/fecha. |
| `PATCH` | `/appointments/{id}/confirm` | Cambia estado a confirmado. |
| `PATCH` | `/appointments/{id}/reschedule` | Reprograma un turno (cancela el anterior y crea uno nuevo atómicamente). |
| `GET` | `/appointments/search` | Búsqueda con filtros dinámicos y paginación (`page`/`page_size`). `include_total=false` no cuenta el total y devuelve `total: null` (para las paginas 2 en adelante; F3-06). Cada respuesta trae `next_cursor` (null si no hay mas); pasarlo como `after` pide la pagina siguiente por clave `(starts_at, id)` sin `OFFSET` (`after` con `page` > 1 es 422; F3-08). |
| `GET` | `/ledger/customers/{client_id}` | Historial de fiado paginado (`limit`/`offset`). Trae `next_cursor`; pasarlo como `after` pide la pagina siguiente por clave `(created_at, id)` sin `OFFSET` (`after` con `offset` > 0 es 422; F3-08). |
| `GET` | `/reports/summary` | Resumen del rango con detalle paginado (`limit`/`offset`). `order=desc` devuelve el detalle del mas reciente al mas viejo; con `limit=6`, los 6 mas recientes (F3-06). |
| `GET` | `/appointment-blocks/` | Bloqueos de la tienda: los leen los roles que gestionan bloqueos (admin y profesional) y, solo lectura, la recepcion (FF-14); todos ven los de toda la tienda. Sin parametros: todos, activos e inactivos, de toda la historia (como siempre). F4-07 (aditivo): `from_date` + `to_date` (dias LOCALES, los dos o ninguno; `to_date >= from_date`; hasta 400 dias incluidos; una fecha sin dia siguiente, como 9999-12-31, tambien es 422) devuelven los que solapan `[medianoche local de from_date, medianoche local del dia siguiente a to_date)`; `include_inactive=false` saca los desactivados (ausente = incluirlos, el default de siempre). Orden por inicio. |
| `GET` | `/users/` | Usuarios de la tienda (solo admin; `q` no cambia los roles: el buscador para el profesional en Fiado, parte de FF-20, sigue pendiente). Filtros de siempre (`include_inactive`, `email`, `role`, `limit` 1..500 default 200, `offset` 0..1.000.000). `q` (FF-20/F4-03, aditivo; 2..80 caracteres, sin caracteres de control; si no, 422): nombre, apellido o "nombre apellido" que CONTIENE `q` sin distinguir mayusculas, o, si `q` es un telefono (digitos y `+ - ( )` o espacios, 2 o mas digitos), telefono que contiene esos digitos. Los comodines de LIKE (`%`, `_`) y la barra invertida en `q` son literales. Para Fiado: `?role=client&q=...`. La consulta queda acotada por `ix_users_store_id` (el `ILIKE` es filtro sobre las filas de la tienda; `tests/postgres/test_pg_busqueda_de_clientes.py`). |
| `GET` | `/superadmin/stores` | Listado de tiendas del soporte global (solo `is_global_admin`). `is_active`: `true` (default, igual que antes), `false` o `all` (sin filtro de estado; FF-24); `search`, `has_subscription`, `limit` (1..200, default 50), `offset` (0..1.000.000). La respuesta sigue siendo la lista; el total con los mismos filtros y sin paginar viaja en el header `X-Total-Count` (expuesto por CORS). |
| `GET` | `/public/client/{store_public_id}/{phone}/appointments` | Historial del cliente (requiere OTP reciente). Cada turno trae `can_cancel` y `can_reschedule`, calculados con las MISMAS reglas que las acciones (`client_cancel_denial` / `client_reschedule_denial` y el grafo de estados): `false` si el turno es terminal (`cancelled`, `completed`, `absent`, `expired`), si tiene un pago en curso (`pending_payment`) o si ya esta dentro de la ventana de cancelacion de la tienda; `can_reschedule` es ademas `false` con un pago acreditado (aprobado o confirmado a mano; un pago devuelto no cuenta). Las acciones responden 409 `PAYMENT_APPOINTMENT_REQUIRES_RELEASE`, `CANCELLATION_WINDOW_EXPIRED` o `PAID_APPOINTMENT_RESCHEDULE_DENIED` con mensajes para el cliente. |
| `GET` | `/public/stores/{slug}/ref` | Referencia minima para "Mis turnos" (FF-16): `{store_public_id, name, accepts_new_bookings}`. Responde tambien con la suscripcion suspendida (`accepts_new_bookings: false`), para que el cliente llegue a cancelar o reprogramar; `GET /public/stores/{slug}` sigue dando 404 en ese caso. 404 `STORE_NOT_FOUND` (el mismo de la vitrina) si la tienda no existe o esta dada de baja. Slug sin distinguir mayusculas. `Cache-Control: no-store`; rate limit `public-read`. |
| (varias) | Horizontes y fechas extremas | Toda fecha que manda un request tiene cota y fuera de ella responde 422, nunca 500 (revision de perf/f4-back): reservar o reprogramar desde el portal, el alta del panel para un cliente y reservar desde la lista de espera, hasta `BOOKING_HORIZON_DAYS` (120 dias locales, el horizonte de `/public/availability`); el auto-turno y la reprogramacion del panel, hasta 2 anios; la lista de espera y el alta para un cliente, no mas de 5 minutos en el pasado; bloqueos, cada instante mandado entre hace 2 anios y dentro de 2 anios mas 366 dias (el PATCH solo mira los extremos que cambia); periodo de una suscripcion del superadmin, +-5 anios; filtros de dia (agenda, busqueda, reportes, bloqueos) sin 9999-12-31, y la grilla de `/appointments/availability` sin 0001-01-01 ni 9999-12-31. |

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
