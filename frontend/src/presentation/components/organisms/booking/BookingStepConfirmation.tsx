import React, { useEffect, useState } from 'react'

import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  Clock,
  ExternalLink,
  Loader2,
  Tag
} from 'lucide-react'

import type { BookingConfirmation, PromotionPreview } from '@application/services/PublicBookingService'

import { usePreviewPublicPromotion } from '@presentation/hooks/usePublic'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import type { BookingWizardState } from './types'
import { colors2000s } from '../../../../theme/colors'
import { currencyFmtEsAr as currencyFmt } from '../../../lib/formatters'
import {
  createBookingBackButtonStyle,
  createBookingInputStyle,
  createBookingSurfaceStyle,
  createBookingAccentBoxStyle
} from '../../../lib/surfaceStyles'

interface BookingStepConfirmationProps {
  storePublicId: string
  serviceId: string
  bookingState: BookingWizardState
  onBack: () => void
  onPromotionCodeChange: (promotionCode: string) => void
  onConfirm: () => Promise<BookingConfirmation>
}

export const BookingStepConfirmation: React.FC<BookingStepConfirmationProps> = ({
  storePublicId,
  serviceId,
  bookingState,
  onBack,
  onPromotionCodeChange,
  onConfirm
}) => {
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [confirmation, setConfirmation] = useState<BookingConfirmation | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [promotionCode, setPromotionCode] = useState(bookingState.promotionCode || '')
  const [promotionPreview, setPromotionPreview] = useState<PromotionPreview | null>(null)
  const previewPromotion = usePreviewPublicPromotion()

  useEffect(() => {
    setPromotionCode(bookingState.promotionCode || '')
  }, [bookingState.promotionCode])

  const handleApplyPromotion = async () => {
    const normalizedCode = promotionCode.trim().toUpperCase()
    if (!normalizedCode) {
      setPromotionPreview(null)
      setErrorMessage('')
      onPromotionCodeChange('')
      return
    }

    try {
      const preview = await previewPromotion.mutateAsync({
        storePublicId,
        serviceId,
        code: normalizedCode
      })
      setPromotionPreview(preview)
      onPromotionCodeChange(normalizedCode)
      setPromotionCode(normalizedCode)
      setErrorMessage('')
    } catch (error: unknown) {
      setPromotionPreview(null)
      onPromotionCodeChange('')
      setErrorMessage(getErrorMessage(error, 'No pudimos validar ese codigo'))
    }
  }

  const handleConfirm = async () => {
    setStatus('loading')
    setErrorMessage('')
    try {
      const result = await onConfirm()
      setConfirmation(result)
      setStatus('success')
    } catch (error: unknown) {
      setStatus('error')
      setErrorMessage(
        getErrorMessage(error, 'No pudimos procesar tu reserva. El horario podria estar ocupado.')
      )
    }
  }

  if (status === 'loading') {
    return (
      <div className="flex flex-col items-center justify-center py-20 animate-in fade-in duration-500">
        <Loader2 className="w-16 h-16 animate-spin text-orange-500 mb-6" />
        <h2
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.accent }}
        >
          Confirmando...
        </h2>
        <p className="text-sm font-bold text-gray-500 mt-2">No cierres esta ventana.</p>
      </div>
    )
  }

  if (status === 'success') {
    const isPendingPayment = confirmation?.status === 'pending_payment'
    const isPendingReview = confirmation?.status === 'pending'
    const title = isPendingPayment
      ? 'Reserva Pendiente de Pago'
      : isPendingReview
        ? 'Reserva Registrada'
        : 'Reserva Confirmada'
    const subtitle = confirmation?.payment_required
      ? 'Tu turno se confirma cuando el cobro quede aprobado.'
      : isPendingReview
        ? 'Tu solicitud ya fue enviada y queda pendiente de confirmacion.'
        : bookingState.client.email
          ? `Te enviamos los detalles a ${bookingState.client.email}`
          : 'Tu reserva ya quedo registrada.'

    return (
      <div className="flex flex-col items-center py-10 text-center animate-in fade-in zoom-in-95 duration-500">
        <div className="relative mb-8">
          <div
            className={`absolute inset-0 rounded-full blur-xl opacity-20 animate-pulse ${isPendingPayment || isPendingReview ? 'bg-amber-500' : 'bg-green-500'}`}
          />
          <div
            className="w-24 h-24 rounded-full flex items-center justify-center text-white shadow-2xl relative z-10 border-4 border-white"
            style={{
              background:
                isPendingPayment || isPendingReview
                  ? 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)'
                  : 'linear-gradient(135deg, #4ade80 0%, #16a34a 100%)',
              boxShadow:
                isPendingPayment || isPendingReview
                  ? 'inset 0 2px 4px rgba(255,255,255,0.4), 0 4px 12px rgba(217,119,6,0.3)'
                  : 'inset 0 2px 4px rgba(255,255,255,0.4), 0 4px 12px rgba(22,163,74,0.3)'
            }}
          >
            <CheckCircle2 className="w-12 h-12 stroke-[3px]" />
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
          className="w-full rounded-3xl p-6 text-left border"
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
                className="p-2.5 rounded-xl border text-orange-500"
                style={{
                  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                  borderColor: colors2000s.border.default,
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
                  {bookingState.date}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div
                className="p-2.5 rounded-xl border text-blue-500"
                style={{
                  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                  borderColor: colors2000s.border.default,
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

            {(confirmation?.service_price || confirmation?.final_price) && (
              <div
                className="rounded-2xl p-4 border"
                style={{ background: '#f8fafc', borderColor: '#cbd5e1' }}
              >
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-600 mb-1">
                  Resumen comercial
                </p>
                <div className="space-y-1 text-sm font-black text-slate-900">
                  <p>Servicio: {currencyFmt.format(Number(confirmation.service_price || 0))}</p>
                  {(confirmation.discount_amount || 0) > 0 && (
                    <p>
                      Descuento: -{currencyFmt.format(Number(confirmation.discount_amount || 0))}
                    </p>
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

            {confirmation?.payment_required && (
              <div
                className="rounded-2xl p-4 border"
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

        {confirmation?.payment_link && (
          <a
            href={confirmation.payment_link}
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

        <button
          onClick={() => window.location.reload()}
          className="w-full mt-4 text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none"
          style={{
            background: 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)',
            borderColor: '#020617',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15), 0 4px 10px rgba(0,0,0,0.1)'
          }}
        >
          Hacer otra reserva
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="flex items-center gap-4 mb-2">
        <button
          onClick={onBack}
          type="button"
          className="p-2 rounded-full transition-all active:scale-90 flex items-center justify-center border"
          style={createBookingBackButtonStyle()}
        >
          <ChevronLeft size={20} className="stroke-[3px]" />
        </button>
        <div>
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.orange.accent }}
          >
            Revisa y confirma
          </h2>
          <p className="text-sm font-bold text-gray-500">
            Este es el ultimo paso antes de reservar.
          </p>
        </div>
      </div>

      <div
        className="rounded-3xl p-6 bg-white space-y-5"
        style={createBookingSurfaceStyle()}
      >
          <div className="grid sm:grid-cols-2 gap-4">
          <div className="rounded-2xl p-4 border" style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}>
            <p className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-1">
              Fecha
            </p>
            <p className="text-lg font-black text-gray-800">{bookingState.date}</p>
          </div>
          <div className="rounded-2xl p-4 border" style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}>
            <p className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-1">
              Hora
            </p>
            <p className="text-lg font-black text-gray-800">{bookingState.startTime} hs</p>
          </div>
        </div>

        <div
          className="rounded-2xl p-4 border space-y-3"
          style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}
        >
          <div className="flex items-center gap-2">
            <Tag className="w-4 h-4 text-orange-500" />
            <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
              Codigo promocional
            </p>
          </div>
          <div className="grid sm:grid-cols-[1fr_auto] gap-3">
            <input
              value={promotionCode}
              onChange={(event) => {
                setPromotionCode(event.target.value)
                setPromotionPreview(null)
                onPromotionCodeChange('')
                setErrorMessage('')
              }}
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={createBookingInputStyle()}
              placeholder="Ej: BIENVENIDA10"
            />
            <button
              type="button"
              onClick={() => {
                void handleApplyPromotion()
              }}
              disabled={previewPromotion.isPending}
              className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={{
                background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                border: `1px solid ${colors2000s.border.default}`,
                boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                color: colors2000s.text.primary
              }}
            >
              {previewPromotion.isPending ? 'Validando...' : 'Aplicar'}
            </button>
          </div>
          {promotionPreview && (
              <div
                className="rounded-2xl p-4 border"
                style={{ ...createBookingAccentBoxStyle('#ecfdf5', '#bbf7d0', '#166534') }}
              >
              <p className="text-[10px] font-black uppercase tracking-widest text-green-700">
                {promotionPreview.title}
              </p>
              <div className="mt-2 space-y-1 text-sm font-black text-green-900">
                <p>Servicio: {currencyFmt.format(Number(promotionPreview.base_amount))}</p>
                <p>Descuento: -{currencyFmt.format(Number(promotionPreview.discount_amount))}</p>
                <p>Total final: {currencyFmt.format(Number(promotionPreview.final_amount))}</p>
              </div>
            </div>
          )}
        </div>

        {errorMessage && (
          <div
            role="alert"
            aria-live="polite"
            className="rounded-2xl p-3 text-xs font-bold flex items-center gap-2"
            style={createBookingAccentBoxStyle('#fef2f2', '#fecaca', '#b91c1c')}
          >
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {errorMessage}
          </div>
        )}

        <button
          type="button"
          onClick={() => {
            void handleConfirm()
          }}
          className="w-full text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
            borderColor: colors2000s.orange.accent,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
          }}
        >
          Confirmar reserva
        </button>
      </div>

      {status === 'error' && (
        <div
          role="alert"
          aria-live="polite"
          className="rounded-2xl p-4 text-xs font-bold flex items-center gap-2"
          style={createBookingAccentBoxStyle('#fff7ed', '#fed7aa', '#c2410c')}
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          El horario podria haberse ocupado mientras completabas el formulario. Volve un paso atras
          y elegi otro.
        </div>
      )}
    </div>
  )
}

export default BookingStepConfirmation
