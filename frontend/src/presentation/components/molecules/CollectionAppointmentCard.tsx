import React from 'react'

import { CheckCircle2, ExternalLink, Link2 } from 'lucide-react'

import type { AppointmentCharge } from '@domain/value-objects/AppointmentCharge'

import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { bookingStatusLabel } from '../../lib/bookingStatusLabel'
import { formatDateTimeEsAr } from '../../lib/formatters'
import { create2000sListCardStyle } from '../../lib/surfaceStyles'

interface CollectionAppointmentCardProps {
  clientName: string
  serviceName: string
  staffName: string
  startsAt: string
  status: string
  charge: AppointmentCharge
  /** Link de Mercado Pago recien creado para este turno, si hay. */
  latestLink: string | null
  linkBlockedReason: string | null
  confirmBlockedReason: string | null
  onCreateLink: () => void
  onConfirmPayment: () => void
}

const chipClass = 'px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest'

const ChargeSummary: React.FC<{ charge: AppointmentCharge }> = ({ charge }) => {
  if (charge.kind === 'paid') {
    return (
      <div className="flex flex-wrap gap-2 mt-2">
        <span
          className={chipClass}
          style={{
            background: colors2000s.status.success.bg,
            color: colors2000s.status.success.text
          }}
        >
          Pagado {formatCurrency(charge.paid)}
        </span>
        {charge.remaining > 0 && (
          <span
            className={chipClass}
            style={{ background: colors2000s.status.info.bg, color: colors2000s.status.info.text }}
          >
            Resta {formatCurrency(charge.remaining)}
          </span>
        )}
      </div>
    )
  }
  if (charge.kind === 'deposit') {
    return (
      <span
        className={`${chipClass} inline-block mt-2`}
        style={{ background: colors2000s.status.info.bg, color: colors2000s.status.info.text }}
      >
        Seña pendiente {formatCurrency(charge.amount)}
      </span>
    )
  }
  if (charge.kind === 'refunded') {
    return (
      <span
        className={`${chipClass} inline-block mt-2`}
        style={{ background: '#f3f4f6', color: colors2000s.text.secondary }}
      >
        Pago reembolsado
      </span>
    )
  }
  return null
}

/**
 * Un turno en Cobros: datos, estado del cobro y acciones. Solo pinta; el
 * contenedor (`pages/Collections.tsx`) decide y envia.
 *
 * 2026-10-08, QA en el celular: despues de pagar la tarjeta seguia igual
 * (CONFIRMADO y el mismo boton). Un turno pagado muestra lo pagado y lo que
 * resta, y no vuelve a ofrecer cobrar (el backend ignora una segunda
 * confirmacion de un cobro acreditado).
 */
export const CollectionAppointmentCard: React.FC<CollectionAppointmentCardProps> = ({
  clientName,
  serviceName,
  staffName,
  startsAt,
  status,
  charge,
  latestLink,
  linkBlockedReason,
  confirmBlockedReason,
  onCreateLink,
  onConfirmPayment
}) => {
  const canCharge = charge.kind === 'unpaid' || charge.kind === 'deposit'
  return (
    <div
      className="rounded-2xl p-4 bg-white flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4"
      style={create2000sListCardStyle()}
    >
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
            {clientName}
          </p>
          <span
            className={chipClass}
            style={{ background: '#f3f4f6', color: colors2000s.text.secondary }}
          >
            {bookingStatusLabel(status)}
          </span>
        </div>
        <p className="text-[11px] font-bold mt-1" style={{ color: colors2000s.text.secondary }}>
          {serviceName} · {staffName} · {formatDateTimeEsAr(startsAt)}
        </p>
        <ChargeSummary charge={charge} />
      </div>

      {canCharge && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onCreateLink}
            disabled={linkBlockedReason !== null}
            title={linkBlockedReason ?? undefined}
            className="px-4 py-2 text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2 disabled:opacity-50"
            style={buttonStyles2000s.default}
          >
            <Link2 className="w-3.5 h-3.5" />
            Crear link
          </button>
          <button
            type="button"
            onClick={onConfirmPayment}
            disabled={confirmBlockedReason !== null}
            title={confirmBlockedReason ?? undefined}
            className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2 disabled:opacity-50"
            style={buttonStyles2000s.selected}
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
            Confirmar pago
          </button>
          {latestLink && (
            <a
              href={latestLink}
              target="_blank"
              rel="noreferrer"
              className="px-4 py-2 text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
              style={buttonStyles2000s.default}
            >
              Abrir link
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          )}
        </div>
      )}
    </div>
  )
}
