import React from 'react'

import { AlertTriangle, MessageCircle, X } from 'lucide-react'

import type {
  AffectedAppointment,
  BlockPreviewResult
} from '@application/services/AppointmentBlocksService'

import { formatArgentinaDateDisplay, formatArgentinaTime } from '@shared/utils/argentinaTime'
import { sanitizePhoneForUrl } from '@shared/utils/safeUrl'

interface BlockPreviewModalProps {
  preview: BlockPreviewResult
  reason: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}

const blockerLabel = (blocker: string | null): string | null => {
  if (blocker === 'pending_payment') return 'Esperando la seña en Mercado Pago: liberalo a mano'
  if (blocker === 'has_deposit') return 'Con seña acreditada: decidí vos qué hacer'
  return null
}

export const buildWhatsAppText = (item: AffectedAppointment, reason: string): string =>
  `Hola ${item.client_name}, te aviso que tu turno de ${item.service_name} del ${formatArgentinaDateDisplay(item.starts_at)} a las ${formatArgentinaTime(item.starts_at)} no lo vamos a poder atender (${reason}). ¿Querés que lo reprogramemos?`

/**
 * Antes de crear un bloqueo con turnos adentro: lista de afectados, aviso por
 * WhatsApp a mano (link wa.me, costo cero) y confirmacion explicita. Es
 * obligatorio porque "cancelado" es terminal: borrar el bloqueo despues no
 * devuelve los turnos.
 */
export const BlockPreviewModal: React.FC<BlockPreviewModalProps> = ({
  preview,
  reason,
  busy,
  onConfirm,
  onCancel
}) => {
  const cancellable = preview.affected.filter((item) => item.cancellable)
  const manual = preview.affected.filter((item) => !item.cancellable)

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="block-preview-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-2xl rounded-3xl bg-white p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-6 h-6 text-amber-500 mt-0.5" />
            <div>
              <h3 id="block-preview-title" className="text-lg font-black uppercase tracking-tight">
                Hay {preview.affected.length} turno{preview.affected.length === 1 ? '' : 's'} dentro
                del bloqueo
              </h3>
              <p className="text-xs font-bold text-gray-500">
                {preview.ranges > 1 ? `${preview.ranges} fechas. ` : ''}
                {cancellable.length > 0
                  ? `Se cancelan ${cancellable.length} y se avisa por mail a quien dejó uno.`
                  : 'Ninguno se cancela solo.'}{' '}
                Cancelar es definitivo: borrar el bloqueo después no los devuelve.
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Cerrar"
            onClick={onCancel}
            className="rounded-full p-1.5 text-gray-500 hover:bg-gray-100"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <ul className="divide-y divide-gray-100 rounded-2xl border border-gray-200">
          {preview.affected.map((item) => {
            const nota = blockerLabel(item.blocker)
            return (
              <li key={item.public_id} className="flex flex-wrap items-center gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-black truncate">{item.client_name || 'Sin nombre'}</p>
                  <p className="text-xs font-bold text-gray-500">
                    {item.service_name} · {item.staff_name} ·{' '}
                    {formatArgentinaDateDisplay(item.starts_at)}{' '}
                    {formatArgentinaTime(item.starts_at)} hs
                  </p>
                  {nota && <p className="text-[11px] font-bold text-amber-700 mt-1">{nota}</p>}
                </div>
                <span className="text-[9px] font-black uppercase tracking-widest text-gray-500">
                  {item.status}
                </span>
                {item.client_phone && (
                  <a
                    href={`https://wa.me/${sanitizePhoneForUrl(item.client_phone)}?text=${encodeURIComponent(buildWhatsAppText(item, reason))}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2 py-1 text-[9px] font-black uppercase tracking-widest text-emerald-700"
                  >
                    <MessageCircle className="w-3 h-3" />
                    Avisar por WhatsApp
                  </a>
                )}
              </li>
            )
          })}
        </ul>

        {manual.length > 0 && (
          <p className="text-xs font-bold text-amber-700">
            {manual.length} turno{manual.length === 1 ? '' : 's'} requiere
            {manual.length === 1 ? '' : 'n'} decisión tuya y no se cancela
            {manual.length === 1 ? '' : 'n'} con el bloqueo.
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-2xl border border-gray-300 px-4 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50"
          >
            Volver
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-2xl bg-red-600 px-4 py-2 text-xs font-black uppercase tracking-widest text-white disabled:opacity-50"
          >
            {cancellable.length > 0
              ? `Cancelar ${cancellable.length} turno${cancellable.length === 1 ? '' : 's'} y bloquear`
              : 'Bloquear igual'}
          </button>
        </div>
      </div>
    </div>
  )
}
