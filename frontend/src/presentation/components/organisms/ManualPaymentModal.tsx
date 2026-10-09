import React, { useState } from 'react'

import { Loader2, TriangleAlert, X } from 'lucide-react'

import {
  REMAINDER_PAYMENT_METHODS,
  fitsRemaining,
  type RemainderPaymentMethod
} from '@domain/value-objects/AppointmentCharge'

import { formatAmountInput, parseAmountInput } from '@shared/utils/amountInput'
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
  /**
   * `remainder`: registra el resto de un turno ya señado (D-20261008-01). Pide
   * el medio de pago y no deja pasarse de `maxAmount` (lo que resta).
   */
  mode?: 'payment' | 'remainder'
  maxAmount?: number | null
  busy: boolean
  error: string | null
  /** En modo `remainder` llega tambien el medio elegido (o null). */
  onSubmit: (amount: number, method?: RemainderPaymentMethod | null) => void
  onClose: () => void
}

const labelClass = 'text-[10px] font-black uppercase tracking-widest ml-1'

const METHOD_LABELS: Record<RemainderPaymentMethod, string> = {
  efectivo: 'Efectivo',
  transferencia: 'Transferencia',
  mercadopago: 'Mercado Pago',
  otro: 'Otro'
}

const isRemainderMethod = (value: string): value is RemainderPaymentMethod =>
  (REMAINDER_PAYMENT_METHODS as readonly string[]).includes(value)

/**
 * Confirmar a mano un pago (efectivo, transferencia o seña por WhatsApp).
 *
 * 2026-10-08, QA en el celular (decision de Mateo): "Confirmar pago" registraba
 * al instante, sin confirmar ni pedir importe. Este dialogo muestra el turno
 * y pide el importe; solo pinta y junta el dato: el envio y los errores los
 * resuelve el contenedor. Se monta al abrirse, asi que el estado inicial ya es
 * el del turno a cobrar.
 *
 * Saldo restante por turno (D-20261008-01): en modo `remainder` registra el
 * resto que el cliente paga en el local despues de la seña.
 */
export const ManualPaymentModal: React.FC<ManualPaymentModalProps> = ({
  clientName,
  serviceName,
  startsAt,
  suggestedAmount,
  isDeposit,
  mode = 'payment',
  maxAmount = null,
  busy,
  error,
  onSubmit,
  onClose
}) => {
  const [value, setValue] = useState(() =>
    suggestedAmount === null ? '' : formatAmountInput(suggestedAmount)
  )
  // Formato es-AR ("3.200,50"): un `type="number"` leia "3.200" como 3,2
  // (revision de la PR #131, W4). El campo vacio solo deshabilita el boton.
  const [method, setMethod] = useState('')
  const isRemainder = mode === 'remainder'
  const parsed = parseAmountInput(value)
  const exceeds =
    isRemainder && parsed.ok && maxAmount !== null && !fitsRemaining(parsed.value, maxAmount)
  const amount = parsed.ok && !exceeds ? parsed.value : null
  const amountError = exceeds
    ? `El importe supera lo que resta (${formatCurrency(maxAmount ?? 0)}).`
    : !parsed.ok && value.trim() !== ''
      ? parsed.error
      : null
  const title = isRemainder ? 'Registrar resto' : 'Confirmar pago'

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (amount === null || busy) return
    if (isRemainder) {
      onSubmit(amount, isRemainderMethod(method) ? method : null)
      return
    }
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
              {title}
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

          {isRemainder && maxAmount !== null && (
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Resta {formatCurrency(maxAmount)} para completar el precio del turno. El resto salda
              lo que falta del precio; no es fiado: si una parte quedó en el fiado, no la registres
              también como resto.
            </p>
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
              {isRemainder ? 'Importe del resto' : 'Importe que te pagaron'}
            </label>
            <input
              id="manual-payment-amount"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              placeholder="3.200,50"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              aria-invalid={amountError !== null}
              aria-describedby={amountError ? 'manual-payment-amount-error' : undefined}
              className="w-full rounded-md px-4 py-3 font-bold outline-none text-sm"
              style={create2000sModalInputStyle()}
              required
            />
            {amountError && (
              <p
                id="manual-payment-amount-error"
                className="text-xs font-bold ml-1"
                style={{ color: '#be123c' }}
              >
                {amountError}
              </p>
            )}
          </div>

          {isRemainder && (
            <div className="space-y-1.5">
              <label
                htmlFor="manual-payment-method"
                className={labelClass}
                style={{ color: colors2000s.text.secondary }}
              >
                Medio de pago (opcional)
              </label>
              <select
                id="manual-payment-method"
                value={method}
                onChange={(event) => setMethod(event.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-sm"
                style={create2000sModalInputStyle()}
              >
                <option value="">Sin especificar</option>
                {REMAINDER_PAYMENT_METHODS.map((option) => (
                  <option key={option} value={option}>
                    {METHOD_LABELS[option]}
                  </option>
                ))}
              </select>
            </div>
          )}

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
              {isRemainder ? 'Registrar resto' : 'Registrar pago'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
