import React from 'react'

import { ArrowRight } from 'lucide-react'

import { formatCurrency } from '@shared/utils/currency'

import { sumAmounts } from './addonGroups'
import { colors2000s } from '../../../../theme/colors'
import { brandCtaStyle } from '../../../lib/brandTheme'

interface BookingServicesBarProps {
  /** Servicios elegidos (al menos uno: sin nada elegido la barra no se muestra). */
  count: number
  durationMinutes: number
  /**
   * Suma de los precios de lista. El total a cobrar (promo incluida) lo
   * confirma el backend en el ultimo paso.
   */
  listPrice: number
  /** Suma de los adicionales elegidos; entra en el total que se muestra. */
  addonsTotal?: number
  onContinue: () => void
}

/**
 * Barra del paso del servicio: cuantos servicios, cuanto dura y cuanto suman
 * (con los adicionales), con el boton para seguir al horario. Solo pinta.
 */
export const BookingServicesBar: React.FC<BookingServicesBarProps> = ({
  count,
  durationMinutes,
  listPrice,
  addonsTotal = 0,
  onContinue
}) => (
  <div
    className="sticky bottom-0 z-10 mt-4 p-3 sm:p-4 rounded-lg border flex flex-wrap items-center justify-between gap-3"
    style={{
      background: '#ffffff',
      borderColor: colors2000s.border.default,
      boxShadow: `${colors2000s.shadows.insetLight}, 0 -4px 12px rgba(0,0,0,0.08)`
    }}
    data-testid="booking-services-bar"
  >
    <p
      role="status"
      aria-live="polite"
      className="text-sm font-black min-w-0"
      style={{ color: colors2000s.text.primary }}
    >
      {count === 1 ? '1 servicio' : `${count} servicios`} · {durationMinutes} min ·{' '}
      {formatCurrency(sumAmounts(listPrice, addonsTotal))}
    </p>
    <button
      type="button"
      onClick={onContinue}
      className="inline-flex items-center gap-2 px-4 py-3 rounded-xl border text-xs font-black uppercase tracking-widest active:scale-95"
      style={brandCtaStyle}
    >
      Continuar
      <ArrowRight className="w-4 h-4" />
    </button>
  </div>
)
