import React from 'react'

import { Loader2 } from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { create2000sInputStyle } from '../../lib/surfaceStyles'

/** Tope del motivo en `POST /appointments/bulk-cancel`. */
const BULK_CANCEL_REASON_MAX = 200

interface BulkCancelConfirmProps {
  count: number
  reason: string
  onReasonChange: (reason: string) => void
  onConfirm: () => void
  onBack: () => void
  isPending: boolean
}

const reservas = (count: number) => `${count} ${count === 1 ? 'reserva' : 'reservas'}`

/**
 * Paso de confirmacion en la misma pantalla (sin `window.confirm`): dice
 * cuantas se cancelan y que el cliente con email recibe el aviso.
 */
export const BulkCancelConfirm: React.FC<BulkCancelConfirmProps> = ({
  count,
  reason,
  onReasonChange,
  onConfirm,
  onBack,
  isPending
}) => (
  <section
    aria-label="Confirmar cancelación"
    className="p-4 rounded-2xl space-y-3"
    style={{
      background: colors2000s.status.danger.bg,
      border: `1px solid ${colors2000s.status.danger.border}`,
      color: colors2000s.status.danger.text
    }}
  >
    <p className="text-sm font-bold">
      {`Vas a cancelar ${reservas(count)}. A los clientes que dejaron email les va a llegar el aviso de cancelación.`}
    </p>
    <div className="space-y-1">
      <label htmlFor="bulk-cancel-reason" className="text-xs font-black uppercase tracking-widest">
        Motivo (opcional)
      </label>
      <textarea
        id="bulk-cancel-reason"
        value={reason}
        maxLength={BULK_CANCEL_REASON_MAX}
        rows={2}
        onChange={(event) => onReasonChange(event.target.value)}
        className="w-full p-3 rounded-xl text-sm"
        style={create2000sInputStyle()}
      />
      <p className="text-right text-[10px] font-bold">
        {`${reason.length}/${BULK_CANCEL_REASON_MAX}`}
      </p>
    </div>
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <button
        type="button"
        onClick={onBack}
        disabled={isPending}
        className="min-h-11 px-4 rounded-xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
        style={buttonStyles2000s.default}
      >
        Volver
      </button>
      <button
        type="button"
        onClick={onConfirm}
        disabled={isPending}
        className="min-h-11 px-4 rounded-xl inline-flex items-center justify-center gap-2 text-xs font-black uppercase tracking-widest text-white bg-red-700 disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {isPending && <Loader2 className="w-4 h-4 animate-spin" />}
        {isPending ? 'Cancelando…' : `Sí, cancelar ${reservas(count)}`}
      </button>
    </div>
  </section>
)
