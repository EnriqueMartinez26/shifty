import React, { useEffect, useReducer, useRef, useState } from 'react'

import {
  CalendarCheck,
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

import { AddonSelection, type SelectedAddon } from '@domain/value-objects/AddonSelection'
import { Email } from '@domain/value-objects/Email'

import { publicAddonOptions } from '@application/mappers/PublicAddonMapper'
import type {
  BookingConfirmation,
  PromotionPreview,
  PublicBookingAddon
} from '@application/services/PublicBookingService'
import type { StoreCustomField } from '@application/services/StoreSettingsService'

import { useDebouncedValue } from '@presentation/hooks/useDebouncedValue'
import {
  usePreviewPublicPromotion,
  usePublicDepositPreview,
  usePublicServices,
  useRefreshPublicServices
} from '@presentation/hooks/usePublic'

import { getErrorCode, getErrorMessage, getHttpStatus } from '@shared/errors/getErrorMessage'
import { formatArgentinaDateDisplay } from '@shared/utils/argentinaTime'
import { CLIENT_PHONE_HINT, isValidClientPhone } from '@shared/utils/clientPhone'
import { formatCurrency } from '@shared/utils/currency'
import { phoneDigits } from '@shared/utils/otpSession'
import { navigateExternal } from '@shared/utils/safeUrl'

import { BookingAddonsPicker } from './BookingAddonsPicker'
import { BookingOtpSection } from './BookingOtpSection'
import { BookingPriceSummary } from './BookingPriceSummary'
import { BookingSuccess } from './BookingSuccess'
import { depositBreakdownText } from './depositReasons'
import type { BookingClientData, BookingOtpState, BookingWizardState } from './types'
import { buttonStyles2000s, colors2000s, orangeCtaGradient } from '../../../../theme/colors'
import { revealOnMount } from '../../../lib/revealOnMount'
import {
  createBookingBackButtonStyle,
  createBookingClientInputStyle,
  createBookingInputStyle,
  createBookingSurfaceStyle,
  createBookingAccentBoxStyle
} from '../../../lib/surfaceStyles'

// Un 422 nombra el campo; el texto crudo de Pydantic nunca llega (regla 20).
const BOOKING_FIELD_MESSAGES: Partial<Record<string, string>> = {
  client_phone: `Revisá el teléfono. ${CLIENT_PHONE_HINT}`,
  client_name: 'Revisá tu nombre: no puede quedar vacío ni tener caracteres raros.',
  client_email: 'Revisá el email: no parece válido.',
  notes: 'Las notas son demasiado largas o tienen caracteres no permitidos.',
  custom_fields: 'Revisá los datos adicionales que pide el negocio.'
}

// 422 ADDON_UNAVAILABLE: el catalogo cambio mientras se elegia (un adicional
// borrado o con otro maximo). Se vuelve a pedir y se avisa; el horario no tiene
// nada que ver.
const ADDON_UNAVAILABLE = 'ADDON_UNAVAILABLE'
const ADDON_UNAVAILABLE_MESSAGE =
  'Uno de los adicionales que elegiste ya no está disponible o cambió. Revisá la selección y volvé a confirmar.'
const BOOKING_CODE_MESSAGES: Partial<Record<string, string>> = {
  [ADDON_UNAVAILABLE]: ADDON_UNAVAILABLE_MESSAGE
}
const ADDONS_CHANGED_MESSAGE =
  'Los adicionales del servicio cambiaron. Revisá tu selección antes de confirmar.'
// Espera antes de pedir la seña con otros adicionales: cada toque del
// contador era una request.
const ADDONS_PREVIEW_DEBOUNCE_MS = 300

const sumAmounts = (a: number, b: number): number => Math.round((a + b) * 100) / 100

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
  /** Codigo aplicado y su descuento (null: sin codigo). */
  onPromotionCodeChange: (promotionCode: string, preview: PromotionPreview | null) => void
  /** Adicionales elegidos, con el nombre y el precio que vio el cliente. */
  onAddonsChange: (addons: SelectedAddon[]) => void
  onConfirm: (
    paymentMethod: 'manual' | 'mercadopago',
    acceptsTerms: boolean,
    addons: PublicBookingAddon[]
  ) => Promise<BookingConfirmation>
}

type SubmissionState =
  | { phase: 'idle' }
  | { phase: 'submitting' }
  | { phase: 'success'; confirmation: BookingConfirmation }
  | { phase: 'error'; slotMayBeTaken: boolean }

type SubmissionAction =
  | { type: 'submit' }
  | { type: 'succeed'; confirmation: BookingConfirmation }
  | { type: 'fail'; slotMayBeTaken: boolean }

