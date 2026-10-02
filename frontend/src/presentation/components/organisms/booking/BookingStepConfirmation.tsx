import React, { useReducer, useRef, useState } from 'react'

import {
  ChevronLeft,
  FileText,
  Loader2,
  Mail,
  Phone,
  Tag,
  TriangleAlert,
  User,
  WalletCards
} from 'lucide-react'

import type {
  BookingConfirmation,
  PromotionPreview
} from '@application/services/PublicBookingService'
import type { StoreCustomField } from '@application/services/StoreSettingsService'

import { useDebouncedValue } from '@presentation/hooks/useDebouncedValue'
import {
  usePreviewPublicPromotion,
  usePublicDepositPreview,
  usePublicServices
} from '@presentation/hooks/usePublic'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { phoneDigits } from '@shared/utils/otpSession'
import { navigateExternal } from '@shared/utils/safeUrl'

import { BookingOtpSection } from './BookingOtpSection'
import { BookingSuccess } from './BookingSuccess'
import { depositBreakdownText } from './depositReasons'
import type { BookingClientData, BookingOtpState, BookingWizardState } from './types'
import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { currencyFmtEsAr as currencyFmt } from '../../../lib/formatters'
import {
  createBookingBackButtonStyle,
  createBookingClientInputStyle,
  createBookingInputStyle,
  createBookingSurfaceStyle,
  createBookingAccentBoxStyle
} from '../../../lib/surfaceStyles'

interface BookingStepConfirmationProps {
  storePublicId: string
  serviceId: string
  paymentsEnabled: boolean
  storeName: string
  /** Slug de la tienda: link a "mis turnos" desde la pantalla de exito. */
  storeSlug?: string
  whatsappNumber?: string | null
  depositPolicy?: string | null
  allowManualCoordination?: boolean
  bookingState: BookingWizardState
  customFields: StoreCustomField[]
  requiresOtp: boolean
  otpState: BookingOtpState
  isRequestingOtp: boolean
  /** Segundos que faltan para poder pedir otro codigo (0: se puede). */
  otpResendSeconds: number
  isVerifyingOtp: boolean
  onRequestOtp: () => void
  onVerifyOtp: () => void
  onOtpEmailChange: (email: string) => void
  onOtpCodeChange: (code: string) => void
  onBack: () => void
  onClientChange: (client: BookingClientData) => void
  onPromotionCodeChange: (promotionCode: string) => void
  onConfirm: (
    paymentMethod: 'manual' | 'mercadopago',
    acceptsTerms: boolean
  ) => Promise<BookingConfirmation>
}

type SubmissionState =
  | { phase: 'idle' }
  | { phase: 'submitting' }
  | { phase: 'success'; confirmation: BookingConfirmation }
  | { phase: 'error' }

type SubmissionAction =
  { type: 'submit' } | { type: 'succeed'; confirmation: BookingConfirmation } | { type: 'fail' }

function submissionReducer(_state: SubmissionState, action: SubmissionAction): SubmissionState {
  switch (action.type) {
    case 'submit':
      return { phase: 'submitting' }
    case 'succeed':
      return { phase: 'success', confirmation: action.confirmation }
    case 'fail':
      return { phase: 'error' }
  }
}

