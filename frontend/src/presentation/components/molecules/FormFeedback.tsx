import React from 'react'

import { CircleCheck, TriangleAlert } from 'lucide-react'

export interface FormFeedbackMessage {
  tone: 'error' | 'success'
  text: string
}

interface FormFeedbackProps {
  /** null no renderiza nada. */
  feedback: FormFeedbackMessage | null
}

/**
 * Lleva el aviso a la vista al montarse. Funcion de modulo, estable entre
 * renders: React la llama solo al montar y al desmontar, no en cada tecla.
 * jsdom no implementa scrollIntoView, de ahi el chequeo.
 */
const revealOnMount = (node: HTMLDivElement | null) => {
  if (node && typeof node.scrollIntoView === 'function') {
    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
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
      className="p-3 rounded-2xl text-sm font-bold flex items-center gap-3"
      style={
        isError
          ? { background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c' }
          : { background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#15803d' }
      }
    >
      <Icon className="w-5 h-5 flex-shrink-0" />
      <span>{feedback.text}</span>
    </div>
  )
}
