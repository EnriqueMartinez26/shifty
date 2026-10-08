import React from 'react'

import { TriangleAlert } from 'lucide-react'

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
      className={`rounded-2xl px-4 py-3 text-xs font-bold flex items-center gap-2 outline-none scroll-my-4 ${className}`}
      style={{ background: '#fff1f2', border: '1px solid #fecdd3', color: '#be123c' }}
    >
      <TriangleAlert size={14} className="flex-shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </div>
  )
}