export const BookingStepConfirmation: React.FC<BookingStepConfirmationProps> = ({
  storePublicId,
  serviceId,
  paymentsEnabled,
  storeName,
  storeSlug,
  whatsappNumber,
  depositPolicy,
  allowManualCoordination = true,
  bookingState,
  customFields,
  requiresOtp,
  otpState,
  isRequestingOtp,
  otpResendSeconds,
  isVerifyingOtp,
  onRequestOtp,
  onVerifyOtp,
  onOtpEmailChange,
  onOtpCodeChange,
  onBack,
  onClientChange,
  onPromotionCodeChange,
  onConfirm
}) => {
  const [acceptsTerms, setAcceptsTerms] = useState(false)
  const [submission, dispatchSubmission] = useReducer(submissionReducer, { phase: 'idle' })
  const [errorMessage, setErrorMessage] = useState('')
  // Lo tipeado es del input; el codigo APLICADO es del wizard
  // (bookingState.promotionCode). Se siembra una vez y no se resincroniza:
  // un efecto que copiaba uno sobre otro borraba el campo al editarlo (F11a-04).
  const [promotionCode, setPromotionCode] = useState(bookingState.promotionCode || '')
  const [promotionPreview, setPromotionPreview] = useState<PromotionPreview | null>(null)
  const previewPromotion = usePreviewPublicPromotion()
  const servicesQuery = usePublicServices(storePublicId)
  const selectedService = servicesQuery.data?.find((service) => service.public_id === serviceId)
  // La seña real la decide el backend (antelación e historial del cliente):
  // inferirla desde los campos crudos del servicio divergía en cuanto la
  // tienda configuraba un recargo. Mientras carga, se cae a la inferencia.
  // El telefono solo viaja dentro del rango que acepta el backend
  // (client_phone 6..30): a medio tipear era un 422 por tecla (F11a-05). Sin
  // el, el backend decide la seña sin historial, igual que con uno sin OTP.
  // Viaja con 8 digitos o mas y 400 ms sin tipear: desde el sexto caracter
  // era una request por tecla (F4-06).
  const depositPhone = bookingState.client.phone.trim()
  const eligibleDepositPhone =
    phoneDigits(depositPhone).length >= 8 && depositPhone.length <= 30 ? depositPhone : undefined
  const debouncedDepositPhone = useDebouncedValue(eligibleDepositPhone, 400)
  const depositQuery = usePublicDepositPreview({
    storePublicId,
    serviceId,
    startsAt: bookingState.startsAt,
    clientPhone: debouncedDepositPhone,
    promotionCode: bookingState.promotionCode || undefined
  })
  const inferredDeposit = Boolean(
    selectedService &&
    selectedService.deposit_mode !== 'none' &&
    Number(selectedService.deposit_amount ?? (selectedService.deposit_type === 'full' ? 1 : 0)) > 0
  )
  const depositPreview = depositQuery.data ?? null
  const canPayDeposit = Boolean(
    paymentsEnabled && (depositPreview ? depositPreview.amount > 0 : inferredDeposit)
  )
  // Con seña obligatoria y coordinación manual deshabilitada por la tienda, la
  // única vía válida es pagar online. El backend lo rechaza igual, pero no tiene
  // sentido ofrecer un botón que va a fallar.
  const onlinePaymentMandatory = Boolean(
    depositPreview
      ? depositPreview.online_payment_mandatory
      : canPayDeposit && selectedService?.deposit_mode === 'required' && !allowManualCoordination
  )

  const { client } = bookingState
  const updateClient = (patch: Partial<BookingClientData>) =>
    onClientChange({ ...client, ...patch })
  const updateCustomField = (key: string, value: string) =>
    onClientChange({ ...client, customFields: { ...client.customFields, [key]: value } })

  const customFieldsValid = customFields.every(
    (field) => !field.required || Boolean(client.customFields[field.key]?.trim())
  )
  const clientValid =
    Boolean(client.name.trim()) && Boolean(client.phone.trim()) && customFieldsValid
  // Gate duro: el backend rechaza la reserva si la tienda exige OTP y el
  // telefono no quedo verificado (create_public_booking, public_api/router.py).
  // No se debilita: el boton final queda deshabilitado hasta otpState.verified.
  const otpVerifiedGate = !requiresOtp || otpState.verified
  const canSubmit = acceptsTerms && clientValid && otpVerifiedGate
  const showOtpSection = requiresOtp && client.phone.trim().length >= 6

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

  // Guarda contra reenvios concurrentes: un click repetido (doble click real,
  // doble tap, o un evento duplicado) puede disparar el handler antes de que
  // React desmonte el boton via el estado 'loading'. `status` por si solo no
  // alcanza para esto porque los handlers invocados en el mismo tick leen el
  // mismo closure viejo; el ref se actualiza de forma sincronica y es
  // compartido entre esas invocaciones.
  const isSubmittingRef = useRef(false)

  const handleConfirm = async (paymentMethod: 'manual' | 'mercadopago') => {
    if (isSubmittingRef.current) return
    isSubmittingRef.current = true
    dispatchSubmission({ type: 'submit' })
    setErrorMessage('')
    try {
      const result = await onConfirm(paymentMethod, acceptsTerms)
      if (paymentMethod === 'mercadopago') {
        if (!navigateExternal(result.payment_link)) {
          throw new Error('Mercado Pago no devolvio un enlace de pago valido')
        }
        return
      }
      dispatchSubmission({ type: 'succeed', confirmation: result })
    } catch (error: unknown) {
      dispatchSubmission({ type: 'fail' })
      setErrorMessage(
        getErrorMessage(error, 'No pudimos procesar tu reserva. El horario podria estar ocupado.')
      )
    } finally {
      isSubmittingRef.current = false
    }
  }

  const clientInputStyle = createBookingClientInputStyle()

  const renderCustomField = (field: StoreCustomField) => {
    const commonProps = {
      required: field.required,
      value: client.customFields[field.key] || '',
      onChange: (
        event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
      ) => updateCustomField(field.key, event.target.value),
      style: clientInputStyle
    }

    if (field.type === 'textarea') {
      return (
        <textarea
          {...commonProps}
          className="w-full px-4 py-3.5 font-bold min-h-[100px] resize-none"
          placeholder={field.placeholder || ''}
        />
      )
    }

    if (field.type === 'select') {
      return (
        <select {...commonProps} className="w-full px-4 py-3.5 font-bold">
          <option value="">Seleccionar...</option>
          {field.options.map((option) => (
            <option key={`${field.key}-${option.value}`} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )
    }

    const inputType =
      field.type === 'date' || field.type === 'email' || field.type === 'tel' ? field.type : 'text'
    return (
      <input
        {...commonProps}
        type={inputType}
        className="w-full px-4 py-3.5 font-bold"
        placeholder={field.placeholder || ''}
      />
    )
  }

  const renderClientFields = () => (
    <div className="p-6 bg-white space-y-5" style={createBookingSurfaceStyle()}>
      <div>
        <h3 className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-1">
          Tus datos
        </h3>
        <p className="text-xs font-bold text-gray-500">
          Los necesitamos para registrar tu reserva.
        </p>
      </div>

      <div className="relative">
        <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">
          Nombre Completo
        </label>
        <div className="relative">
          <User size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            required
            autoComplete="name"
            value={client.name}
            onChange={(e) => updateClient({ name: e.target.value })}
            className="w-full pl-12 pr-4 py-3.5 font-bold"
            style={clientInputStyle}
            placeholder="Ej: Juan Perez"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="relative">
          <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">
            Email (Opcional)
          </label>
          <div className="relative">
            <Mail size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="email"
              autoComplete="email"
              value={client.email}
              onChange={(e) => updateClient({ email: e.target.value })}
              className="w-full pl-12 pr-4 py-3.5 font-bold"
              style={clientInputStyle}
              placeholder="juan@email.com"
            />
          </div>
        </div>

        <div className="relative">
          <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">
            Telefono
          </label>
          <div className="relative">
            <Phone size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="tel"
              required
              autoComplete="tel"
              value={client.phone}
              onChange={(e) => updateClient({ phone: e.target.value })}
              className="w-full pl-12 pr-4 py-3.5 font-bold"
              style={clientInputStyle}
              placeholder="PREFIJO + NUM"
            />
          </div>
        </div>
      </div>

      {customFields.length > 0 && (
        <div
          className="space-y-4 rounded-md p-4"
          style={{
            ...createBookingSurfaceStyle(),
            borderRadius: 6,
            background: 'rgba(255,255,255,0.55)'
          }}
        >
          <div>
            <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
              Datos extra del turno
            </p>
            <p className="text-xs font-bold text-gray-500 mt-1">
              Completalos para que el negocio prepare mejor tu atencion.
            </p>
          </div>
          {customFields.map((field) => (
            <div key={field.key} className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block">
                {field.label}
                {field.required ? ' *' : ''}
              </label>
              {renderCustomField(field)}
              {field.help_text && (
                <p className="text-[11px] font-bold text-gray-400 ml-1">{field.help_text}</p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="relative">
        <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">
          Notas Adicionales (Opcional)
        </label>
        <div className="relative">
          <FileText size={18} className="absolute left-4 top-4 text-gray-400" />
          <textarea
            value={client.notes}
            onChange={(e) => updateClient({ notes: e.target.value })}
            className="w-full pl-12 pr-4 py-3.5 font-bold min-h-[100px] resize-none"
            style={clientInputStyle}
            placeholder="Algo que debamos saber?"
          />
        </div>
      </div>
    </div>
  )

  if (submission.phase === 'submitting') {
    return (
      <div className="flex flex-col items-center justify-center py-20 duration-500">
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

  if (submission.phase === 'success') {
    return (
      <BookingSuccess
        confirmation={submission.confirmation}
        bookingState={bookingState}
        storeSlug={storeSlug}
        storeName={storeName}
        whatsappNumber={whatsappNumber}
      />
    )
  }

  return (
    <div className="space-y-6 duration-500">
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
            Tus datos y confirmacion
          </h2>
          <p className="text-sm font-bold text-gray-500">
            Completa tus datos, revisa el turno y confirma la reserva.
          </p>
        </div>
      </div>

      {renderClientFields()}

      {showOtpSection && (
        <BookingOtpSection
          phone={client.phone}
          otpState={otpState}
          isRequestingOtp={isRequestingOtp}
          otpResendSeconds={otpResendSeconds}
          isVerifyingOtp={isVerifyingOtp}
          onRequestOtp={onRequestOtp}
          onVerifyOtp={onVerifyOtp}
          onOtpEmailChange={onOtpEmailChange}
          onOtpCodeChange={onOtpCodeChange}
        />
      )}
      {requiresOtp && !showOtpSection && (
        <p className="text-xs font-bold text-center" style={{ color: colors2000s.text.secondary }}>
          Completa tu telefono para verificarlo antes de confirmar.
        </p>
      )}

      <div className="p-6 bg-white space-y-5" style={createBookingSurfaceStyle()}>
        <div className="grid sm:grid-cols-2 gap-4">
          <div
            className="p-4 border"
            style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}
          >
            <p className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-1">
              Fecha
            </p>
            <p className="text-lg font-black text-gray-800">{bookingState.date}</p>
          </div>
          <div
            className="p-4 border"
            style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}
          >
            <p className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-1">
              Hora
            </p>
            <p className="text-lg font-black text-gray-800">{bookingState.startTime} hs</p>
          </div>
        </div>

        <div
          className="p-4 border space-y-3"
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
              className="w-full px-4 py-3 font-bold outline-none"
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
              className="p-4"
              style={{
                ...createBookingAccentBoxStyle(
                  colors2000s.status.success.bg,
                  colors2000s.status.success.border,
                  colors2000s.status.success.text
                ),
                border: 'none'
              }}
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
            className="p-3 text-xs font-bold flex items-center gap-2"
            style={createBookingAccentBoxStyle(
              colors2000s.status.danger.bg,
              colors2000s.status.danger.border,
              colors2000s.status.danger.text
            )}
          >
            <TriangleAlert className="w-4 h-4 flex-shrink-0" />
            {errorMessage}
          </div>
        )}

        {depositPreview && depositPreview.amount > 0 && (
          <div
            className="rounded-2xl p-4 text-xs"
            style={createBookingAccentBoxStyle('#eff6ff', '#bfdbfe', '#1e3a8a')}
            data-testid="deposit-preview"
          >
            <p className="font-black uppercase tracking-widest text-[10px] mb-1">Seña</p>
            <p className="text-sm font-black">{currencyFmt.format(depositPreview.amount)}</p>
            {depositPreview.extra_percent > 0 && (
              <p className="font-medium mt-1">
                {depositBreakdownText(depositPreview, (n) => currencyFmt.format(n))}
              </p>
            )}
          </div>
        )}

        {depositPolicy && (
          <div
            className="p-4 text-xs leading-relaxed"
            style={createBookingAccentBoxStyle(
              colors2000s.bg.button,
              colors2000s.border.default,
              colors2000s.text.secondary
            )}
          >
            <p className="font-black uppercase tracking-widest text-[10px] mb-1">
              Politica de seña de {storeName}
            </p>
            <p className="font-medium whitespace-pre-line">{depositPolicy}</p>
          </div>
        )}

        <label
          className="flex items-start gap-3 text-xs font-bold cursor-pointer select-none"
          style={{ color: colors2000s.text.secondary }}
        >
          <input
            type="checkbox"
            checked={acceptsTerms}
            onChange={(event) => setAcceptsTerms(event.target.checked)}
            className="mt-0.5 w-4 h-4 accent-orange-500 cursor-pointer"
          />
          <span>
            Acepto los{' '}
            <a
              href="/legal/terminos"
              target="_blank"
              rel="noreferrer"
              className="underline"
              style={{ color: colors2000s.orange.accent }}
            >
              terminos y condiciones
            </a>
            , la{' '}
            <a
              href="/legal/privacidad"
              target="_blank"
              rel="noreferrer"
              className="underline"
              style={{ color: colors2000s.orange.accent }}
            >
              politica de privacidad
            </a>
            {depositPolicy ? ' y la politica de seña de la tienda.' : '.'}
          </span>
        </label>

        {!onlinePaymentMandatory && (
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => {
              void handleConfirm('manual')
            }}
            className="w-full text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none disabled:cursor-not-allowed"
            style={
              canSubmit
                ? {
                    background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                    borderColor: colors2000s.orange.accent,
                    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                  }
                : buttonStyles2000s.disabled
            }
          >
            <Phone className="w-4 h-4 inline mr-2" />
            Reservar y pagar por WhatsApp
          </button>
        )}
        {canPayDeposit && (
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => {
              void handleConfirm('mercadopago')
            }}
            className="w-full text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed"
            style={
              canSubmit
                ? {
                    background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                    borderColor: colors2000s.orange.accent,
                    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                  }
                : buttonStyles2000s.disabled
            }
          >
            <WalletCards className="w-4 h-4" />
            Pagar seña con Mercado Pago
          </button>
        )}
      </div>

      {submission.phase === 'error' && (
        <div
          role="alert"
          aria-live="polite"
          className="p-4 text-xs font-bold flex items-center gap-2"
          style={createBookingAccentBoxStyle(
            colors2000s.status.warning.bg,
            colors2000s.status.warning.border,
            colors2000s.status.warning.text
          )}
        >
          <TriangleAlert className="w-4 h-4 flex-shrink-0" />
          El horario podria haberse ocupado mientras completabas el formulario. Volve un paso atras
          y elegi otro.
        </div>
      )}
    </div>
  )
}
