import { formatArgentinaDateDisplay, formatArgentinaTime } from './argentinaTime'
import { sanitizePhoneForUrl } from './safeUrl'

export type ClientMessageKind = 'reminder' | 'rebook'

export interface ClientMessageInput {
  clientName: string
  serviceName: string
  staffName: string
  startsAt: Date
  storeName: string
  rebookUrl?: string | null
}

/**
 * Deep-link a la reserva publica con servicio y profesional preseleccionados.
 * Es el mismo que arma el backend en el mail "reserva de nuevo".
 */
export const buildRebookUrl = (
  origin: string,
  slug: string,
  serviceId: string,
  staffId: string
): string => {
  const params = new URLSearchParams({ service: serviceId, staff: staffId })
  return `${origin.replace(/\/$/, '')}/b/${slug}?${params.toString()}`
}

/**
 * Texto prearmado para que el dueno lo mande por WhatsApp a mano (link wa.me,
 * costo cero). Recordatorio para turnos que todavia no pasaron; invitacion
 * a volver para turnos completados.
 */
export const buildClientMessage = (kind: ClientMessageKind, input: ClientMessageInput): string => {
  const nombre = input.clientName.trim() ? `Hola ${input.clientName.trim()}!` : 'Hola!'
  const iso = input.startsAt.toISOString()
  const cuando = `${formatArgentinaDateDisplay(iso)} a las ${formatArgentinaTime(iso)} hs`
  if (kind === 'rebook') {
    const link = input.rebookUrl ? ` Reserva tu proximo turno en un toque: ${input.rebookUrl}` : ''
    return `${nombre} Gracias por venir a ${input.storeName}.${link}`
  }
  return `${nombre} Te recordamos tu turno para ${input.serviceName} con ${input.staffName} el ${cuando}. Te esperamos en ${input.storeName}.`
}

/** Que mensaje corresponde segun el estado del turno; null si no tiene sentido. */
export const clientMessageKindFor = (status: string): ClientMessageKind | null => {
  if (status === 'completed') return 'rebook'
  if (status === 'pending' || status === 'confirmed') return 'reminder'
  return null
}

export const buildWaMeUrl = (phone: string, text: string): string =>
  `https://wa.me/${sanitizePhoneForUrl(phone)}?text=${encodeURIComponent(text)}`
