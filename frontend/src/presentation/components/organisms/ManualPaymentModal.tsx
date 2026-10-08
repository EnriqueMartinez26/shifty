import React, { useState } from 'react'

import { Loader2, TriangleAlert, X } from 'lucide-react'

import { formatArgentinaDateDisplay, formatArgentinaTime } from '@shared/utils/argentinaTime'
import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'

interface ManualPaymentModalProps {
  clientName: string
  serviceName: string
  /** Inicio del turno (ISO): se muestra en hora argentina. */
  startsAt: string
  /** Importe precargado; null si no se conoce y hay que tipearlo. */
  suggestedAmount: number | null
  /** El importe sugerido es la seña que el turno tiene pendiente. */
  isDeposit: boolean
  busy: boolean
  error: string | null
  onSubmit: (amount: number) => void
  onClose: () => void
}

const labelClass = 'text-[10px] font-black uppercase tracking-widest ml-1'

const parseAmount = (value: string): number | null => {
  const amount = Number(value)
  return value.trim() !== '' && Number.isFinite(amount) && amount > 0 ? amount : null
}

/**
 * Confirmar a mano un pago (efectivo, transferencia o seña por WhatsApp).
 *
 * 2026-10-08, QA en el celular (decision de Mateo): "Confirmar pago" registraba
 * al instante, sin confirmar ni pedir importe. Este dialogo muestra el turno
 * y pide el importe; solo pinta y junta el dato: el envio y los errores los
 * resuelve el contenedor. Se monta al abrirse, asi que el estado inicial ya es
 * el del turno a cobrar.
 */
export const ManualPaymentModal: React.FC<ManualPaymentModalProps> = ({
  clientName,
  serviceName,
  startsAt,
  suggestedAmount,
  isDeposit,
  busy,
  error,
  onSubmit,
  onClose
}) => {
  const [value, setValue] = useState(() =>
    suggestedAmount === null ? '' : String(suggestedAmount)
  )
  const amount = parseAmount(value)

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (amount === null || busy) return
    onSubmit(amount)
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-payment-title"
        onKeyDown={handleKeyDown}
        className="relative w-full max-w-md rounded-md shadow-2xl flex flex-col overflow-hidden max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div
          className="p-4 sm:p-6 flex justify-between items-start gap-3"
          style={{ background: colors2000s.bg.disabled }}
        >
          <div>
            <h3
              id="manual-payment-title"
              className="text-xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Confirmar pago
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              {clientName} · {serviceName}
            </p>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              {formatArgentinaDateDisplay(startsAt)} · {formatArgentinaTime(startsAt)} hs
            </p>
          </div>
          <button
            onClick={onClose}
            type="button"
            aria-label="Cerrar"
            className="p-2.5"
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
          {error && (
            <div
              role="alert"
              className="rounded-2xl px-4 py-3 text-xs font-bold flex items-center gap-2"
              style={{ background: '#fff1f2', color: '#be123c' }}
            >
              <TriangleAlert size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}

          {isDeposit && suggestedAmount !== null && (
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Tiene una seña pendiente de {formatCurrency(suggestedAmount)}.
            </p>
          )}

          <div className="space-y-1.5">
            <label
              htmlFor="manual-payment-amount"
              className={labelClass}
              style={{ color: colors2000s.text.secondary }}
            >
              Importe que te pagaron
            </label>
            <input
              id="manual-payment-amount"
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              className="w-full rounded-md px-4 py-3 font-bold outline-none text-sm"
              style={create2000sModalInputStyle()}
              required
            />
          </div>

          <div className="flex gap-4 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 font-black uppercase tracking-widest text-xs"
              style={buttonStyles2000s.default}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={busy || amount === null}
              className="flex-1 font-black py-3 rounded-xl uppercase tracking-widest text-xs disabled:opacity-50 inline-flex items-center justify-center gap-2"
              style={buttonStyles2000s.selected}
            >
              {busy && <Loader2 className="w-4 h-4 animate-spin" />}
              Registrar pago
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
