/**
 * Eventos de la agenda (turnos, ausencias y bloqueos) en una sola lista, sin
 * React: salio de CalendarContainer (F11c-08) para poder probarlo solo.
 */

import type { Appointment } from '@domain/entities/Appointment'
import { isBookingStatus } from '@domain/value-objects/BookingStatus'

import type { AppointmentBlock } from '@application/services/AppointmentBlocksService'

import { formatArgentinaDate } from '@shared/utils/argentinaTime'

import { reportUnknownStatus } from './reportUnreadableInstant'

export type UnifiedCalendarEvent =
  | {
      id: string
      type: 'appointment' | 'absence'
      staffId: string
      staffName: string
      title: string
      subtitle: string
      startsAt: Date
      endsAt: Date
      status: string
      /** Solo llega para administradores (dato personal). */
      clientPhone: string | null
      serviceId: string
    }
  | {
      id: string
      type: 'block'
      staffId: string
      staffName: string
      title: string
      subtitle: string
      startsAt: Date
      endsAt: Date
      status: 'blocked'
    }

/** Un dia sin eventos: la misma referencia siempre, para que la grilla no se recalcule. */
export const NO_EVENTS: readonly UnifiedCalendarEvent[] = []

/**
 * `toISOString()` de un `Date` invalido no devuelve vacio: lanza `RangeError`.
 * En un camino de render eso tumba la agenda entera por un solo turno con
 * fecha corrupta, asi que la cadena vacia entra a los formateadores de
 * `argentinaTime`, que ya la resuelven como "sin dato".
 */
export const toInstantIso = (date: Date) => (Number.isNaN(date.getTime()) ? '' : date.toISOString())

export const eventPriority = (event: UnifiedCalendarEvent) => {
  if (event.type === 'block') return 0
  if (event.type === 'absence') return 1
  return 2
}

interface UnifiedEventSources {
  appointments: readonly Appointment[]
  /** Bloqueos ya recortados al rango visible. */
  blocks: readonly AppointmentBlock[]
  staffMembers: readonly { id: string; displayName: string }[] | undefined
}

/** Por inicio y, a igual inicio, bloqueo, ausencia y turno (`eventPriority`). */
export const buildUnifiedEvents = ({
  appointments,
  blocks,
  staffMembers
}: UnifiedEventSources): UnifiedCalendarEvent[] => {
  const appointmentEvents: UnifiedCalendarEvent[] = appointments.map((appointment) => {
    // Un estado nuevo del backend se muestra crudo y sin acciones; esto
    // deja la senal en vez de pasar inadvertido (F8-03).
    if (!isBookingStatus(appointment.status)) {
      reportUnknownStatus('agenda', appointment.status)
    }
    return {
      id: appointment.id,
      type: appointment.status === 'absent' ? 'absence' : 'appointment',
      staffId: appointment.staffId,
      // Primero el nombre autoritativo que manda el backend (del join, vale
      // aunque el profesional este dado de baja o el listado de staff no
      // haya cargado); el cruce por id queda como respaldo.
      staffName:
        appointment.staffName ||
        staffMembers?.find((staff) => staff.id === appointment.staffId)?.displayName ||
        'Profesional',
      title: appointment.clientName,
      subtitle: appointment.serviceName,
      startsAt: appointment.timeSpan.getStartsAt(),
      endsAt: appointment.timeSpan.getEndsAt(),
      status: appointment.status,
      clientPhone: appointment.clientPhone,
      serviceId: appointment.serviceId
    }
  })

  const blockEvents: UnifiedCalendarEvent[] = blocks.map((block) => {
    const staffName =
      staffMembers?.find((staff) => staff.id === block.staff_id)?.displayName || 'Profesional'
    return {
      id: block.public_id,
      type: 'block',
      staffId: block.staff_id,
      staffName,
      title: block.reason,
      subtitle: 'Bloqueo de agenda',
      startsAt: new Date(block.starts_at),
      endsAt: new Date(block.ends_at),
      status: 'blocked'
    }
  })

  return [...blockEvents, ...appointmentEvents].sort((a, b) => {
    const startDiff = a.startsAt.getTime() - b.startsAt.getTime()
    if (startDiff !== 0) return startDiff
    return eventPriority(a) - eventPriority(b)
  })
}

// Dia argentino de cada evento, calculado UNA vez por lista (F4-08): la vista
// mes lo recalculaba dias x eventos veces en cada render.
export const groupEventsByDay = (events: readonly UnifiedCalendarEvent[]) => {
  const byDay = new Map<string, UnifiedCalendarEvent[]>()
  for (const event of events) {
    const key = formatArgentinaDate(toInstantIso(event.startsAt))
    const bucket = byDay.get(key)
    if (bucket) bucket.push(event)
    else byDay.set(key, [event])
  }
  return byDay
}
