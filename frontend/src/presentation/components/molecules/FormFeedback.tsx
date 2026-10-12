import React from 'react'

import { CircleCheck, TriangleAlert } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'
import { revealOnMount } from '../../lib/revealOnMount'

export interface FormFeedbackMessage {
  tone: 'error' | 'success'
  text: string
}

interface FormFeedbackProps {
  /** null no renderiza nada. */
  feedback: FormFeedbackMessage | null
}

/**
 * Resultado de enviar un formulario, junto al formulario. Un aviso arriba de
 * la pagina quedaba fuera de la vista cuando el formulario estaba abajo (QA
 * 2026-10-02): este se monta al lado del boton y se desplaza hasta quedar
 * visible. Un aviso nuevo (otro texto) se vuelve a montar y a mostrar.
 */
export const FormFeedback: React.FC<FormFeedbackProps> = ({ feedback }) => {
  if (!feedback) return null
  const isError = feedback.tone === 'error'
  const Icon = isError ? TriangleAlert : CircleCheck
  return (
    <div
      key={`${feedback.tone}:${feedback.text}`}
      ref={revealOnMount}
      role={isError ? 'alert' : 'status'}
      className="p-3 rounded-2xl text-sm font-bold flex items-start gap-3"
      style={
        isError
          ? {
              background: colors2000s.status.danger.bg,
              border: `1px solid ${colors2000s.status.danger.border}`,
              color: colors2000s.status.danger.text
            }
          : {
              background: colors2000s.status.success.bg,
              border: `1px solid ${colors2000s.status.success.border}`,
              color: colors2000s.status.success.text
            }
      }
    >
      <Icon className="w-5 h-5 flex-shrink-0" />
      <span className="min-w-0 break-words">{feedback.text}</span>
    </div>
  )
}
