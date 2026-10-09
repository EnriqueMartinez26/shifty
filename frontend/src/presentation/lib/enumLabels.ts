/**
 * Etiquetas en castellano de los enums que la API manda crudos. Una sola tabla
 * por enum: la UI mostraba el valor de la API ("CLIENT", "ACTIVE",
 * "available") con uppercase encima (QA 2026-10-02). Un valor que el backend
 * sumo antes que el front se muestra crudo, como `bookingStatusLabel`.
 */

const labelFrom =
  (labels: Readonly<Record<string, string>>) =>
  (value: string): string =>
    Object.hasOwn(labels, value) ? (labels[value] ?? value) : value

/** `users.role` (modules/users/model.py). */
export const userRoleLabel = labelFrom({
  admin: 'Administrador',
  staff: 'Profesional',
  receptionist: 'Recepción',
  client: 'Cliente'
})

/** `store_subscriptions.status` (CHECK en billing/model.py). */
export const subscriptionStatusLabel = labelFrom({
  active: 'Activa',
  past_due: 'Pago vencido',
  suspended: 'Suspendida',
  cancelled: 'Cancelada'
})

/** `plans.billing_interval`: los valores que ofrece el alta de planes. */
export const billingIntervalLabel = labelFrom({
  monthly: 'Mensual',
  quarterly: 'Trimestral',
  yearly: 'Anual',
  custom: 'Personalizado'
})

/** Estado de un horario de `/public/availability`. */
export const slotStatusLabel = labelFrom({
  available: 'Libre',
  booked: 'Ocupado',
  blocked: 'Bloqueado'
})
