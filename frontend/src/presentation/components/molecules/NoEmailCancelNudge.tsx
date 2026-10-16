import React from 'react'

import { MessageCircle } from 'lucide-react'

interface NoEmailCancelNudgeProps {
  /** wa.me al telefono del cliente con el aviso armado; null sin telefono legible. */
  whatsappHref: string | null
}

/**
 * Despues de cancelar el turno de alguien que reservo sin email (propuesta
 * por Mateo, 2026-10-16): no le llega ningun aviso, asi que se sugiere
 * escribirle por WhatsApp (link wa.me, costo cero; el personal toca y manda).
 */
export const NoEmailCancelNudge: React.FC<NoEmailCancelNudgeProps> = ({ whatsappHref }) => (
  <div
    role="status"
    className="flex flex-wrap items-center gap-3 p-4 rounded-[6px] text-sm font-bold"
    style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#166534' }}
  >
    <span className="flex-1 min-w-0">Este turno no recibe avisos por email.</span>
    {whatsappHref && (
      <a
        href={whatsappHref}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 rounded-lg border border-green-300 bg-white px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-green-700"
      >
        <MessageCircle className="w-3.5 h-3.5" />
        Avisale por WhatsApp
      </a>
    )}
  </div>
)
