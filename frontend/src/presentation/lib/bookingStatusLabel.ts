import { isBookingStatus, type BookingStatusValue } from '@domain/value-objects/BookingStatus'

// Record sobre BookingStatusValue: si el dominio suma un estado, esto deja de
// compilar en vez de mostrar el codigo crudo en silencio.
const BOOKING_STATUS_LABELS: Record<BookingStatusValue, string> = {
  pending: 'Pendiente',
  pending_payment: 'Pendiente de pago',
  confirmed: 'Confirmado',
  completed: 'Completado',
  cancelled: 'Cancelado',
  absent: 'Ausente',
  expired: 'Vencido'
}

/**
 * Etiqueta en castellano del estado de un turno. Un estado que el backend
 * sumo antes que el front se muestra crudo (ver `isBookingStatus`).
 */
export const bookingStatusLabel = (status: string): string =>
  isBookingStatus(status) ? BOOKING_STATUS_LABELS[status] : status
