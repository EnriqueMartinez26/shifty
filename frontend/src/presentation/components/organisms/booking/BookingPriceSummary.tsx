import React from 'react'

import { formatAddonLabel, type AddonLine } from '@domain/value-objects/AddonSelection'

import { formatCurrency } from '@shared/utils/currency'

import { createBookingAccentBoxStyle } from '../../../lib/surfaceStyles'

interface BookingPriceSummaryProps {
  /** Precio de lista del servicio. */
  basePrice: number
  addons: readonly AddonLine[]
  /** Descuento del codigo sobre el total (servicio y adicionales), o null. */
  discount: number | null
  promotionCode?: string
  /** Total a cobrar; null mientras el backend no lo confirma. */
  total: number | null
  /** Que decir sin total: "Calculando…" por defecto, "Sin confirmar" ante un error. */
  pendingLabel?: string
}

const rowClass = 'flex justify-between gap-3 text-sm font-bold text-slate-700'

/** Servicio, adicionales, descuento y total del turno. Solo pinta. */
export const BookingPriceSummary: React.FC<BookingPriceSummaryProps> = ({
  basePrice,
  addons,
  discount,
  promotionCode,
  total,
  pendingLabel = 'Calculando…'
}) => (
  <div
    className="p-4 border space-y-2"
    style={createBookingAccentBoxStyle('#f8fafc', '#cbd5e1')}
    data-testid="booking-price-summary"
  >
    <div className={rowClass}>
      <span>Servicio</span>
      <span>{formatCurrency(basePrice)}</span>
    </div>
    {addons.map((line) => (
      <div key={line.addonId} className={rowClass}>
        <span className="min-w-0 break-words">{formatAddonLabel(line)}</span>
        <span>{formatCurrency(line.amount)}</span>
      </div>
    ))}
    {discount !== null && discount > 0 && (
      <div className={rowClass} data-testid="booking-price-discount">
        <span>Descuento{promotionCode ? ` (${promotionCode})` : ''}</span>
        <span>-{formatCurrency(discount)}</span>
      </div>
    )}
    <div
      className="flex justify-between gap-3 pt-2 border-t text-base font-black text-slate-900"
      style={{ borderColor: '#cbd5e1' }}
    >
      <span>Total</span>
      <span>{total === null ? pendingLabel : formatCurrency(total)}</span>
    </div>
  </div>
)
