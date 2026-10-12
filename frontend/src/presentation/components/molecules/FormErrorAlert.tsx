import React from 'react'

import { TriangleAlert } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'
import { revealOnMount } from '../../lib/revealOnMount'

interface FormErrorAlertProps {
  /** Vacio o null no renderiza nada. */
  message: string | null | undefined
  className?: string
}

/**
 * Error de un formulario en un modal: se desplaza hasta quedar visible y toma
 * el foco al aparecer. En un telefono el formulario scrolleado dejaba el aviso
 * arriba, fuera de la vista, y parecia que el boton no hacia nada (QA movil
 * 2026-10-08: el 409 del alta de turno a top=-84px). Un texto nuevo se vuelve a
 * montar (`key`) y se vuelve a mostrar.
 */
export const FormErrorAlert: React.FC<FormErrorAlertProps> = ({ message, className = '' }) => {
  if (!message) return null
  return (
    <div
      key={message}
      ref={revealOnMount}
      role="alert"
      tabIndex={-1}
      className={`rounded-2xl px-4 py-3 text-xs font-bold flex items-start gap-2 scroll-my-4 ${className}`}
      style={{
        background: colors2000s.status.danger.bg,
        border: `1px solid ${colors2000s.status.danger.border}`,
        color: colors2000s.status.danger.text
      }}
    >
      <TriangleAlert size={14} className="flex-shrink-0" aria-hidden="true" />
      <span className="min-w-0 break-words">{message}</span>
    </div>
  )
}
