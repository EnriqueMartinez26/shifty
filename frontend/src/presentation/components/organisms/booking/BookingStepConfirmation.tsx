import React, { useEffect, useId, useReducer, useRef, useState } from 'react'

import {
  CalendarCheck,
  FileText,
  Loader2,
  Mail,
  Phone,
  Tag,
  TriangleAlert,
  User,
  WalletCards
} from 'lucide-react'

import {
  AddonSelection,
  type AddonOption,
  type SelectedAddon
} from '@domain/value-objects/AddonSelection'
import { Email } from '@domain/value-objects/Email'
import { MAX_SERVICES_PER_BOOKING } from '@domain/value-objects/ServiceSelection'

import { publicAddonOptions } from '@application/mappers/PublicAddonMapper'
import type {
  BookingConfirmation,
  PromotionPreview,
  PublicBookingAddon,
  PublicService
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
import { BookingBackButton } from './BookingBackButton'
import { BookingOtpSection } from './BookingOtpSection'
import { BookingPriceSummary } from './BookingPriceSummary'
import { BookingSuccess } from './BookingSuccess'
import { depositBreakdownText } from './depositReasons'
import type { BookingClientData, BookingOtpState, BookingWizardState } from './types'
import { buttonStyles2000s, colors2000s, orangeCtaGradient } from '../../../../theme/colors'
import { revealOnMount } from '../../../lib/revealOnMount'
import {
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
// Varios servicios en un turno (2026-10-16): la combinacion elegida ya no se
// puede reservar. El horario no tiene nada que ver; se cambia en el paso 1.
const SERVICE_COMBO_MESSAGES: Partial<Record<string, string>> = {
  TOO_MANY_SERVICES: `Podés reservar hasta ${MAX_SERVICES_PER_BOOKING} servicios por turno. Volvé al primer paso y quitá alguno.`,
  SERVICES_TOO_LONG:
    'Los servicios que elegiste no entran en un solo turno. Volvé al primer paso y quitá alguno.',
  MULTI_SERVICE_DISABLED:
    'La tienda ya no toma varios servicios en un mismo turno. Volvé al primer paso y elegí uno solo.',
  // El profesional elegido no hace todos los servicios: no es que el horario
  // se ocupo (revision de #194).
  STAFF_CANNOT_PERFORM_SELECTION:
    'El profesional elegido no hace todos los servicios que elegiste. Volvé al horario y elegí otro profesional.'
}
const BOOKING_CODE_MESSAGES: Partial<Record<string, string>> = {
  [ADDON_UNAVAILABLE]: ADDON_UNAVAILABLE_MESSAGE,
  ...SERVICE_COMBO_MESSAGES
}
const ADDONS_CHANGED_MESSAGE =
  'Los adicionales del servicio cambiaron. Revisá tu selección antes de confirmar.'
// Espera antes de pedir la seña con otros adicionales: cada toque del
// contador era una request.
const ADDONS_PREVIEW_DEBOUNCE_MS = 300

// Una politica de seña mas larga que esto va plegada (unas 6 lineas en 390 px).
const LONG_DEPOSIT_POLICY_CHARS = 280

const sumAmounts = (a: number, b: number): number => Math.round((a + b) * 100) / 100

/** Los adicionales de UN servicio elegido, contra el catalogo vigente. */
interface ServiceAddonsGroup {
  serviceId: string
  service: PublicService | undefined
  options: AddonOption[]
  selection: AddonSelection
  /** Lo elegido cambio en el catalogo (borrado, otro precio, otro maximo). */
  changed: boolean
  /** Habia algo elegido para este servicio. */
  hasChosen: boolean
}

/**
 * Agrupa lo elegido por servicio (un adicional sin `serviceId` es del
 * principal) y lo concilia con el catalogo de cada uno. Sin el servicio en el
 * catalogo lo elegido no se puede cobrar: si el catalogo ya llego se avisa.
 */
const groupAddonsByService = (
  serviceIds: readonly string[],
  catalog: readonly PublicService[] | undefined,
  chosen: readonly SelectedAddon[]
): ServiceAddonsGroup[] =>
  serviceIds.map((id) => {
    const service = catalog?.find((candidate) => candidate.public_id === id)
    const mine = chosen.filter((addon) => (addon.serviceId ?? serviceIds[0]) === id)
    const hasChosen = mine.some((addon) => addon.quantity > 0)
    const options = publicAddonOptions(service)
    const { selection, changed } = service
      ? AddonSelection.reconcile(options, mine)
      : { selection: AddonSelection.empty(), changed: Boolean(catalog) && hasChosen }
    return { serviceId: id, service, options, selection, changed, hasChosen }
  })

/**
 * Las lineas para el wizard: las de un servicio sumado llevan su `serviceId`;
 * las del principal van sin marca, como siempre.
 */
const toSelectedAddons = (
  groups: readonly Pick<ServiceAddonsGroup, 'serviceId' | 'selection'>[]
): SelectedAddon[] =>
  groups.flatMap((group, index) =>
    group.selection
      .lines()
      .map((line) => (index === 0 ? line : { ...line, serviceId: group.serviceId }))
  )

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
  const fieldId = useId()
  const [acceptsTerms, setAcceptsTerms] = useState(false)
  // El codigo promocional va plegado detras de un link: la mayoria no tiene
  // uno y el campo era ruido en el celular. Con un codigo ya aplicado (volver
  // al paso) arranca abierto; una vez abierto no se vuelve a plegar solo, asi
  // los avisos de la revalidacion siempre quedan a la vista.
  const [promotionOpen, setPromotionOpen] = useState(Boolean(bookingState.promotionCode))
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
  // Varios servicios en un turno (2026-10-16): el principal y los sumados, en
  // el orden elegido. Un mismo profesional los hace todos.
  const { extraServiceIds } = bookingState
  const hasExtraServices = extraServiceIds.length > 0
  const serviceIds = [serviceId, ...extraServiceIds]
  // Lo elegido contra el catalogo vigente. Si cambio (un adicional borrado,
  // otro precio, un maximo menor) se avisa y hay que revisarlo antes de
  // confirmar: nunca se descarta en silencio.
  const addonGroups = groupAddonsByService(serviceIds, servicesQuery.data, bookingState.addons)
  const selectedServices = addonGroups.flatMap((group) => (group.service ? [group.service] : []))
  const hasAddonOptions = addonGroups.some((group) => group.options.length > 0)
  const addonsChanged = addonGroups.some((group) => group.changed)
  // Sin el servicio en el catalogo lo elegido no se puede cobrar: mientras
  // carga solo se frena la reserva.
  const addonsBlocked =
    addonsChanged || addonGroups.some((group) => !group.service && group.hasChosen)
  const addonLines = addonGroups.flatMap((group) => group.selection.lines())
  const addonQueryParams = addonGroups.flatMap((group) => group.selection.toQueryParams())
  const addonsEmpty = addonLines.length === 0
  const addonsTotal = addonGroups.reduce(
    (sum, group) => sumAmounts(sum, group.selection.total()),
    0
  )
  const addonsKey = addonQueryParams.join(',')
  const debouncedAddonsKey = useDebouncedValue(addonsKey, ADDONS_PREVIEW_DEBOUNCE_MS)
  // Precios de lista, solo para el detalle: el total lo dice el backend.
  const listPrice = selectedServices.reduce(
    (sum, service) => sumAmounts(sum, Number(service.price)),
    0
  )
  const subtotal = sumAmounts(listPrice, addonsTotal)
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
    addons: debouncedAddonsKey ? debouncedAddonsKey.split(',') : [],
    extraServiceIds
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
  // promo. Lo demas espera al backend ("Calculando…"). Con varios servicios
  // el total sale SOLO del preview (decision de Mateo, 2026-10-16).
  const promotionApplied = Boolean(bookingState.promotionCode) && promotionPreview !== null
  const serverTotal =
    depositQuery.data && !depositUpdating && !depositQuery.error
      ? Number(depositQuery.data.price)
      : null
  const totalPrice =
    serverTotal ??
    (hasExtraServices
      ? null
      : !promotionApplied
        ? subtotal
        : addonsEmpty && promotionPreview
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
  // La ultima revalidacion fallo sin respuesta del backend (red, 5xx): el
  // codigo sigue, pero no se reserva hasta que una revalidacion salga bien.
  const [promotionCheckFailed, setPromotionCheckFailed] = useState(false)
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
    setPromotionCheckFailed(false)
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
        .mutateAsync({ storePublicId, serviceId, code, addons, extraServiceIds })
        .then((preview) => {
          if (!isCurrent()) return
          applyPromotion(code, preview)
          setPromotionNotice('')
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
            setPromotionCheckFailed(true)
            setPromotionNotice(
              `No pudimos volver a validar el código ${code} con los adicionales elegidos. Reintentá para continuar.`
            )
          }
        })
        .finally(() => {
          if (isCurrent()) setPromotionChecking(false)
        })
    }, ADDONS_PREVIEW_DEBOUNCE_MS)
  }
  const commitAddons = (groups: readonly Pick<ServiceAddonsGroup, 'serviceId' | 'selection'>[]) => {
    onAddonsChange(toSelectedAddons(groups))
    revalidatePromotion(groups.flatMap((group) => group.selection.toQueryParams()))
  }
  const handleAddonChange = (groupServiceId: string, addonId: string, quantity: number) => {
    commitAddons(
      addonGroups.map((group) =>
        group.serviceId === groupServiceId
          ? {
              serviceId: group.serviceId,
              selection: AddonSelection.create(group.options, {
                ...group.selection.toQuantities(),
                [addonId]: quantity
              })
            }
          : group
      )
    )
  }
  // Mientras el preview no llega solo se infiere SI hay seña (para ofrecer
  // los botones), nunca el importe: con varios servicios la seña sale sobre
  // el total con la regla mas alta, y eso lo decide el backend.
  const inferredDeposit = selectedServices.some(
    (service) =>
      service.deposit_mode !== 'none' &&
      Number(service.deposit_amount ?? (service.deposit_type === 'full' ? 1 : 0)) > 0
  )
  const depositRequired = selectedServices.some((service) => service.deposit_mode === 'required')
  const depositPreview = depositQuery.data ?? null
  // Lleva seña (obligatoria u opcional), se cobre online o no.
  const hasDeposit = depositPreview ? depositPreview.amount > 0 : inferredDeposit
  const canPayDeposit = Boolean(paymentsEnabled && hasDeposit)
  // Solo una seña OBLIGATORIA queda debiendose al reservar sin Mercado Pago:
  // con una opcional el backend no genera cobro manual
  // (deposit_channels.resolve_deposit_channel), asi que no hay nada que pagar
  // por WhatsApp. Sin el servicio cargado no se sabe y se cae a confirmar.
  const owesDepositByWhatsApp = hasDeposit && depositRequired
  // Con seña obligatoria y coordinación manual deshabilitada por la tienda, la
  // única vía válida es pagar online. El backend lo rechaza igual, pero no tiene
  // sentido ofrecer un botón que va a fallar.
  const onlinePaymentMandatory = Boolean(
    depositPreview
      ? depositPreview.online_payment_mandatory
      : canPayDeposit && depositRequired && !allowManualCoordination
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
  // Opcional, salvo con OTP (propuesta por Mateo, 2026-10-16): el codigo sale
  // solo por email y sin email no hay forma de verificar. Si se escribe, tiene
  // que ser valido. Sin email no hay avisos ni "Mis turnos"; la pantalla de
  // exito ofrece calendario y el WhatsApp de la tienda.
  const emailRequired = requiresOtp
  const emailTyped = Boolean(client.email.trim())
  const emailFormatValid = Email.isValid(client.email)
  const emailValid = emailTyped ? emailFormatValid : !emailRequired
  const clientValid = Boolean(client.name.trim()) && phoneValid && emailValid && customFieldsValid
  // Gate duro: el backend rechaza la reserva si la tienda exige OTP y el
  // telefono no quedo verificado (create_public_booking, public_api/router.py).
  // No se debilita: el boton final queda deshabilitado hasta otpState.verified.
  const otpVerifiedGate = !requiresOtp || otpState.verified
  // Un solo criterio, derivado en el render, para ofrecer reservar o pagar
  // (pedido de Enrique en la revision de #186): si el importe depende del
  // backend (codigo aplicado, adicionales o una seña) tiene que estar
  // confirmado por el preview de la seña para los datos ACTUALES (codigo,
  // adicionales y telefono: misma clave, sin espera pendiente ni dato viejo)
  // y, con codigo, por la ultima revalidacion de la promo. Un error no
  // confirma nada: se ofrece reintentar.
  const depositPreviewConfirmed =
    Boolean(depositQuery.data) && !depositUpdating && !depositQuery.error
  const promotionConfirmed =
    !bookingState.promotionCode || (!promotionChecking && !promotionCheckFailed)
  const amountDependsOnServer =
    Boolean(bookingState.promotionCode) || !addonsEmpty || hasDeposit || hasExtraServices
  const amountConfirmed = !amountDependsOnServer || (depositPreviewConfirmed && promotionConfirmed)
  // El 422 ADDON_UNAVAILABLE tiene su propio aviso (actualizar el catalogo).
  const amountFailed = amountDependsOnServer && Boolean(depositQuery.error) && !addonsOutdated
  // La combinacion de servicios ya no se puede reservar: se dice por que.
  const serviceComboMessage = SERVICE_COMBO_MESSAGES[getErrorCode(depositQuery.error) ?? '']
  const canSubmit =
    acceptsTerms && clientValid && otpVerifiedGate && !addonsBlocked && amountConfirmed
  const showOtpSection = requiresOtp && client.phone.trim().length >= 6
  // Abierto si se pidio, si hay un codigo aplicado o si hay un aviso del
  // codigo: un aviso nunca queda escondido detras del link.
  const showPromotion =
    promotionOpen || Boolean(bookingState.promotionCode) || Boolean(promotionNotice)
  // Al abrirlo desde el link el foco va al campo: el link desaparece y el
  // foco no puede quedar en la nada.
  const promotionFocusPending = useRef(false)
  const focusPromotionInput = (input: HTMLInputElement | null) => {
    if (!input || !promotionFocusPending.current) return
    promotionFocusPending.current = false
    input.focus()
  }
  // Que, con quien y cuando: con "Cualquiera" el profesional es el que asigno
  // el horario elegido; si no se conoce, no se muestra.
  const { assignedStaff } = bookingState
  // "Corte + Barba" y la duracion del turno entero, solo con todo el catalogo.
  const allServicesLoaded = selectedServices.length === serviceIds.length
  const servicesLabel = selectedServices.map((service) => service.name).join(' + ')
  const totalDuration = selectedServices.reduce(
    (sum, service) => sum + Number(service.duration_minutes),
    0
  )
  const turnSummary = [
    { label: 'Fecha', value: formatArgentinaDateDisplay(bookingState.date ?? '') },
    { label: 'Hora', value: `${bookingState.startTime ?? ''} hs` },
    ...(allServicesLoaded && servicesLabel ? [{ label: 'Servicio', value: servicesLabel }] : []),
    ...(allServicesLoaded && hasExtraServices
      ? [{ label: 'Duración', value: `${totalDuration} min` }]
      : []),
    ...(assignedStaff
      ? [
          {
            label: assignedStaff.isResource ? 'Cancha / sala' : 'Profesional',
            value: assignedStaff.name
          }
        ]
      : [])
  ]

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
        addons: addonQueryParams,
        extraServiceIds
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
      const result = await onConfirm(
        paymentMethod,
        acceptsTerms,
        addonGroups.flatMap((group) => group.selection.toPayload())
      )
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
        slotMayBeTaken:
          code !== 'DEPOSIT_CHANNEL_UNAVAILABLE' &&
          code !== ADDON_UNAVAILABLE &&
          !SERVICE_COMBO_MESSAGES[code ?? '']
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

  // Un solo titulo para el paso (el h2): el bloque de datos no repite otro
  // encabezado, pero sigue nombrado para los lectores de pantalla.
  const renderClientFields = () => (
    <section
      aria-label="Tus datos"
      className="p-4 sm:p-6 bg-white space-y-5"
      style={createBookingSurfaceStyle()}
    >
      <div className="relative">
        <label
          htmlFor={`${fieldId}-name`}
          className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1"
        >
          Nombre Completo
        </label>
        <div className="relative">
          <User size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            id={`${fieldId}-name`}
            type="text"
            required
            autoComplete="name"
            value={client.name}
            onChange={(e) => updateClient({ name: e.target.value })}
            className="w-full min-h-11 pl-12 pr-4 py-3.5 font-bold"
            style={clientInputStyle}
            placeholder="Ej: Juan Perez"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="relative">
          <label
            htmlFor={`${fieldId}-email`}
            className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1"
          >
            {emailRequired ? 'Email' : 'Email (opcional)'}
          </label>
          <div className="relative">
            <Mail size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              id={`${fieldId}-email`}
              type="email"
              required={emailRequired}
              autoComplete="email"
              value={client.email}
              onChange={(e) => updateClient({ email: e.target.value })}
              className="w-full min-h-11 pl-12 pr-4 py-3.5 font-bold"
              style={clientInputStyle}
              placeholder="juan@email.com"
              aria-invalid={emailTyped && !emailFormatValid}
              aria-describedby="booking-email-hint"
            />
          </div>
          {emailTyped && !emailFormatValid ? (
            <p id="booking-email-hint" className="mt-1 ml-1 text-[11px] font-bold text-red-600">
              {BOOKING_FIELD_MESSAGES.client_email}
            </p>
          ) : (
            <p id="booking-email-hint" className="mt-1 ml-1 text-[11px] font-bold text-gray-500">
              {emailRequired
                ? 'Te enviamos la confirmación y el acceso a tus turnos.'
                : 'Opcional. Si no lo dejás, no vas a poder gestionar tu turno desde acá ni recibir avisos; para cambiarlo o cancelarlo escribile a la tienda por WhatsApp.'}
            </p>
          )}
        </div>

        <div className="relative">
          <label
            htmlFor={`${fieldId}-phone`}
            className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1"
          >
            Teléfono
          </label>
          <div className="relative">
            <Phone size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              id={`${fieldId}-phone`}
              type="tel"
              required
              autoComplete="tel"
              value={client.phone}
              onChange={(e) => updateClient({ phone: e.target.value })}
              className="w-full min-h-11 pl-12 pr-4 py-3.5 font-bold"
              style={clientInputStyle}
              // Un ejemplo con forma de numero: "PREFIJO + NUM" no decia nada en
              // el celular. La validacion no cambia (isValidClientPhone).
              placeholder="Ej: 351 1234567"
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
        <label
          htmlFor={`${fieldId}-notes`}
          className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1"
        >
          Notas para la tienda (opcional)
        </label>
        <div className="relative">
          <FileText size={18} className="absolute left-4 top-4 text-gray-400" />
          <textarea
            id={`${fieldId}-notes`}
            value={client.notes}
            onChange={(e) => updateClient({ notes: e.target.value })}
            className="w-full min-h-[100px] pl-12 pr-4 py-3.5 font-bold resize-none"
            style={clientInputStyle}
            placeholder="Algo que debamos saber?"
          />
        </div>
      </div>
    </section>
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
      <div className="space-y-3 mb-2">
        <BookingBackButton onBack={onBack} />
        <div>
          <h2
            className="break-words text-2xl font-black uppercase tracking-tight"
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

      <div className="p-4 sm:p-6 bg-white space-y-5" style={createBookingSurfaceStyle()}>
        <dl
          className="grid grid-cols-1 min-[380px]:grid-cols-2 gap-3 sm:gap-4"
          aria-label="Tu turno"
        >
          {turnSummary.map((item) => (
            <div
              key={item.label}
              className="p-3 sm:p-4 border min-w-0"
              style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}
            >
              <dt className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-1">
                {item.label}
              </dt>
              <dd className="text-lg font-black text-gray-800 break-words">{item.value}</dd>
            </div>
          ))}
        </dl>

        {!showPromotion ? (
          <button
            type="button"
            aria-expanded={false}
            onClick={() => {
              promotionFocusPending.current = true
              setPromotionOpen(true)
            }}
            className="inline-flex items-center gap-2 text-xs font-black underline"
            style={{ color: colors2000s.orange.accent }}
          >
            <Tag className="w-4 h-4" />
            ¿Tenés un código de descuento?
          </button>
        ) : (
          <div
            className="p-4 border space-y-3"
            style={{ ...createBookingAccentBoxStyle('#ffffff', '#e5e7eb') }}
          >
            <div className="flex items-center gap-2">
              <Tag className="w-4 h-4 text-orange-500" />
              <label
                htmlFor={`${fieldId}-promo-code`}
                className="text-[10px] font-black uppercase tracking-widest text-gray-400"
              >
                Código promocional
              </label>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3">
              <input
                id={`${fieldId}-promo-code`}
                ref={focusPromotionInput}
                value={promotionCode}
                onChange={(event) => {
                  setPromotionCode(event.target.value)
                  cancelPromotionCheck()
                  setPromotionNotice('')
                  applyPromotion('', null)
                  setErrorMessage('')
                }}
                className="w-full min-h-11 px-4 py-3 font-bold outline-none"
                style={createBookingInputStyle()}
                placeholder="Ej: BIENVENIDA10"
              />
              <button
                type="button"
                onClick={() => {
                  void handleApplyPromotion()
                }}
                disabled={previewPromotion.isPending}
                className="min-h-11 px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
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
              <div
                role="status"
                className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
                style={createBookingAccentBoxStyle(
                  colors2000s.status.warning.bg,
                  colors2000s.status.warning.border,
                  colors2000s.status.warning.text
                )}
              >
                <span className="flex-1">{promotionNotice}</span>
                {promotionCheckFailed && (
                  <button
                    type="button"
                    onClick={() => revalidatePromotion(addonQueryParams)}
                    className="underline font-black"
                  >
                    Reintentar
                  </button>
                )}
              </div>
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
                {hasAddonOptions || hasExtraServices ? (
                  // Con adicionales o varios servicios el descuento sale sobre el
                  // total: los importes de este preview no son los que se cobran.
                  <p className="mt-2 text-sm font-black text-green-900">
                    {hasExtraServices
                      ? 'El descuento se aplica al total del turno.'
                      : 'El descuento se aplica al total, adicionales incluidos.'}
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
        )}

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
              onClick={() => commitAddons(addonGroups)}
              className="underline font-black"
            >
              Revisé mi selección
            </button>
          </div>
        )}

        {(hasAddonOptions || hasExtraServices) && (
          <>
            {/* Con varios servicios, un bloque por servicio con sus adicionales. */}
            {addonGroups.map((group) => (
              <BookingAddonsPicker
                key={group.serviceId}
                title={
                  hasExtraServices && group.service
                    ? `Adicionales de ${group.service.name}`
                    : undefined
                }
                addons={group.options}
                quantities={group.selection.toQuantities()}
                onChange={(addonId, quantity) =>
                  handleAddonChange(group.serviceId, addonId, quantity)
                }
              />
            ))}
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
                    // Con el catalogo nuevo se vuelve a pedir el importe: si la
                    // seleccion no cambio, la clave del preview tampoco, y el
                    // error quedaba hasta recargar.
                    void refreshServices().then(() => depositQuery.refetch())
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
              serviceLines={
                hasExtraServices
                  ? addonGroups.map((group) => ({
                      serviceId: group.serviceId,
                      name: group.service?.name ?? 'Servicio',
                      price: Number(group.service?.price ?? 0),
                      addons: group.selection.lines()
                    }))
                  : undefined
              }
              discount={discount}
              promotionCode={promotionApplied ? bookingState.promotionCode : undefined}
              total={totalPrice}
              pendingLabel={amountFailed ? 'Sin confirmar' : undefined}
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

        {amountFailed && (
          <div
            role="alert"
            className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
            style={createBookingAccentBoxStyle(
              colors2000s.status.danger.bg,
              colors2000s.status.danger.border,
              colors2000s.status.danger.text
            )}
          >
            <TriangleAlert className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1">
              {serviceComboMessage ??
                'No pudimos confirmar el importe de tu reserva. Reintentá para continuar.'}
            </span>
            <button
              type="button"
              onClick={() => {
                void depositQuery.refetch()
              }}
              className="underline font-black"
            >
              Reintentar
            </button>
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
              {depositQuery.error
                ? 'Sin confirmar'
                : depositUpdating
                  ? 'Calculando…'
                  : formatCurrency(depositPreview.amount)}
            </p>
            {depositPreviewConfirmed && depositPreview.extra_percent > 0 && (
              <p className="font-medium mt-1">
                {depositBreakdownText(depositPreview, (n) => formatCurrency(n))}
              </p>
            )}
          </div>
        )}

        {/* La politica se muestra aca, junto a la seña y antes de aceptar
            (Legal.tsx: "se muestra al cliente antes de confirmar la reserva");
            el pie de la pagina no la repite en este paso. Una larga va plegada
            detras de "Ver política de seña" para no tapar el boton en el
            celular; corta, se ve entera. */}
        {depositPolicy &&
          (depositPolicy.length > LONG_DEPOSIT_POLICY_CHARS ? (
            <details
              className="p-4 text-xs leading-relaxed"
              style={createBookingAccentBoxStyle(
                colors2000s.bg.button,
                colors2000s.border.default,
                colors2000s.text.secondary
              )}
            >
              <summary className="cursor-pointer font-black uppercase tracking-widest text-[10px]">
                Ver política de seña de {storeName}
              </summary>
              <p className="mt-2 font-medium whitespace-pre-line">{depositPolicy}</p>
            </details>
          ) : (
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
          ))}

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
            className="w-full min-h-11 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none disabled:cursor-not-allowed"
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
            className="w-full min-h-11 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed"
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
