# 🛠 Plan de Pulido: Shifty v2

Este plan detalla las mejoras para alinear el sistema con la documentación técnica y elevar la calidad de la experiencia de usuario.

## 1. Calendario de Gestión (Admin/Staff)
El objetivo es transformar la grilla estática en una agenda viva y profesional.

### Mejoras Visuales
- [ ] **Bloques Dinámicos**: Los turnos deben ocupar el alto proporcional a su duración (ej: 60 min = 4 slots).
- [ ] **Indicadores de Estado**: 
  - `PENDING`: Borde punteado, fondo grisáceo.
  - `CONFIRMED`: Fondo Indigo sólido.
  - `COMPLETED`: Fondo Emerald (verde) con check.
  - `ABSENT`: Fondo Amber (naranja) con icono de alerta.
  - `CANCELLED`: Tachado y opaco (opcional, generalmente se ocultan).
- [ ] **Información de Slot**: Mostrar nombre del servicio y cliente dentro del bloque si hay espacio.

### Funcionalidad
- [ ] **Acciones Rápidas (Context Menu)**: Al hacer clic en un turno, mostrar un modal o menú para:
  - Confirmar (si está PENDING).
  - Completar (si está CONFIRMED).
  - Marcar como Ausente (si ya pasó la hora).
  - Ver notas del profesional.
- [ ] **Drag & Drop (Reprogramación)**: Implementar la lógica para mover un bloque a otro horario/staff, disparando el endpoint `/reschedule`.

## 2. Portal Público de Reservas

### Robustez Técnica
- [ ] **Fijar Idempotency Key**: Generar la clave una sola vez al cargar el componente o al entrar en el último paso, y no cambiarla en cada clic de reintento.
- [ ] **Validación de Teléfono**: Agregar una validación básica de formato para asegurar que el `client_phone` sea útil para el comercio.

### Diseño Premium
- [ ] **Micro-interacciones**: Agregar transiciones suaves de entrada (`framer-motion` o CSS transitions) entre pasos.
- [ ] **Branding Refinado**: Asegurar que los estados de *hover* y *focus* también respeten el `primary_color` del salón.

## 3. Reportes y Dashboard
- [ ] **Gráficos Rápidos**: Agregar un pequeño gráfico de 'Ingresos por día' o 'Turnos por estado' en la página principal para dar una visión rápida al administrador.

---

## Próximos Pasos
1. Implementar los **Bloques Dinámicos** en `Calendar.tsx`.
2. Crear el **Modal de Acciones** de turnos.
3. Ajustar la **Idempotencia** en `PublicBooking.tsx`.
