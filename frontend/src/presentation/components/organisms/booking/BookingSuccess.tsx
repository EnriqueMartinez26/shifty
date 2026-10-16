import React from 'react'

import { Briefcase, Calendar, Check, Clock, ExternalLink } from 'lucide-react'

import { formatAddonLabel } from '@domain/value-objects/AddonSelection'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import {
  formatArgentinaDateDisplay,
  formatArgentinaDayHeading,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'
import { formatCurrency } from '@shared/utils/currency'
import { asSafeHttpsUrl } from '@shared/utils/safeUrl'
import { buildWaMeUrl } from '@shared/utils/whatsAppPhone'

import { BookingNoEmailActions, bookedSummary } from './BookingNoEmailActions'
import type { BookingWizardState } from './types'
import { colors2000s, orangeCtaGradient } from '../../../../theme/colors'

// Estado del cobro en castellano: el cliente leia "Estado: pending".
const PAYMENT_STATUS_LABELS: Record<string, string> = {
  pending: 'pendiente',
  approved: 'aprobado',
  rejected: 'rechazado',
  expired: 'vencido',
  manual_confirmed: 'confirmado',
  refunded: 'devuelto'
}

const paymentStatusLabel = (status: string | null | undefined): string =>
  status ? (PAYMENT_STATUS_LABELS[status] ?? status) : 'pendiente'

/** "sábado 12/10 a las 15:00" en hora argentina, o null si no hay plazo. */
const deadlineLabel = (deadline: string | null | undefined): string | null => {
  if (!deadline) return null
  const day = formatArgentinaDayHeading(deadline)
  const time = formatArgentinaTime(deadline)
  return day && time ? `${day} a las ${time}` : null
}

interface ServicePriceLine {
  key: string
  label: string
  amount: number
}

const toCents = (value: number): number => Math.round(value * 100)

/**
 * Las lineas de servicios del resumen comercial, para que con el descuento y
 * los adicionales sumen el total (revision de #194). `service_price` es solo
 * el principal: con varios servicios va una linea por servicio si la
 * respuesta trae el precio de cada uno, o una sola con la suma si trae
 * `extra_services_amount`. Sin ninguno de los dos (backend anterior) no se
 * muestra un importe que no cierre: queda solo el total.
 */
const servicePriceLines = (confirmation: BookingConfirmation): ServicePriceLine[] => {
  const principal = Number(confirmation.service_price || 0)
  const extras = confirmation.extra_services ?? []
  if (extras.length === 0) return [{ key: 'servicio', label: 'Servicio', amount: principal }]
  if (extras.every((extra) => extra.price !== undefined && extra.price !== null)) {
    return [
      { key: confirmation.service_id, label: confirmation.service_name, amount: principal },
      ...extras.map((extra) => ({
        key: extra.public_id,
        label: extra.name,
        amount: Number(extra.price)
      }))
    ]
  }
  if (
    confirmation.extra_services_amount !== undefined &&
    confirmation.extra_services_amount !== null
  ) {
    const label = confirmation.services_label || confirmation.service_name
    return [
      {
        key: 'servicios',
        label: `Servicios (${label})`,
        amount: (toCents(principal) + toCents(Number(confirmation.extra_services_amount))) / 100
      }
    ]
  }
  return []
}

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
  // Seña obligatoria que se paga por WhatsApp (decision de Mateo, 2026-10-03):
  // el canal viene explicito en la respuesta (antes se inferia de la falta de
  // link). La tienda la confirma a mano cuando le pagan, hasta el plazo.
  const isWhatsappDeposit = confirmation.deposit_channel === 'whatsapp'
  const whatsappDeadline = isWhatsappDeposit ? deadlineLabel(confirmation.deposit_deadline) : null
  const depositLabel = confirmation.payment_amount
    ? formatCurrency(Number(confirmation.payment_amount))
    : null
  const paymentRequest =
    isWhatsappDeposit && depositLabel
      ? `Quiero pagar la seña de ${depositLabel}.`
      : 'Quiero coordinar el pago.'
  // null si el WhatsApp de la tienda no se puede leer como numero: sin boton.
  const whatsappHref = buildWaMeUrl(
    whatsappNumber,
    `Hola ${storeName}, reservé el turno ${confirmation.public_id ?? ''} para el ${formatArgentinaDateDisplay(bookingState.date ?? '')} a las ${bookingState.startTime}. ${paymentRequest}`
  )
  const isPendingPayment = confirmation.status === 'pending_payment'
  const isPendingReview = confirmation.status === 'pending'
  // Sin email (propuesta por Mateo, 2026-10-16): no hay avisos ni "Mis
  // turnos". La pantalla dice cuando es el turno y ofrece calendario y
  // WhatsApp; los flujos de seña no cambian.
  const withoutEmail = !bookingState.client.email.trim()
  const emailTitle = isPendingPayment
    ? 'Reserva Pendiente de Pago'
    : isPendingReview
      ? 'Reserva Registrada'
      : 'Reserva Confirmada'
  const title = withoutEmail
    ? isPendingPayment || isPendingReview
      ? 'Reserva registrada'
      : 'Turno reservado'
    : emailTitle
  const subtitle = isWhatsappDeposit
    ? `Pagá la seña por WhatsApp: tu turno se confirma cuando ${storeName} reciba el pago.`
    : confirmation.payment_required
      ? 'Tu turno se confirma cuando el cobro quede aprobado.'
      : isPendingReview
        ? 'Tu solicitud ya fue enviada y queda pendiente de confirmación.'
        : withoutEmail
          ? null
          : `Te enviamos los detalles a ${bookingState.client.email}`

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
      {withoutEmail && (
        <p className={`text-sm font-black text-gray-700 ${subtitle ? 'mb-2' : 'mb-10'}`}>
          {bookedSummary(confirmation)}
        </p>
      )}
      {subtitle && <p className="text-sm font-bold text-gray-500 mb-10">{subtitle}</p>}

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
              <p className="font-black text-gray-700 text-lg leading-tight">
                {formatArgentinaDateDisplay(bookingState.date ?? '')}
              </p>
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

          {/* "Corte + Barba" con varios servicios; una respuesta vieja trae solo el principal. */}
          {(confirmation.services_label || confirmation.service_name) && (
            <div className="flex items-center gap-3">
              <div
                className="p-2.5 rounded-md text-orange-500"
                style={{
                  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
                }}
              >
                <Briefcase size={18} className="stroke-[2.5px]" />
              </div>
              <div className="min-w-0">
                <p className="text-[9px] font-black uppercase tracking-wider text-gray-400">
                  {confirmation.extra_services?.length ? 'Servicios' : 'Servicio'}
                </p>
                <p className="font-black text-gray-700 text-lg leading-tight break-words">
                  {confirmation.services_label || confirmation.service_name}
                </p>
              </div>
            </div>
          )}

          {(confirmation.service_price || confirmation.final_price) && (
            <div
              className="rounded-md p-4 border"
              style={{ background: '#f8fafc', borderColor: '#cbd5e1' }}
            >
              <p className="text-[10px] font-black uppercase tracking-widest text-slate-600 mb-1">
                Resumen comercial
              </p>
              <div className="space-y-1 text-sm font-black text-slate-900">
                {servicePriceLines(confirmation).map((line) => (
                  <p key={line.key}>
                    {line.label}: {formatCurrency(line.amount)}
                  </p>
                ))}
                {(confirmation.discount_amount || 0) > 0 && (
                  <p>Descuento: -{formatCurrency(Number(confirmation.discount_amount || 0))}</p>
                )}
                {/* Precio congelado al reservar: el de la respuesta, no el del catalogo. */}
                {(confirmation.addons ?? []).map((addon) => (
                  <p key={addon.addon_id}>
                    {formatAddonLabel(addon)}: {formatCurrency(Number(addon.amount))}
                  </p>
                ))}
                <p>
                  Total final:{' '}
                  {formatCurrency(
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
                {isWhatsappDeposit ? 'Seña a pagar por WhatsApp' : 'Pago requerido'}
              </p>
              <p className="text-sm font-black text-amber-900">
                {depositLabel ?? 'Importe a confirmar'}
              </p>
              {whatsappDeadline && (
                <p className="text-sm font-bold text-amber-900 mt-2">
                  Tenés hasta el {whatsappDeadline} para pagar la seña por WhatsApp. Si no, el turno
                  se libera.
                </p>
              )}
              <p className="text-xs font-bold text-amber-800 mt-2">
                Estado: {paymentStatusLabel(confirmation.payment_status)}
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
          className="w-full mt-6 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs border cursor-pointer select-none inline-flex items-center justify-center gap-2"
          style={{
            background: orangeCtaGradient,
            borderColor: colors2000s.orange.dark,
            color: colors2000s.text.onOrangeSelection,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
          }}
        >
          Ir a pagar
          <ExternalLink className="w-4 h-4" />
        </a>
      )}

      {whatsappHref && !confirmation.payment_link && (
        <a
          href={whatsappHref}
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

      {isWhatsappDeposit && !whatsappHref && (
        <p className="w-full mt-6 text-sm font-bold text-amber-800">
          Comunicate con {storeName} para pagar la seña.
        </p>
      )}

      {withoutEmail && (
        <BookingNoEmailActions
          confirmation={confirmation}
          storeName={storeName}
          whatsappNumber={whatsappNumber}
        />
      )}

      {/* "Mis turnos" se abre con un codigo que sale solo por email: sin email
          no hay a donde mandarlo. */}
      {storeSlug && !withoutEmail && (
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
