import React from 'react'

import { TriangleAlert } from 'lucide-react'

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
      className="p-4 rounded-2xl text-sm font-bold flex items-center gap-3"
      style={{ background: '#fff7ed', border: '1px solid #fed7aa', color: '#c2410c' }}
    >
      <TriangleAlert className="w-5 h-5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  )
}
