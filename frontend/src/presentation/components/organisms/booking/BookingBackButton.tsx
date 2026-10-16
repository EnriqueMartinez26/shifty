import React from 'react'

import { ArrowLeft } from 'lucide-react'

import { createBookingBackButtonStyle } from '../../../lib/surfaceStyles'

interface BookingBackButtonProps {
  onBack: () => void
}

/**
 * "Volver" de cada paso del portal, con texto visible. 2026-10-16 (pedido de
 * Mateo): era un circulo naranja con un chevron solo y los clientes no lo veian.
 * El nombre accesible sale del texto; el icono es decorativo.
 */
export const BookingBackButton: React.FC<BookingBackButtonProps> = ({ onBack }) => (
  <button
    type="button"
    onClick={onBack}
    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md border text-xs font-black uppercase tracking-widest transition-all active:scale-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
    style={createBookingBackButtonStyle()}
  >
    <ArrowLeft size={16} aria-hidden="true" className="stroke-[3px]" />
    <span>Volver</span>
  </button>
)
