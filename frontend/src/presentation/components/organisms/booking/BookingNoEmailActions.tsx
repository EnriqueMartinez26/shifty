import React from 'react'

import { CalendarPlus, ExternalLink, MessageCircle } from 'lucide-react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { formatArgentinaDayHeading, formatArgentinaTime } from '@shared/utils/argentinaTime'
import { buildCalendarInvite, downloadCalendarInvite } from '@shared/utils/calendarInvite'
import { buildWaMeUrl, buildWaShareUrl } from '@shared/utils/whatsAppPhone'

import { colors2000s } from '../../../../theme/colors'

/**
 * Quien reserva sin email (propuesta por Mateo, 2026-10-16) no recibe avisos
 * ni entra a "Mis turnos": el codigo de acceso sale solo por email. Esta
 * pantalla le da lo que necesita para no perder el turno.
 */

/** "jueves 23/10 a las 15:00" en hora argentina, o vacio si no se puede leer. */
const bookedWhen = (startsAt: string): string => {
  const day = formatArgentinaDayHeading(startsAt)
  const time = formatArgentinaTime(startsAt)
  return day && time ? `${day} a las ${time}` : ''
}

/** "Turno reservado para el jueves 23/10 a las 15:00 con Natalia." */
export const bookedSummary = (confirmation: BookingConfirmation): string => {
  const when = bookedWhen(confirmation.starts_at)
  const staff = confirmation.staff_name?.trim()
  return `Turno reservado${when ? ` para el ${when}` : ''}${staff ? ` con ${staff}` : ''}.`
}

/** "Corte + Barba" con varios servicios en el turno; si no, el servicio. */
const servicesOf = (confirmation: BookingConfirmation): string =>
  confirmation.services_label || confirmation.service_name

const selfShareText = (confirmation: BookingConfirmation, storeName: string): string =>
  [
    bookedSummary(confirmation),
    ...(servicesOf(confirmation) ? [`Servicio: ${servicesOf(confirmation)}`] : []),
    `Lugar: ${storeName}`
  ].join('\n')

const storeMessage = (confirmation: BookingConfirmation): string => {
  const when = bookedWhen(confirmation.starts_at)
  return `Hola, reservé el turno ${confirmation.public_id}${when ? ` para el ${when}` : ''}. Quiero cambiarlo/cancelarlo.`
}

const inviteFor = (confirmation: BookingConfirmation, storeName: string) => {
  const staff = confirmation.staff_name?.trim()
  return {
    uid: confirmation.public_id,
    startsAt: confirmation.starts_at,
    endsAt: confirmation.ends_at,
    summary: servicesOf(confirmation)
      ? `${servicesOf(confirmation)} en ${storeName}`
      : `Turno en ${storeName}`,
    description: `Turno ${confirmation.public_id}${staff ? ` con ${staff}` : ''}. Para cambiarlo o cancelarlo, comunicate con ${storeName}.`
  }
}

const secondaryStyle: React.CSSProperties = {
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  borderColor: colors2000s.border.default,
  color: colors2000s.text.primary,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
}
const secondaryClass =
  'w-full mt-4 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs border cursor-pointer select-none inline-flex items-center justify-center gap-2'

interface BookingNoEmailActionsProps {
  confirmation: BookingConfirmation
  storeName: string
  whatsappNumber?: string | null
}

/** Aviso y acciones para una reserva sin email: calendario y WhatsApp. */
export const BookingNoEmailActions: React.FC<BookingNoEmailActionsProps> = ({
  confirmation,
  storeName,
  whatsappNumber
}) => {
  const invite = inviteFor(confirmation, storeName)
  const canAddToCalendar = buildCalendarInvite(invite) !== null
  // null si el WhatsApp de la tienda no se puede leer como numero: sin boton.
  const storeHref = buildWaMeUrl(whatsappNumber, storeMessage(confirmation))

  return (
    <div className="w-full mt-6">
      <p
        role="note"
        className="rounded-md border p-4 text-left text-sm font-bold"
        style={{ background: '#fff7ed', borderColor: '#fed7aa', color: '#9a3412' }}
      >
        Como no dejaste email, no te vamos a mandar recordatorios. Guardalo en tu calendario o
        mandátelo por WhatsApp.
      </p>

      {canAddToCalendar && (
        <button
          type="button"
          onClick={() => downloadCalendarInvite(invite, `turno-${confirmation.public_id}.ics`)}
          className={secondaryClass}
          style={secondaryStyle}
        >
          <CalendarPlus className="w-4 h-4" />
          Agregar al calendario
        </button>
      )}

      <a
        href={buildWaShareUrl(selfShareText(confirmation, storeName))}
        target="_blank"
        rel="noreferrer"
        className={secondaryClass}
        style={secondaryStyle}
      >
        <MessageCircle className="w-4 h-4" />
        Mandármelo por WhatsApp
      </a>

      {storeHref ? (
        <a
          href={storeHref}
          target="_blank"
          rel="noreferrer"
          className={secondaryClass}
          style={secondaryStyle}
        >
          Escribirle a {storeName} por WhatsApp
          <ExternalLink className="w-4 h-4" />
        </a>
      ) : (
        <p className="w-full mt-4 text-sm font-bold text-gray-600">
          Para cambiarlo o cancelarlo, comunicate con {storeName}.
        </p>
      )}
    </div>
  )
}
