import React, { useId } from 'react'

import { Minus, Plus, Sparkles } from 'lucide-react'

import type { AddonOption } from '@domain/value-objects/AddonSelection'

import { formatCurrency } from '@shared/utils/currency'

import { colors2000s } from '../../../../theme/colors'
import { brandColor } from '../../../lib/brandTheme'
import { createBookingAccentBoxStyle } from '../../../lib/surfaceStyles'

interface BookingAddonsPickerProps {
  addons: readonly AddonOption[]
  /** Cantidad elegida por id; un id ausente es 0. */
  quantities: Readonly<Record<string, number>>
  onChange: (addonId: string, quantity: number) => void
  disabled?: boolean
  /** Encabezado; con varios servicios nombra el servicio ("Adicionales de Corte"). */
  title?: string
  /** Id del bloque, para que el servicio que lo abre lo apunte (`aria-controls`). */
  id?: string
}

const stepperButtonStyle: React.CSSProperties = {
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
  color: colors2000s.text.primary
}

/**
 * Adicionales del servicio con un contador de 0 al maximo de cada uno. Solo
 * pinta: las cantidades y el total los lleva quien lo usa. Un adicional suma
 * precio, nunca tiempo.
 */
export const BookingAddonsPicker: React.FC<BookingAddonsPickerProps> = ({
  addons,
  quantities,
  onChange,
  disabled = false,
  title = 'Adicionales',
  id
}) => {
  // Un id por bloque: con varios servicios hay un picker por servicio.
  const titleId = useId()
  if (addons.length === 0) return null
  return (
    <section
      id={id}
      className="p-4 border space-y-3"
      style={createBookingAccentBoxStyle('#ffffff', '#e5e7eb')}
      aria-labelledby={titleId}
    >
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4" style={{ color: brandColor.ink }} />
        <h3 id={titleId} className="text-[10px] font-black uppercase tracking-widest text-gray-400">
          {title}
        </h3>
      </div>
      <p className="text-xs font-bold text-gray-500">
        Sumá lo que quieras a tu turno. Se suma al total y no cambia la duración.
      </p>
      <ul className="space-y-2">
        {addons.map((addon) => {
          const quantity = quantities[addon.id] ?? 0
          return (
            <li
              key={addon.id}
              className="flex flex-wrap items-center justify-between gap-3 py-2 border-t first:border-t-0"
              style={{ borderColor: '#f3f4f6' }}
            >
              <div className="min-w-0">
                <p className="text-sm font-black text-gray-800 break-words">{addon.name}</p>
                <p className="text-[11px] font-bold text-gray-500">
                  {formatCurrency(addon.unitPrice)} c/u · hasta {addon.maxQuantity}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label={`Quitar uno de ${addon.name}`}
                  disabled={disabled || quantity <= 0}
                  onClick={() => onChange(addon.id, quantity - 1)}
                  className="w-11 h-11 rounded-full flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
                  style={stepperButtonStyle}
                >
                  <Minus className="w-4 h-4" />
                </button>
                <output
                  aria-live="polite"
                  aria-label={`Cantidad de ${addon.name}`}
                  className="w-6 text-center text-sm font-black text-gray-800"
                >
                  {quantity}
                </output>
                <button
                  type="button"
                  aria-label={`Agregar uno de ${addon.name}`}
                  disabled={disabled || quantity >= addon.maxQuantity}
                  onClick={() => onChange(addon.id, quantity + 1)}
                  className="w-11 h-11 rounded-full flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
                  style={stepperButtonStyle}
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
