import React, { useId } from 'react'

import { ExternalLink, PenTool } from 'lucide-react'

import { defaultPriorDesignMessage } from '@domain/entities/Service'
import { formatAddonsLabel } from '@domain/value-objects/AddonSelection'

import type { BookingConfirmation, PublicService } from '@application/services/PublicBookingService'

import { buildWaMeUrl } from '@shared/utils/whatsAppPhone'

import { colors2000s } from '../../../../theme/colors'
import { brandColor } from '../../../lib/brandTheme'

const whatsAppButtonStyle: React.CSSProperties = {
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  borderColor: colors2000s.border.default,
  color: brandColor.ink,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
}

/** Boton secundario de la pantalla de exito que abre un chat de WhatsApp. */
export const WhatsAppLinkButton: React.FC<{ href: string; children: React.ReactNode }> = ({
  href,
  children
}) => (
  <a
    href={href}
    target="_blank"
    rel="noreferrer"
    className="w-full min-h-[44px] mt-6 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs border cursor-pointer select-none inline-flex items-center justify-center gap-2"
    style={whatsAppButtonStyle}
  >
    {children}
    <ExternalLink className="w-4 h-4" aria-hidden="true" />
  </a>
)

type PriorDesignFields = Pick<PublicService, 'requires_prior_design' | 'prior_design_message'>

/** El mensaje propio del primer servicio marcado que lo tenga; si no, el de siempre. */
const priorDesignMessage = (flagged: readonly PriorDesignFields[], storeName: string): string =>
  flagged.map((service) => service.prior_design_message?.trim()).find(Boolean) ??
  defaultPriorDesignMessage(storeName)

/** Texto que identifica el turno para que la tienda encuentre la reserva. */
const designRequestText = (
  confirmation: BookingConfirmation,
  clientName: string,
  when: string | null,
  storeName: string
): string => {
  const name = clientName.trim()
  const services = confirmation.services_label || confirmation.service_name
  const addons = formatAddonsLabel(confirmation.addons)
  return [
    `Hola ${storeName}${name ? `, soy ${name}` : ''}.`,
    `Reservé ${services}${addons ? ` (${addons})` : ''}${when ? ` para el ${when}` : ''} (turno ${confirmation.public_id}).`,
    'Te mando mi diseño para que lo veas antes del turno.'
  ].join('\n')
}

interface BookingPriorDesignProps {
  /** Servicios del turno (principal y sumados), tal como los vio la clienta. */
  services: readonly PriorDesignFields[]
  confirmation: BookingConfirmation
  clientName: string
  /** "viernes 23/10 a las 15:00" en hora argentina, o null si no se puede leer. */
  when: string | null
  storeName: string
  whatsappNumber?: string | null
}

/**
 * Diseño previo (S7): si algun servicio del turno lo pide, la clienta le manda
 * su diseño a la tienda por WhatsApp. El cobro y el estado del turno no
 * cambian; la tienda lo revisa y, si no se puede hacer, cancela desde el panel.
 */
export const BookingPriorDesign: React.FC<BookingPriorDesignProps> = ({
  services,
  confirmation,
  clientName,
  when,
  storeName,
  whatsappNumber
}) => {
  const headingId = useId()
  const flagged = services.filter((service) => service.requires_prior_design === true)
  if (flagged.length === 0) return null

  // null si el WhatsApp de la tienda no se puede leer como numero: sin boton.
  const href = buildWaMeUrl(
    whatsappNumber,
    designRequestText(confirmation, clientName, when, storeName)
  )

  return (
    <section
      aria-labelledby={headingId}
      className="w-full mt-6 rounded-lg p-5 text-left border"
      style={{ background: '#ffffff', borderColor: colors2000s.border.light }}
    >
      <h3
        id={headingId}
        className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-gray-500"
      >
        <PenTool size={14} aria-hidden="true" style={{ color: brandColor.ink }} />
        Diseño previo
      </h3>
      <p className="text-sm font-bold text-gray-700 mt-2 whitespace-pre-line break-words">
        {priorDesignMessage(flagged, storeName)}
      </p>
      {href && <WhatsAppLinkButton href={href}>Enviar mi diseño por WhatsApp</WhatsAppLinkButton>}
    </section>
  )
}
