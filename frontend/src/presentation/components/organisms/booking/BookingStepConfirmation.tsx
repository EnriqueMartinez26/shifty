import React, { useEffect, useEffectEvent, useId, useReducer, useRef, useState } from 'react'

import { FileText, Loader2, Mail, Phone, Tag, TriangleAlert, User } from 'lucide-react'

import type { SelectedAddon } from '@domain/value-objects/AddonSelection'
import { Email } from '@domain/value-objects/Email'
import { MAX_SERVICES_PER_BOOKING } from '@domain/value-objects/ServiceSelection'

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
import { formatArgentinaDayHeading } from '@shared/utils/argentinaTime'
import { CLIENT_PHONE_HINT, isValidClientPhone } from '@shared/utils/clientPhone'
import { formatCurrency } from '@shared/utils/currency'
import { phoneDigits } from '@shared/utils/otpSession'
import { savePriorDesignHandoff } from '@shared/utils/priorDesignHandoff'
import { navigateExternal } from '@shared/utils/safeUrl'

import {
  groupAddonsByService,
  sumAmounts,
  toSelectedAddons,
  type ServiceAddonsGroup
} from './addonGroups'
import { BookingBackButton } from './BookingBackButton'
import { type BookingBotTrap, BookingHoneypotField, formElapsedMs } from './BookingBotTrap'
import {
  BookingConfirmationCard,
  type BookingPaymentMethod,
  type BookingSubmitAction
} from './BookingConfirmationCard'
import { BookingOtpSection } from './BookingOtpSection'
import { BookingPriceSummary } from './BookingPriceSummary'
import { priorDesignHandoffFor } from './BookingPriorDesign'
import { BookingSuccess } from './BookingSuccess'
import { depositBreakdownText } from './depositReasons'
import type { BookingClientData, BookingOtpState, BookingWizardState } from './types'
import { colors2000s } from '../../../../theme/colors'
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
  ...SERVICE_COMBO_MESSAGES,
  // La trampa para bots (S4): el aviso no dice por que, para no ensenarle al
  // bot que campo o que espera lo delato.
  BOOKING_REJECTED: 'No pudimos registrar la reserva. Probá de nuevo.'
}
// Los adicionales se eligen en el primer paso (S4): aca solo se avisa.
const ADDONS_CHANGED_MESSAGE =
  'Los adicionales del servicio cambiaron. Revisá tu selección en el primer paso.'
