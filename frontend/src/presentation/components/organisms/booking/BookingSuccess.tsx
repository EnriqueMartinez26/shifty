import React from 'react'

import { Calendar, Check, Clock, ExternalLink } from 'lucide-react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { asSafeHttpsUrl, sanitizePhoneForUrl } from '@shared/utils/safeUrl'

import type { BookingWizardState } from './types'
import { colors2000s } from '../../../../theme/colors'
import { currencyFmtEsAr as currencyFmt } from '../../../lib/formatters'

interface BookingSuccessProps {
  confirmation: BookingConfirmation
  bookingState: BookingWizardState
  /** Slug de la tienda: link a "mis turnos". */
  storeSlug?: string
  storeName: string
  whatsappNumber?: string | null
}

/** Pantalla de exito de la reserva; BookingStepConfirmation decide cuando se muestra. */
export const BookingSuccess: React.FC<BookingSuccessProps> = ({
  confirmation,
  bookingState,
  storeSlug,
  storeName,
  whatsappNumber
}) => {
  const whatsappPhone = (whatsappNumber || '').replace(/\D/g, '')
  const isPendingPayment = confirmation.status === 'pending_payment'
  const isPendingReview = confirmation.status === 'pending'
  const title = isPendingPayment
    ? 'Reserva Pendiente de Pago'
    : isPendingReview
      ? 'Reserva Registrada'
      : 'Reserva Confirmada'
  const subtitle = confirmation.payment_required
    ? 'Tu turno se confirma cuando el cobro quede aprobado.'
    : isPendingReview
      ? 'Tu solicitud ya fue enviada y queda pendiente de confirmacion.'
      : bookingState.client.email
        ? `Te enviamos los detalles a ${bookingState.client.email}`
        : 'Tu reserva ya quedo registrada.'

  return (
    <div className="flex flex-col items-center py-10 text-center duration-500">
      <div className="relative mb-8">
        <div
          className={`absolute inset-0 rounded-full blur-xl opacity-20 animate-pulse ${isPendingPayment || isPendingReview ? 'bg-amber-500' : 'bg-green-500'}`}
        />
        <div
          className="w-24 h-24 rounded-full flex items-center justify-center text-white shadow-2xl relative z-10 border-4 border-white"
          style={{
            background:
              isPendingPayment || isPendingReview
                ? `linear-gradient(135deg, ${colors2000s.status.warning.light} 0%, ${colors2000s.status.warning.dark} 100%)`
                : `linear-gradient(135deg, ${colors2000s.status.success.light} 0%, ${colors2000s.status.success.dark} 100%)`,
            boxShadow:
              isPendingPayment || isPendingReview
                ? 'inset 0 2px 4px rgba(255,255,255,0.4), 0 4px 12px rgba(217,119,6,0.3)'
                : 'inset 0 2px 4px rgba(255,255,255,0.4), 0 4px 12px rgba(22,163,74,0.3)'
          }}
        >
          <Check className="w-12 h-12 stroke-[3px]" />
        </div>
      </div>

      <h2
        className="text-3xl font-black uppercase tracking-tight leading-none mb-2"
        style={{ color: colors2000s.orange.accent }}
      >
        {title}
      </h2>
      <p className="text-sm font-bold text-gray-500 mb-10">{subtitle}</p>

      <div
        className="w-full rounded-lg p-6 text-left border"
        style={{
          background: '#ffffff',
          borderColor: colors2000s.border.light,
          boxShadow: colors2000s.shadows.insetDark
        }}
      >
        <h3 className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-4 ml-1">
          Detalles del Turno
        </h3>

        <div className="grid gap-4">
          <div className="flex items-center gap-3">
            <div
              className="p-2.5 rounded-md text-orange-500"
              style={{
                background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
              }}
            >
              <Calendar size={18} className="stroke-[2.5px]" />
            </div>
            <div>
              <p className="text-[9px] font-black uppercase tracking-wider text-gray-400">
                Fecha del turno
              </p>
              <p className="font-black text-gray-700 text-lg leading-tight">{bookingState.date}</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div
              className="p-2.5 rounded-md text-blue-500"
              style={{
                background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
              }}
            >
              <Clock size={18} className="stroke-[2.5px]" />
            </div>
            <div>
              <p className="text-[9px] font-black uppercase tracking-wider text-gray-400">
                Hora de inicio
              </p>
              <p className="font-black text-gray-700 text-lg leading-tight">
                {bookingState.startTime} hs
              </p>
            </div>
          </div>

          {(confirmation.service_price || confirmation.final_price) && (
            <div
              className="rounded-md p-4 border"
              style={{ background: '#f8fafc', borderColor: '#cbd5e1' }}
            >
              <p className="text-[10px] font-black uppercase tracking-widest text-slate-600 mb-1">
                Resumen comercial
              </p>
              <div className="space-y-1 text-sm font-black text-slate-900">
                <p>Servicio: {currencyFmt.format(Number(confirmation.service_price || 0))}</p>
                {(confirmation.discount_amount || 0) > 0 && (
                  <p>Descuento: -{currencyFmt.format(Number(confirmation.discount_amount || 0))}</p>
                )}
                <p>
                  Total final:{' '}
                  {currencyFmt.format(
                    Number(confirmation.final_price || confirmation.service_price || 0)
                  )}
                </p>
              </div>
            </div>
          )}

          {confirmation.payment_required && (
            <div
              className="rounded-md p-4 border"
              style={{ background: '#fff7ed', borderColor: '#fed7aa' }}
            >
              <p className="text-[10px] font-black uppercase tracking-widest text-amber-700 mb-1">
                Pago requerido
              </p>
              <p className="text-sm font-black text-amber-900">
                {confirmation.payment_amount
                  ? currencyFmt.format(Number(confirmation.payment_amount))
                  : 'Importe a confirmar'}
              </p>
              <p className="text-xs font-bold text-amber-800 mt-2">
                Estado: {confirmation.payment_status || 'pendiente'}
              </p>
            </div>
          )}
        </div>
      </div>

      {confirmation.payment_link && (
        <a
          href={asSafeHttpsUrl(confirmation.payment_link) ?? '#'}
          target="_blank"
          rel="noreferrer"
          className="w-full mt-6 text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs border cursor-pointer select-none inline-flex items-center justify-center gap-2"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
            borderColor: colors2000s.orange.accent,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
          }}
        >
          Ir a pagar
          <ExternalLink className="w-4 h-4" />
        </a>
      )}

      {whatsappPhone && !confirmation.payment_link && (
        <a
          href={`https://wa.me/${sanitizePhoneForUrl(whatsappPhone)}?text=${encodeURIComponent(
            `Hola ${storeName}, reservé el turno ${confirmation.public_id ?? ''} para el ${bookingState.date} a las ${bookingState.startTime}. Quiero coordinar el pago.`
          )}`}
          target="_blank"
          rel="noreferrer"
          className="w-full mt-6 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs border cursor-pointer select-none inline-flex items-center justify-center gap-2"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            color: colors2000s.orange.accent,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
          }}
        >
          Coordinar el pago por WhatsApp
          <ExternalLink className="w-4 h-4" />
        </a>
      )}

      {storeSlug && (
        <a
          href={`/b/${storeSlug}/mis-turnos`}
          className="w-full mt-4 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs border cursor-pointer select-none inline-flex items-center justify-center gap-2"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            color: colors2000s.text.primary,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
          }}
        >
          Quiero cambiar o cancelar mi turno
        </a>
      )}

      <button
        onClick={() => window.location.reload()}
        className="w-full mt-4 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          borderColor: colors2000s.border.default,
          color: colors2000s.text.primary,
          boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
        }}
      >
        Hacer otra reserva
      </button>
    </div>
  )
}
