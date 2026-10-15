import React from 'react'

import { formatAddonLabel, type AddonLine } from '@domain/value-objects/AddonSelection'

import { formatCurrency } from '@shared/utils/currency'

import { createBookingAccentBoxStyle } from '../../../lib/surfaceStyles'

interface BookingPriceSummaryProps {
  /** Precio del servicio, con la promo aplicada si hay. */
  basePrice: number
  addons: readonly AddonLine[]
  total: number
}

/** Servicio, adicionales y total del turno. Solo pinta. */
export const BookingPriceSummary: React.FC<BookingPriceSummaryProps> = ({
  basePrice,
  addons,
  total
}) => (
  <div
    className="p-4 border space-y-2"
    style={createBookingAccentBoxStyle('#f8fafc', '#cbd5e1')}
    data-testid="booking-price-summary"
  >
    <div className="flex justify-between gap-3 text-sm font-bold text-slate-700">
      <span>Servicio</span>
      <span>{formatCurrency(basePrice)}</span>
    </div>
    {addons.map((line) => (
      <div
        key={line.addonId}
        className="flex justify-between gap-3 text-sm font-bold text-slate-700"
      >
        <span className="min-w-0 break-words">{formatAddonLabel(line)}</span>
        <span>{formatCurrency(line.amount)}</span>
      </div>
    ))}
    <div
      className="flex justify-between gap-3 pt-2 border-t text-base font-black text-slate-900"
      style={{ borderColor: '#cbd5e1' }}
    >
      <span>Total</span>
      <span>{formatCurrency(total)}</span>
    </div>
  </div>
)
