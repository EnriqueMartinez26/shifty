import React from 'react'

import { MessageCircle } from 'lucide-react'

import {
  buildClientMessage,
  clientMessageKindFor,
  type ClientMessageInput
} from '@shared/utils/clientWhatsApp'
import { buildWaMeUrl } from '@shared/utils/whatsAppPhone'

interface ClientWhatsAppButtonProps {
  phone: string
  status: string
  message: ClientMessageInput
  compact?: boolean
}

/**
 * "Mandar por WhatsApp" desde la agenda: link wa.me con texto prearmado segun
 * el estado del turno (recordatorio o invitacion a volver). Costo cero, sin
 * API de Meta; el dueno toca y manda.
 */
export const ClientWhatsAppButton: React.FC<ClientWhatsAppButtonProps> = ({
  phone,
  status,
  message,
  compact = false
}) => {
  const kind = clientMessageKindFor(status)
  // Un telefono que no se puede leer como argentino no arma link: wa.me lo
  // mandaria a otro numero.
  const href = kind ? buildWaMeUrl(phone, buildClientMessage(kind, message)) : null
  if (!kind || !href) return null
  const label = kind === 'rebook' ? 'Invitar a volver' : 'Recordar por WhatsApp'
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={label}
      aria-label={label}
      onClick={(event) => event.stopPropagation()}
      className={`inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-[9px] font-black uppercase tracking-widest border text-green-700 border-green-200 ${compact ? 'mt-1' : 'mt-2'}`}
    >
      <MessageCircle className="w-3 h-3" />
      {compact ? null : label}
    </a>
  )
}