// Espera antes de pedir la seña con otros adicionales: cada toque del
// contador era una request.
const ADDONS_PREVIEW_DEBOUNCE_MS = 300

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
  /**
   * Lleva a elegir los adicionales (el primer paso) cuando el catalogo cambio.
   * Sin el, "Revisar adicionales" vuelve con `onBack`.
   */
  onEditAddons?: () => void
  /** La reserva quedo hecha y se muestra la pantalla de exito. */
  onBooked?: () => void
  /**
   * `botTrap` va al cuerpo de la reserva y nunca a su huella de idempotencia:
   * otro tiempo de llenado no es otro pedido.
   */
  onConfirm: (
    paymentMethod: 'manual' | 'mercadopago',
    acceptsTerms: boolean,
    addons: PublicBookingAddon[],
    botTrap: BookingBotTrap
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
  onEditAddons,
  onBooked,
  onConfirm
}) => {
  const fieldId = useId()
  const [acceptsTerms, setAcceptsTerms] = useState(false)
  // Con los dos medios disponibles se elige antes del unico boton; arranca en
  // pagar online.
  const [chosenMethod, setChosenMethod] = useState<BookingPaymentMethod>('mercadopago')
  // Las notas van plegadas como el codigo; escritas (volver al paso), abiertas.
  const [notesOpen, setNotesOpen] = useState(Boolean(bookingState.client.notes))
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
  const addonGroups: ServiceAddonsGroup[] = groupAddonsByService(
    serviceIds,
    servicesQuery.data,
    bookingState.addons
  )
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

  // La promo se mide contra el total (servicio + adicionales): al volver al
  // paso con un codigo aplicado se vuelve a validar, con la misma espera que la
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
  // Los adicionales se cambian en el primer paso (S4): al volver con un codigo
  // aplicado se revalida una vez contra la seleccion actual. Sincroniza con el
  // backend (sistema externo), no deriva estado.
  const revalidateOnReturn = useEffectEvent(() => revalidatePromotion(addonQueryParams))
  useEffect(() => {
    revalidateOnReturn()
  }, [])
  // El catalogo cambio: se guarda lo que sigue vigente (como hacia "Revisé mi
  // selección") y se lleva a revisarlo donde se elige.
  const reviewAddons = () => {
    onAddonsChange(toSelectedAddons(addonGroups))
    ;(onEditAddons ?? onBack)()
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
  // Que, con quien y cuando, en una linea: "Semipermanente + 3 Decoración ·
  // viernes 25/09 · 09:00 hs · con Ana". Con "Cualquiera" el profesional es el
  // que asigno el horario elegido; si no se conoce, no se muestra. Los
  // servicios y la duracion del turno entero, solo con todo el catalogo.
  const { assignedStaff } = bookingState
  const allServicesLoaded = selectedServices.length === serviceIds.length
  const servicesLabel = addonGroups
    .flatMap((group) =>
      group.service
        ? [
            group.service.name,
            ...group.selection
              .lines()
              .map((line) => (line.quantity > 1 ? `${line.quantity} ${line.name}` : line.name))
          ]
        : []
    )
    .join(' + ')
  const totalDuration = selectedServices.reduce(
    (sum, service) => sum + Number(service.duration_minutes),
    0
  )
  const turnDay = formatArgentinaDayHeading(bookingState.date ?? '')
  const summaryServices = allServicesLoaded && servicesLabel ? servicesLabel : null
  const summaryDetails = [
    ...(allServicesLoaded && hasExtraServices ? [`${totalDuration} min`] : []),
    ...(turnDay ? [turnDay] : []),
    `${bookingState.startTime ?? ''} hs`,
    ...(assignedStaff
      ? [assignedStaff.isResource ? assignedStaff.name : `con ${assignedStaff.name}`]
      : [])
  ]
  // Un solo boton (S5): con los dos medios, el que se eligio; si no, el unico.
  // Con seña solo online y sin Mercado Pago no hay con que reservar (como antes).
  const submitMethod: BookingPaymentMethod | null = onlinePaymentMandatory
    ? canPayDeposit
      ? 'mercadopago'
      : null
    : canPayDeposit
      ? chosenMethod
      : 'manual'
  // El importe en el boton solo si el backend ya lo confirmo para estos datos.
  const confirmedDepositLabel =
    depositPreview && depositPreviewConfirmed ? formatCurrency(depositPreview.amount) : null
  const submitAction: BookingSubmitAction | null = submitMethod && {
    method: submitMethod,
    label:
      submitMethod === 'mercadopago'
        ? confirmedDepositLabel
          ? `Pagar seña ${confirmedDepositLabel}`
          : 'Pagar seña con Mercado Pago'
        : owesDepositByWhatsApp
          ? 'Reservar y pagar la seña por WhatsApp'
          : 'Confirmar reserva',
    owesDepositByWhatsApp,
    disabled: !canSubmit
  }
  // Sin el catalogo ni el total del backend no se muestra un importe inventado.
  const shownTotal = allServicesLoaded || serverTotal !== null ? totalPrice : null
  const totalLabel = shownTotal === null ? null : `Total ${formatCurrency(shownTotal)}`

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

  // Trampa para bots (S4): el campo oculto y cuando se mostro este paso. Se
  // mide desde aca y no desde el inicio del wizard: elegir servicio y horario
  // no es llenar el formulario, y un bot pasa esos pasos tan rapido como este.
  // Un ref y no estado: solo se lee al enviar y no cambia lo que se pinta.
  const [website, setWebsite] = useState('')
  const shownAtRef = useRef(performance.now())

  const handleConfirm = async (paymentMethod: 'manual' | 'mercadopago') => {
    if (isSubmittingRef.current) return
    isSubmittingRef.current = true
    dispatchSubmission({ type: 'submit' })
    setErrorMessage('')
    try {
      const result = await onConfirm(
        paymentMethod,
        acceptsTerms,
        addonGroups.flatMap((group) => group.selection.toPayload()),
        { website, formElapsedMs: formElapsedMs(shownAtRef.current, performance.now()) }
      )
      if (paymentMethod === 'mercadopago') {
        // La pantalla de exito no se ve con MP: el diseño previo (S7) se
        // ofrece a la vuelta con este resumen.
        const handoff = priorDesignHandoffFor(
          selectedServices,
          result,
          result.client_name?.trim() || client.name,
          storeName
        )
        if (handoff) savePriorDesignHandoff(storePublicId, handoff)
        if (!navigateExternal(result.payment_link)) {
          throw new Error('Mercado Pago no devolvió un enlace de pago válido')
        }
        return
      }
      dispatchSubmission({ type: 'succeed', confirmation: result })
      onBooked?.()
    } catch (error: unknown) {
      const code = getErrorCode(error)
      const status = getHttpStatus(error)
      // El catalogo cacheado (edge y navegador) puede ser el viejo: se pide
      // salteando los caches y lo elegido se revisa contra el nuevo.
      if (code === ADDON_UNAVAILABLE) void refreshServices()
      dispatchSubmission({
        type: 'fail',
        // Solo el código de conflicto emitido al reservar puede indicar que
        // otra persona tomó el horario; otros 409 describen causas distintas.
        slotMayBeTaken: status === 409 && code === 'APPOINTMENT_CONFLICT'
      })
      setErrorMessage(
        getErrorMessage(
          error,
          'No pudimos procesar tu reserva. Probá de nuevo.',
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
      id: `${fieldId}-custom-${field.key}`,
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
  // encabezado, pero sigue nombrado para los lectores de pantalla. Arriba solo
  // los tres datos (S5); la verificacion del telefono va con ellos.
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
        <BookingHoneypotField id={`${fieldId}-website`} value={website} onChange={setWebsite} />
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
        {requiresOtp && !showOtpSection && (
          <p
            className="mt-1 ml-1 text-[11px] font-bold"
            style={{ color: colors2000s.text.secondary }}
          >
            Completá tu teléfono para verificarlo antes de confirmar.
          </p>
        )}
      </div>

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
    </section>
  )

  // Lo que la tienda pide aparte de los tres datos, y las notas: debajo, sin
  // perderse (S5). Las notas van plegadas detras de un link, como el codigo.
  const notesFocusPending = useRef(false)
  const focusNotesInput = (input: HTMLTextAreaElement | null) => {
    if (!input || !notesFocusPending.current) return
    notesFocusPending.current = false
    input.focus()
  }
  const renderExtraFields = () => (
    <div className="space-y-4">
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
              <label
                htmlFor={`${fieldId}-custom-${field.key}`}
                className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block"
              >
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

      {notesOpen ? (
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
              ref={focusNotesInput}
              value={client.notes}
              onChange={(e) => updateClient({ notes: e.target.value })}
              className="w-full min-h-[100px] pl-12 pr-4 py-3.5 font-bold resize-none"
              style={clientInputStyle}
              placeholder="Algo que debamos saber?"
            />
          </div>
        </div>
      ) : (
        <button
          type="button"
          aria-expanded={false}
          onClick={() => {
            notesFocusPending.current = true
            setNotesOpen(true)
          }}
          className="min-h-11 inline-flex items-center gap-2 text-xs font-black underline"
          style={{ color: colors2000s.text.primary }}
        >
          <FileText className="w-4 h-4" />
          Agregar una nota para la tienda
        </button>
      )}
    </div>
  )

  const warningBoxStyle = createBookingAccentBoxStyle(
    colors2000s.status.warning.bg,
    colors2000s.status.warning.border,
    colors2000s.status.warning.text
  )
  const dangerBoxStyle = createBookingAccentBoxStyle(
    colors2000s.status.danger.bg,
    colors2000s.status.danger.border,
    colors2000s.status.danger.text
  )

  const renderPromotion = () =>
    !showPromotion ? (
      <button
        type="button"
        aria-expanded={false}
        onClick={() => {
          promotionFocusPending.current = true
          setPromotionOpen(true)
        }}
        className="min-h-11 inline-flex items-center gap-2 text-xs font-black underline"
        style={{ color: colors2000s.text.primary }}
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
          <Tag className="w-4 h-4" style={{ color: colors2000s.text.secondary }} />
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
            style={warningBoxStyle}
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
    )

  const renderAlerts = () => (
    <>
      {/* Si el servicio ya no esta en el catalogo, lo elegido igual se avisa. */}
      {addonsChanged && (
        <div
          role="alert"
          className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
          style={warningBoxStyle}
        >
          <TriangleAlert className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{ADDONS_CHANGED_MESSAGE}</span>
          <button type="button" onClick={reviewAddons} className="min-h-11 underline font-black">
            Revisar adicionales
          </button>
        </div>
      )}

      {addonsOutdated && (
        <div
          role="alert"
          className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
          style={warningBoxStyle}
        >
          <TriangleAlert className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{ADDON_UNAVAILABLE_MESSAGE}</span>
          <button
            type="button"
            onClick={() => {
              // Con el catalogo nuevo se vuelve a pedir el importe: si la
              // seleccion no cambio, la clave del preview tampoco, y el error
              // quedaba hasta recargar.
              void refreshServices().then(() => depositQuery.refetch())
            }}
            className="underline font-black"
          >
            Actualizar adicionales
          </button>
        </div>
      )}

      {errorMessage && (
        <div
          key={errorMessage}
          ref={revealOnMount}
          role="alert"
          aria-live="polite"
          className="p-3 text-xs font-bold flex items-center gap-2"
          style={dangerBoxStyle}
        >
          <TriangleAlert className="w-4 h-4 flex-shrink-0" />
          {errorMessage}
        </div>
      )}

      {amountFailed && (
        <div
          role="alert"
          className="p-3 text-xs font-bold flex flex-wrap items-center gap-2"
          style={dangerBoxStyle}
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
    </>
  )

  if (submission.phase === 'submitting') {
    return (
      <div className="flex flex-col items-center justify-center py-20 duration-500">
        <Loader2
          className="w-16 h-16 animate-spin mb-6"
          style={{ color: colors2000s.text.secondary }}
        />
        <h2
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
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
        // Diseño previo (S7): los servicios del turno, del catalogo ya cargado.
        bookedServices={selectedServices}
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
            style={{ color: colors2000s.text.primary }}
          >
            Tus datos y confirmación
          </h2>
          <p className="text-sm font-bold text-gray-500">
            Completá tus datos, revisá el turno y confirmá la reserva.
          </p>
        </div>
      </div>

      {renderClientFields()}
      {renderExtraFields()}

      <BookingConfirmationCard
        summaryServices={summaryServices}
        summaryDetails={summaryDetails}
        storeName={storeName}
        depositPolicy={depositPolicy}
        acceptsTerms={acceptsTerms}
        onAcceptsTermsChange={setAcceptsTerms}
        paymentChoice={
          canPayDeposit && !onlinePaymentMandatory
            ? {
                value: chosenMethod,
                manualLabel: owesDepositByWhatsApp
                  ? 'Por WhatsApp a la tienda'
                  : 'No la pago ahora, solo reservo',
                onChange: setChosenMethod
              }
            : null
        }
        barAmount={submitMethod === 'mercadopago' && confirmedDepositLabel ? null : totalLabel}
        submit={submitAction}
        onSubmit={(method) => {
          void handleConfirm(method)
        }}
      >
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
          total={shownTotal}
          pendingLabel={amountFailed ? 'Sin confirmar' : undefined}
        />

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

        {renderPromotion()}
        {renderAlerts()}
      </BookingConfirmationCard>

      {submission.phase === 'error' && submission.slotMayBeTaken && (
        <div
          role="alert"
          aria-live="polite"
          className="p-4 text-xs font-bold flex items-center gap-2"
          style={warningBoxStyle}
        >
          <TriangleAlert className="w-4 h-4 flex-shrink-0" />
          El horario podria haberse ocupado mientras completabas el formulario. Volve un paso atras
          y elegí otro.
        </div>
      )}
    </div>
  )
}
