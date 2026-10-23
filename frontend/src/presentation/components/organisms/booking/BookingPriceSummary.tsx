import React from 'react'

import { formatAddonLabel, type AddonLine } from '@domain/value-objects/AddonSelection'

import { formatCurrency } from '@shared/utils/currency'

import { createBookingAccentBoxStyle } from '../../../lib/surfaceStyles'

/** Un servicio del turno con sus adicionales, para el detalle por servicio. */
interface ServicePriceLine {
  serviceId: string
  name: string
  /** Precio de lista. */
  price: number
  addons: readonly AddonLine[]
}

interface BookingPriceSummaryProps {
  /** Precio de lista del servicio. */
  basePrice: number
  addons: readonly AddonLine[]
  /**
   * Con varios servicios en el turno: una linea por servicio (y sus
   * adicionales) en lugar de `basePrice`/`addons`.
   */
  serviceLines?: readonly ServicePriceLine[]
  /** Descuento del codigo sobre el total (servicio y adicionales), o null. */
  discount: number | null
  promotionCode?: string
  /** Total a cobrar; null mientras el backend no lo confirma. */
  total: number | null
  /** Que decir sin total: "Calculando…" por defecto, "Sin confirmar" ante un error. */
  pendingLabel?: string
}

const rowClass = 'flex justify-between gap-3 text-sm font-bold text-slate-700'

/**
 * Total del turno. El detalle (servicio, adicionales y descuento) aparece solo
 * cuando hay algo que sumar o restar: sin eso "Servicio" repetia el total en
 * el celular (pedido de Mateo, 2026-10-16). Solo pinta.
 */
export const BookingPriceSummary: React.FC<BookingPriceSummaryProps> = ({
  basePrice,
  addons,
  serviceLines,
  discount,
  promotionCode,
  total,
  pendingLabel = 'Calculando…'
}) => {
  const hasDiscount = discount !== null && discount > 0
  const perService = serviceLines !== undefined && serviceLines.length > 1
  const lines: readonly ServicePriceLine[] = perService
    ? serviceLines
    : [{ serviceId: 'principal', name: 'Servicio', price: basePrice, addons }]
  const showBreakdown = perService || addons.length > 0 || hasDiscount
  return (
    <div
      className="p-4 border space-y-2"
      style={createBookingAccentBoxStyle('#f8fafc', '#cbd5e1')}
      data-testid="booking-price-summary"
    >
      {showBreakdown && (
        <>
          {lines.map((service) => (
            <React.Fragment key={service.serviceId}>
              <div className={rowClass}>
                <span className="min-w-0 break-words">{service.name}</span>
                <span>{formatCurrency(service.price)}</span>
              </div>
              {service.addons.map((line) => (
                <div key={line.addonId} className={rowClass}>
                  <span className="min-w-0 break-words">{formatAddonLabel(line)}</span>
                  <span>{formatCurrency(line.amount)}</span>
                </div>
              ))}
            </React.Fragment>
          ))}
          {hasDiscount && (
            <div className={rowClass} data-testid="booking-price-discount">
              <span>Descuento{promotionCode ? ` (${promotionCode})` : ''}</span>
              <span>-{formatCurrency(discount)}</span>
            </div>
          )}
        </>
      )}
      <div
        className={`flex justify-between gap-3 text-base font-black text-slate-900${showBreakdown ? ' pt-2 border-t' : ''}`}
        style={showBreakdown ? { borderColor: '#cbd5e1' } : undefined}
      >
        <span>Total</span>
        <span aria-live="polite" aria-atomic="true">
          {total === null ? pendingLabel : formatCurrency(total)}
        </span>
      </div>
    </div>
  )
}
