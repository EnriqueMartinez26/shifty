import React from 'react'

import type { LedgerMovement } from '@application/services/LedgerService'

import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { formatDateEsAr, formatDateTimeEsAr } from '../../lib/formatters'
import { create2000sListCardStyle } from '../../lib/surfaceStyles'

export const movementTypeLabels: Record<LedgerMovement['movement_type'], string> = {
  charge: 'Cargo',
  payment: 'Pago',
  adjustment: 'Ajuste',
  refund: 'Devolución'
}

const isReversal = (movement: LedgerMovement): boolean => Boolean(movement.reverses_id)

/** Un movimiento que no es reversion y que nadie anulo todavia. */
const isReversible = (movement: LedgerMovement): boolean =>
  !movement.reversed && !isReversal(movement)

interface LedgerMovementItemProps {
  movement: LedgerMovement
  /** El movimiento que esta reversion anula, si esta en las paginas cargadas. */
  original?: LedgerMovement
  onReverse: (movement: LedgerMovement) => void
  /** Tienda suspendida o una reversa en curso. */
  reverseDisabled: boolean
  reverseDisabledReason?: string
}

const titleOf = (movement: LedgerMovement, original: LedgerMovement | undefined): string => {
  if (!isReversal(movement)) return movementTypeLabels[movement.movement_type]
  return original
    ? `Reversión de ${movementTypeLabels[original.movement_type]} del ${formatDateEsAr(original.created_at)}`
    : 'Reversión de un movimiento anterior'
}

/**
 * Una fila del estado de cuenta del fiado. Solo render: la confirmacion y la
 * llamada las hace la pantalla (contenedor).
 */
export const LedgerMovementItem: React.FC<LedgerMovementItemProps> = ({
  movement,
  original,
  onReverse,
  reverseDisabled,
  reverseDisabledReason
}) => {
  // La nota de una reversion la escribe el servidor con el id interno.
  const notes = isReversal(movement) ? null : movement.notes
  return (
    <div
      data-testid="ledger-movement"
      className="rounded-2xl p-4 bg-white flex flex-col md:flex-row md:items-center md:justify-between gap-3"
      style={create2000sListCardStyle()}
    >
      <div>
        <p className="text-sm font-black uppercase" style={{ color: colors2000s.text.primary }}>
          {titleOf(movement, original)}
        </p>
        <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
          {formatDateTimeEsAr(movement.created_at)}
          {notes ? ` · ${notes}` : ''}
        </p>
        {movement.reversed && (
          <span
            className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-widest"
            style={{ background: '#f3f4f6', color: colors2000s.text.secondary }}
          >
            Revertido
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 md:justify-end">
        <div className="text-right">
          <p
            className="text-sm font-black"
            style={{
              color: colors2000s.orange.accent,
              textDecoration: movement.reversed ? 'line-through' : undefined
            }}
          >
            {formatCurrency(Number(movement.amount))}
          </p>
          <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
            Saldo: {formatCurrency(Number(movement.balance_after))}
          </p>
        </div>
        {isReversible(movement) && (
          <button
            type="button"
            onClick={() => onReverse(movement)}
            disabled={reverseDisabled}
            title={reverseDisabled ? reverseDisabledReason : undefined}
            className="px-3 py-2 rounded-2xl text-[11px] font-black uppercase disabled:opacity-50"
            style={buttonStyles2000s.default}
          >
            Revertir
          </button>
        )}
      </div>
    </div>
  )
}
