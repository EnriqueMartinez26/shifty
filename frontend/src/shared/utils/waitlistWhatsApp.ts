import { formatArgentinaDateDisplay } from './argentinaTime'

export interface WaitlistMessageInput {
  clientName: string
  serviceName: string
  staffName: string | null
  windowStartsAt: string
  storeName: string
  bookingUrl?: string | null
}

/**
 * Texto prearmado para avisarle por WhatsApp a alguien de la lista de espera
 * que se libero un lugar (link wa.me, costo cero).
 */
export const buildWaitlistMessage = (input: WaitlistMessageInput): string => {
  const nombre = input.clientName.trim() ? `Hola ${input.clientName.trim()}!` : 'Hola!'
  const con = input.staffName ? ` con ${input.staffName}` : ''
  const dia = formatArgentinaDateDisplay(input.windowStartsAt)
  const link = input.bookingUrl ? ` Podes reservarlo aca: ${input.bookingUrl}` : ''
  return `${nombre} Se libero un lugar para ${input.serviceName}${con} el ${dia}, como pediste en la lista de espera de ${input.storeName}.${link} Avisanos si lo queres.`
}
