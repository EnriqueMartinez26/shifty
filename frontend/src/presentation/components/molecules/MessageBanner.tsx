import React from 'react'

import { TriangleAlert } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'

interface MessageBannerProps {
  /** Vacio no renderiza nada: las pantallas guardan '' cuando no hay aviso. */
  message: string
}

/**
 * Aviso del resultado de la ultima accion en las pantallas operativas. Un
 * solo tono para exito y error, como estaba: separarlos cambia lo que ve el
 * dueno y queda fuera de esta extraccion.
 */
export const MessageBanner: React.FC<MessageBannerProps> = ({ message }) => {
  if (!message) return null

  return (
    <div
      role="status"
      className="p-4 rounded-2xl text-sm font-bold flex items-start gap-3"
      style={{
        background: colors2000s.status.warning.bg,
        border: `1px solid ${colors2000s.status.warning.border}`,
        color: colors2000s.status.warning.text
      }}
    >
      <TriangleAlert className="w-5 h-5 flex-shrink-0" />
      <span className="min-w-0 break-words">{message}</span>
    </div>
  )
}