function submissionReducer(_state: SubmissionState, action: SubmissionAction): SubmissionState {
  switch (action.type) {
    case 'submit':
      return { phase: 'submitting' }
    case 'succeed':
      return { phase: 'success', confirmation: action.confirmation }
    case 'fail':
      return { phase: 'error', slotMayBeTaken: action.slotMayBeTaken }
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
  onAddonsChange,
  onConfirm
}) => {
  const [acceptsTerms, setAcceptsTerms] = useState(false)
  const [submission, dispatchSubmission] = useReducer(submissionReducer, { phase: 'idle' })
  const [errorMessage, setErrorMessage] = useState('')
  // Lo tipeado es del input; el codigo APLICADO es del wizard
  // (bookingState.promotionCode). Se siembra una vez y no se resincroniza:
  // un efecto que copiaba uno sobre otro borraba el campo al editarlo (F11a-04).
  const [promotionCode, setPromotionCode] = useState(bookingState.promotionCode || '')
  // El descuento aplicado vive en el wizard: al volver un paso y avanzar, el
  // total lo seguia mostrando sin la promo que el backend si cobra.
  const [promotionPreview, setPromotionPreview] = useState<PromotionPreview | null>(
    bookingState.promotionCode ? bookingState.promotionPreview : null
  )
  const applyPromotion = (code: string, preview: PromotionPreview | null) => {
    setPromotionPreview(preview)
    onPromotionCodeChange(code, preview)
  }
  const previewPromotion = usePreviewPublicPromotion()
  const servicesQuery = usePublicServices(storePublicId)
  const refreshServices = useRefreshPublicServices(storePublicId)
  const selectedService = servicesQuery.data?.find((service) => service.public_id === serviceId)
  // Lo elegido contra el catalogo vigente. Si cambio (un adicional borrado,
  // otro precio, un maximo menor) se avisa y hay que revisarlo antes de
  // confirmar: nunca se descarta en silencio.
  const addonOptions = publicAddonOptions(selectedService)
  // Sin el servicio en el catalogo lo elegido no se puede cobrar: si el
  // catalogo ya llego (el servicio desaparecio) se avisa; mientras carga solo
  // se frena la reserva.
  const hasChosenAddons = bookingState.addons.some((addon) => addon.quantity > 0)
  const { selection: addonSelection, changed: addonsChanged } = selectedService
    ? AddonSelection.reconcile(addonOptions, bookingState.addons)
    : { selection: AddonSelection.empty(), changed: Boolean(servicesQuery.data) && hasChosenAddons }
  const addonsBlocked = addonsChanged || (!selectedService && hasChosenAddons)
  const addonLines = addonSelection.lines()
  const addonsKey = addonSelection.toQueryParams().join(',')
  const debouncedAddonsKey = useDebouncedValue(addonsKey, ADDONS_PREVIEW_DEBOUNCE_MS)
  const listPrice = Number(selectedService?.price ?? 0)
  const subtotal = sumAmounts(listPrice, addonSelection.total())
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
    promotionCode: bookingState.promotionCode || undefined,
    addons: debouncedAddonsKey ? debouncedAddonsKey.split(',') : []
  })
  const addonsOutdated = getErrorCode(depositQuery.error) === ADDON_UNAVAILABLE
  // Mientras la seña se recalcula (otros adicionales, otro telefono) la que
  // se ve es la anterior: no se ofrece pagar ni reservar con ese importe.
  const depositUpdating =
    addonsKey !== debouncedAddonsKey ||
    eligibleDepositPhone !== debouncedDepositPhone ||
    Boolean(depositQuery.isPlaceholderData) ||
    Boolean(depositQuery.isFetching)
  // El total lo dice el backend: la promo descuenta el TOTAL (servicio y
  // adicionales; decision de Mateo, 2026-10-14) y `price` del preview de la
  // seña es ese total ya descontado, el mismo que se cobra. El preview de la
  // promo cotiza solo el servicio, asi que no se usa para el total cuando hay
  // adicionales. Sin el preview vigente solo se muestra lo que es exacto sin
  // la red: sin codigo, la suma; con codigo y sin adicionales, el total de la
  // promo. Lo demas espera al backend ("Calculando…").
  const promotionApplied = Boolean(bookingState.promotionCode) && promotionPreview !== null
  const serverTotal =
    depositQuery.data && !depositUpdating && !depositQuery.error
      ? Number(depositQuery.data.price)
      : null
  const totalPrice =
    serverTotal ??
    (!promotionApplied
      ? subtotal
      : addonSelection.isEmpty() && promotionPreview
        ? Number(promotionPreview.final_amount)
        : null)
  const discount =
    promotionApplied && totalPrice !== null
      ? Math.max(0, Math.round((subtotal - totalPrice) * 100) / 100)
      : null

  // La promo se mide contra el total (servicio + adicionales): cambiar la
  // seleccion vuelve a validar el codigo aplicado, con la misma espera que la
  // seña. Si ya no aplica (p. ej. el total quedo bajo el minimo) se quita y se
  // dice, en vez de dejar que la reserva rebote con 422.
  const [promotionNotice, setPromotionNotice] = useState('')
  const [promotionChecking, setPromotionChecking] = useState(false)
  const promotionCheck = useRef<{ timer?: number; seq: number }>({ seq: 0 })
  // Sincroniza con el temporizador (sistema externo): no queda uno vivo al
  // desmontar.
  useEffect(() => {
    const check = promotionCheck.current
    return () => window.clearTimeout(check.timer)
  }, [])
  const cancelPromotionCheck = () => {
    window.clearTimeout(promotionCheck.current.timer)
    promotionCheck.current.seq += 1
    setPromotionChecking(false)
  }
  const revalidatePromotion = (addons: string[]) => {
    const code = bookingState.promotionCode
    if (!code) return
    cancelPromotionCheck()
    const seq = promotionCheck.current.seq
    setPromotionChecking(true)
    promotionCheck.current.timer = window.setTimeout(() => {
      const isCurrent = () => seq === promotionCheck.current.seq
      previewPromotion
        .mutateAsync({ storePublicId, serviceId, code, addons })
        .then((preview) => {
          if (isCurrent()) applyPromotion(code, preview)
        })
        .catch((error: unknown) => {
          if (!isCurrent()) return
          const status = getHttpStatus(error) ?? 0
          if (status >= 400 && status < 500) {
            applyPromotion('', null)
            setPromotionCode('')
            setPromotionNotice(
              `Quitamos el código ${code}: ${getErrorMessage(error, 'ya no aplica con los adicionales elegidos')}`
            )
          } else {
            setPromotionNotice(
              `No pudimos volver a validar el código ${code} con los adicionales elegidos.`
            )
          }
        })
        .finally(() => {
          if (isCurrent()) setPromotionChecking(false)
        })
    }, ADDONS_PREVIEW_DEBOUNCE_MS)
  }
  const commitAddons = (selection: AddonSelection) => {
    onAddonsChange(selection.lines())
    revalidatePromotion(selection.toQueryParams())
  }
  const handleAddonChange = (addonId: string, quantity: number) => {
    commitAddons(
      AddonSelection.create(addonOptions, {
        ...addonSelection.toQuantities(),
        [addonId]: quantity
      })
    )
  }
  const inferredDeposit = Boolean(
    selectedService &&
    selectedService.deposit_mode !== 'none' &&
    Number(selectedService.deposit_amount ?? (selectedService.deposit_type === 'full' ? 1 : 0)) > 0
  )
  const depositPreview = depositQuery.data ?? null
  // Lleva seña (obligatoria u opcional), se cobre online o no.
  const hasDeposit = depositPreview ? depositPreview.amount > 0 : inferredDeposit
  const canPayDeposit = Boolean(paymentsEnabled && hasDeposit)
  // Solo una seña OBLIGATORIA queda debiendose al reservar sin Mercado Pago:
  // con una opcional el backend no genera cobro manual
  // (deposit_channels.resolve_deposit_channel), asi que no hay nada que pagar
  // por WhatsApp. Sin el servicio cargado no se sabe y se cae a confirmar.
  const owesDepositByWhatsApp = hasDeposit && selectedService?.deposit_mode === 'required'
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
  // El telefono con el criterio del backend: con menos de 6 digitos era un 422
  // que se leia como horario ocupado (QA 2026-10-02).
  const phoneValid = isValidClientPhone(client.phone)
  // Obligatorio (decision de Mateo, 2026-10-14): "Mis turnos" se abre con un
  // codigo que sale solo por email; sin email el cliente no podia volver.
  const emailValid = Email.isValid(client.email)
  const clientValid = Boolean(client.name.trim()) && phoneValid && emailValid && customFieldsValid
  // Gate duro: el backend rechaza la reserva si la tienda exige OTP y el
  // telefono no quedo verificado (create_public_booking, public_api/router.py).
  // No se debilita: el boton final queda deshabilitado hasta otpState.verified.
  const otpVerifiedGate = !requiresOtp || otpState.verified
  const canSubmit =
    acceptsTerms &&
    clientValid &&
    otpVerifiedGate &&
    !addonsBlocked &&
    !depositUpdating &&
    !promotionChecking
  const showOtpSection = requiresOtp && client.phone.trim().length >= 6

  const handleApplyPromotion = async () => {
    const normalizedCode = promotionCode.trim().toUpperCase()
    cancelPromotionCheck()
    setPromotionNotice('')
    if (!normalizedCode) {
      applyPromotion('', null)
      setErrorMessage('')
      return
    }

    try {
      const preview = await previewPromotion.mutateAsync({
        storePublicId,
        serviceId,
        code: normalizedCode,
        addons: addonSelection.toQueryParams()
      })
      applyPromotion(normalizedCode, preview)
      setPromotionCode(normalizedCode)
      setErrorMessage('')
    } catch (error: unknown) {
      applyPromotion('', null)
      setErrorMessage(getErrorMessage(error, 'No pudimos validar ese código'))
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
      const result = await onConfirm(paymentMethod, acceptsTerms, addonSelection.toPayload())
      if (paymentMethod === 'mercadopago') {
        if (!navigateExternal(result.payment_link)) {
          throw new Error('Mercado Pago no devolvió un enlace de pago válido')
        }
        return
      }
      dispatchSubmission({ type: 'succeed', confirmation: result })
    } catch (error: unknown) {
      // Sin canal para cobrar la seña (409 DEPOSIT_CHANNEL_UNAVAILABLE) o con
      // un adicional que ya no existe (422 ADDON_UNAVAILABLE) el horario no
      // tiene nada que ver: no se sugiere elegir otro.
      const code = getErrorCode(error)
      // El catalogo cacheado (edge y navegador) puede ser el viejo: se pide
      // salteando los caches y lo elegido se revisa contra el nuevo.
      if (code === ADDON_UNAVAILABLE) void refreshServices()
      dispatchSubmission({
        type: 'fail',
        slotMayBeTaken: code !== 'DEPOSIT_CHANNEL_UNAVAILABLE' && code !== ADDON_UNAVAILABLE
      })
      setErrorMessage(
        getErrorMessage(
          error,
          'No pudimos procesar tu reserva. El horario podria estar ocupado.',
          BOOKING_CODE_MESSAGES,
          BOOKING_FIELD_MESSAGES
        )
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
            Email
          </label>
          <div className="relative">
            <Mail size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="email"
              required
              autoComplete="email"
              value={client.email}
              onChange={(e) => updateClient({ email: e.target.value })}
              className="w-full pl-12 pr-4 py-3.5 font-bold"
              style={clientInputStyle}
              placeholder="juan@email.com"
              aria-invalid={Boolean(client.email.trim()) && !emailValid}
              aria-describedby="booking-email-hint"
            />
          </div>
          {client.email.trim() && !emailValid ? (
            <p id="booking-email-hint" className="mt-1 ml-1 text-[11px] font-bold text-red-600">
              {BOOKING_FIELD_MESSAGES.client_email}
            </p>
          ) : (
            <p id="booking-email-hint" className="mt-1 ml-1 text-[11px] font-bold text-gray-500">
              Te enviamos la confirmación y el acceso a tus turnos.
            </p>
          )}
        </div>

        <div className="relative">
          <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">
            Teléfono
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
              aria-invalid={Boolean(client.phone.trim()) && !phoneValid}
            />
          </div>
          {client.phone.trim() && !phoneValid && (
            <p className="mt-1 ml-1 text-[11px] font-bold text-red-600">{CLIENT_PHONE_HINT}</p>
          )}
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
              Completalos para que el negocio prepare mejor tu atención.
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
            Tus datos y confirmación
          </h2>
          <p className="text-sm font-bold text-gray-500">
            Completá tus datos, revisá el turno y confirmá la reserva.
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
          Completá tu teléfono para verificarlo antes de confirmar.
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
            <p className="text-lg font-black text-gray-800">
              {formatArgentinaDateDisplay(bookingState.date ?? '')}
            </p>
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
              Código promocional
            </p>
          </div>
          <div className="grid sm:grid-cols-[1fr_auto] gap-3">
            <input
              value={promotionCode}
              onChange={(event) => {
                setPromotionCode(event.target.value)
                cancelPromotionCheck()
                setPromotionNotice('')
                applyPromotion('', null)
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
          {promotionNotice && (
            <p
              role="status"
              className="p-3 text-xs font-bold"
              style={createBookingAccentBoxStyle(
                colors2000s.status.warning.bg,
                colors2000s.status.warning.border,
                colors2000s.status.warning.text
              )}
            >
              {promotionNotice}
            </p>
          )}
          {promotionChecking && (
            <p className="text-[11px] font-bold text-gray-500">
              Revisando el código con los adicionales elegidos…
            </p>
          )}
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
              {addonOptions.length > 0 ? (
                // Con adicionales el descuento sale sobre el total: los importes
                // de este preview (solo el servicio) no son los que se cobran.
                <p className="mt-2 text-sm font-black text-green-900">
                  El descuento se aplica al total, adicionales incluidos.
                </p>
              ) : (
                <div className="mt-2 space-y-1 text-sm font-black text-green-900">
                  <p>Servicio: {formatCurrency(Number(promotionPreview.base_amount))}</p>
                  <p>Descuento: -{formatCurrency(Number(promotionPreview.discount_amount))}</p>
                  <p>Total final: {formatCurrency(Number(promotionPreview.final_amount))}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Fuera del bloque de adicionales: si el servicio ya no esta en el
            catalogo, lo elegido igual se avisa. */}
        {addonsChanged && (
          <div
            role="alert"
            className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
            style={createBookingAccentBoxStyle(
              colors2000s.status.warning.bg,
              colors2000s.status.warning.border,
              colors2000s.status.warning.text
            )}
          >
            <TriangleAlert className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1">{ADDONS_CHANGED_MESSAGE}</span>
            <button
              type="button"
              onClick={() => commitAddons(addonSelection)}
              className="underline font-black"
            >
              Revisé mi selección
            </button>
          </div>
        )}

        {addonOptions.length > 0 && (
          <>
            <BookingAddonsPicker
              addons={addonOptions}
              quantities={addonSelection.toQuantities()}
              onChange={handleAddonChange}
            />
            {addonsOutdated && (
              <div
                role="alert"
                className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
                style={createBookingAccentBoxStyle(
                  colors2000s.status.warning.bg,
                  colors2000s.status.warning.border,
                  colors2000s.status.warning.text
                )}
              >
                <TriangleAlert className="w-4 h-4 flex-shrink-0" />
                <span className="flex-1">{ADDON_UNAVAILABLE_MESSAGE}</span>
                <button
                  type="button"
                  onClick={() => {
                    void refreshServices()
                  }}
                  className="underline font-black"
                >
                  Actualizar adicionales
                </button>
              </div>
            )}
            <BookingPriceSummary
              basePrice={listPrice}
              addons={addonLines}
              discount={discount}
              promotionCode={promotionApplied ? bookingState.promotionCode : undefined}
              total={totalPrice}
            />
          </>
        )}

        {errorMessage && (
          <div
            key={errorMessage}
            ref={revealOnMount}
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
            <p className="text-sm font-black">
              {depositUpdating ? 'Calculando…' : formatCurrency(depositPreview.amount)}
            </p>
            {!depositUpdating && depositPreview.extra_percent > 0 && (
              <p className="font-medium mt-1">
                {depositBreakdownText(depositPreview, (n) => formatCurrency(n))}
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
              Política de seña de {storeName}
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
              términos y condiciones
            </a>
            , la{' '}
            <a
              href="/legal/privacidad"
              target="_blank"
              rel="noreferrer"
              className="underline"
              style={{ color: colors2000s.orange.accent }}
            >
              política de privacidad
            </a>
            {depositPolicy ? ' y la política de seña de la tienda.' : '.'}
          </span>
        </label>

        {!onlinePaymentMandatory && (
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => {
              void handleConfirm('manual')
            }}
            className="w-full font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none disabled:cursor-not-allowed"
            style={
              canSubmit
                ? {
                    background: orangeCtaGradient,
                    borderColor: colors2000s.orange.dark,
                    color: colors2000s.text.onOrangeSelection,
                    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                  }
                : buttonStyles2000s.disabled
            }
          >
            {owesDepositByWhatsApp ? (
              <>
                <Phone className="w-4 h-4 inline mr-2" />
                Reservar y pagar la seña por WhatsApp
              </>
            ) : (
              <>
                <CalendarCheck className="w-4 h-4 inline mr-2" />
                Confirmar reserva
              </>
            )}
          </button>
        )}
        {canPayDeposit && (
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => {
              void handleConfirm('mercadopago')
            }}
            className="w-full font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed"
            style={
              canSubmit
                ? {
                    background: orangeCtaGradient,
                    borderColor: colors2000s.orange.dark,
                    color: colors2000s.text.onOrangeSelection,
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

      {submission.phase === 'error' && submission.slotMayBeTaken && (
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
          y elegí otro.
        </div>
      )}
    </div>
  )
}
