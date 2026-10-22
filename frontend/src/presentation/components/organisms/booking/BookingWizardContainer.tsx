import React, { useEffect, useMemo, useRef, useState } from 'react'

import { Check } from 'lucide-react'

import { ServiceSelection } from '@domain/value-objects/ServiceSelection'

import { publicPerformers } from '@application/mappers/PublicServiceOptionMapper'
import { hasClientToken } from '@application/services/clientToken'

import { trackBookingCreated, trackBookingEvent } from '@infrastructure/analytics/bookingAnalytics'

import { getErrorCode, getErrorMessage, getRetryAfterSeconds } from '@shared/errors/getErrorMessage'
import { bookingIdempotencyKey, forgetBookingIdempotency } from '@shared/utils/bookingIdempotency'
import { isOtpStillValid, phoneDigits, rememberOtpVerification } from '@shared/utils/otpSession'

import { groupAddonsByService, withAddonQuantity } from './addonGroups'
import { BookingStepConfirmation } from './BookingStepConfirmation'
import { BookingStepDateTime } from './BookingStepDateTime'
import { BookingStepService } from './BookingStepService'
import { EMPTY_PRESELECT, type BookingPreselect } from './deepLink'
import { clampStep, resolveBackJump, resolveStepJump } from './stepFlow'
import type { BookingOtpState, BookingStepChange, BookingWizardState } from './types'
import { colors2000s } from '../../../../theme/colors'
import {
  type PublicStore,
  useCreatePublicBooking,
  usePublicServices,
  usePublicStaff,
  useRequestPublicOtp,
  useVerifyPublicOtp
} from '../../../hooks/usePublic'
import { useResendCooldown } from '../../../hooks/useResendCooldown'
import { brandColor, brandCssVariables, resolveBrandTheme } from '../../../lib/brandTheme'
import { createBookingSurfaceStyle } from '../../../lib/surfaceStyles'

interface BookingWizardContainerProps {
  store: PublicStore
  /** Servicio y profesional ya validados contra las listas publicas (deep-link). */
  preselect?: BookingPreselect
  /**
   * Paso pedido, controlado desde afuera (la URL, F4-15). El wizard lo
   * degrada si falta lo elegido antes y pide corregirlo con `replace`.
   */
  step: number
  onStepChange: (change: BookingStepChange) => void
}

export const BookingWizardContainer: React.FC<BookingWizardContainerProps> = ({
  store,
  preselect = EMPTY_PRESELECT,
  step,
  onStepChange
}) => {
  const requiresOtp = Boolean(store.feature_flags?.otp_booking)
  const initialCustomFields = useMemo(
    () => Object.fromEntries((store.custom_client_fields || []).map((field) => [field.key, ''])),
    [store.custom_client_fields]
  )
  // Siempre 3 pasos, incluidas las tiendas con OTP: el paso de validacion se
  // muestra como sub-fase dentro de "Datos y Confirmacion" en vez de ocupar
  // un paso propio.
  const steps = useMemo(() => ['Servicio', 'Horario y Profesional', 'Datos y Confirmación'], [])

  const [otpState, setOtpState] = useState<BookingOtpState>({
    code: '',
    channel: 'email',
    email: '',
    verified: false,
    verifiedPhone: '',
    expiresAt: '',
    error: '',
    rateLimited: false,
    debugCode: ''
  })
  const [bookingState, setBookingState] = useState<BookingWizardState>({
    serviceId: preselect.serviceId,
    extraServiceIds: [],
    requestedStaffId: preselect.staffId,
    assignedStaffId: null,
    assignedStaff: null,
    date: preselect.date,
    startTime: null,
    startsAt: null,
    client: {
      name: '',
      email: '',
      phone: '',
      notes: '',
      customFields: initialCustomFields
    },
    promotionCode: '',
    promotionPreview: null,
    addons: []
  })

  useEffect(() => {
    setBookingState((prev) => ({
      ...prev,
      client: {
        ...prev.client,
        customFields: Object.keys(prev.client.customFields || {}).length
          ? prev.client.customFields
          : initialCustomFields
      }
    }))
  }, [initialCustomFields])

  const createBooking = useCreatePublicBooking()
  const requestOtp = useRequestPublicOtp()
  const verifyOtp = useVerifyPublicOtp()
  // La espera es del telefono pedido: cambiarlo la libera (F4-11).
  const resendCooldown = useResendCooldown(phoneDigits(bookingState.client.phone))
  const { data: services } = usePublicServices(store.public_id)
  // Varios servicios en un turno (2026-10-16). Quien hace que (`service_ids`)
  // lo pide el contenedor: el paso del servicio solo pinta.
  const multiService = Boolean(store.feature_flags?.multi_service_booking)
  const { data: storeStaff } = usePublicStaff(store.public_id, undefined, multiService)

  // El paso pedido solo se muestra si lo anterior esta elegido: tras recargar
  // con ?step=2 el estado arranca vacio (F4-15).
  const currentStep = clampStep(step, bookingState)
  // La URL pide un paso que no se puede mostrar: se corrige sin dejar una
  // entrada en el historial a la que "atras" volveria. Sincroniza la URL.
  useEffect(() => {
    if (currentStep !== step) onStepChange({ to: currentStep, from: step, mode: 'replace' })
  }, [currentStep, step, onStepChange])

  const stepRegionRef = useRef<HTMLDivElement>(null)
  const previousStepRef = useRef(currentStep)

  // Al cambiar de paso, lleva el foco a la región nombrada. En móvil esto
  // evita abrir el teclado virtual automáticamente; el formulario queda
  // disponible al avanzar con Tab.
  useEffect(() => {
    const previousStep = previousStepRef.current
    if (previousStep === currentStep) return
    previousStepRef.current = currentStep
    stepRegionRef.current?.focus()
  }, [currentStep])

  // Un solo servicio no es una eleccion: se elige solo y el wizard arranca
  // en el horario. Sincroniza con la lista publica (dato externo): cuando
  // llega, si el paso visible es el del servicio y hay uno solo, salta. Con
  // `replace`, "atras" del navegador no rebota al paso salteado.
  useEffect(() => {
    const jump = resolveStepJump(currentStep, { services })
    if (jump.step === currentStep) return
    if (jump.serviceId) {
      setBookingState((prev) =>
        prev.serviceId === jump.serviceId
          ? prev
          : { ...prev, serviceId: jump.serviceId ?? null, extraServiceIds: [], addons: [] }
      )
    }
    onStepChange({ to: jump.step, from: currentStep, mode: 'replace' })
  }, [currentStep, services, onStepChange])

  const updateState = (updates: Partial<typeof bookingState>) => {
    setBookingState((prev) => ({ ...prev, ...updates }))
  }

  const nextStep = () =>
    onStepChange({
      to: Math.min(currentStep + 1, steps.length - 1),
      from: currentStep,
      mode: 'push'
    })
  const prevStep = () => {
    const to = resolveBackJump(currentStep, { services })
    if (to !== currentStep) onStepChange({ to, from: currentStep, mode: 'back' })
  }

  // Tocar suma o quita, sin avanzar. Lo elegido despues (horario, promo) era
  // para otra combinacion y se vuelve a elegir; los adicionales de un servicio
  // quitado se van con el. El profesional pedido (p. ej. por deep-link) se
  // conserva solo si se sabe que hace todos los servicios elegidos.
  const handleToggleService = (id: string) => {
    const previous = ServiceSelection.fromParts(
      bookingState.serviceId,
      bookingState.extraServiceIds
    )
    const next = previous.toggle(id)
    const previousPrincipal = previous.principalId()
    const requested = bookingState.requestedStaffId
    const requestedDoesAll = Boolean(
      storeStaff?.some(
        (member) =>
          member.public_id === requested &&
          next.ids().every((serviceId) => (member.service_ids ?? []).includes(serviceId))
      )
    )
    updateState({
      serviceId: next.principalId(),
      extraServiceIds: next.extraIds(),
      addons: bookingState.addons.filter((addon) =>
        next.includes(addon.serviceId ?? previousPrincipal ?? '')
      ),
      promotionCode: '',
      promotionPreview: null,
      requestedStaffId: requestedDoesAll ? requested : null,
      assignedStaffId: null,
      assignedStaff: null,
      date: null,
      startTime: null,
      startsAt: null
    })
  }

  // Los adicionales se eligen en el paso del servicio, debajo de cada servicio
  // elegido (S4, 2026-10-21). `bookingState.addons` sigue siendo la unica
  // fuente: los grupos se concilian contra el catalogo en cada render.
  const chosenServiceIds = bookingState.serviceId
    ? [bookingState.serviceId, ...bookingState.extraServiceIds]
    : []
  const addonGroups = groupAddonsByService(chosenServiceIds, services, bookingState.addons)
  const serviceHasAddons = (id: string) =>
    Boolean(services?.find((service) => service.public_id === id)?.addons?.length)

  const continueFromService = () => {
    trackBookingEvent('service_selected')
    nextStep()
  }

  // La promo se mide contra el total (servicio y adicionales): con otros
  // adicionales el descuento calculado ya no vale, pero el codigo se conserva
  // y la confirmacion lo vuelve a validar al entrar (avisa si deja de aplicar).
  // Borrarlo en silencio obligaba a la clienta a cargarlo de nuevo.
  const handleAddonChange = (serviceId: string, addonId: string, quantity: number) => {
    updateState({
      addons: withAddonQuantity(addonGroups, serviceId, addonId, quantity),
      promotionPreview: null
    })
  }

  const handleClientChange = (client: BookingWizardState['client']) => {
    const emailAnterior = bookingState.client.email
    updateState({ client })
    // Una verificacion de OTP queda atada al telefono que se valido. Si el
    // usuario lo edita despues de verificar, el gate vuelve a cerrarse para
    // ese telefono nuevo (create_public_booking la exige de nuevo en el
    // backend; esto solo evita mostrar un estado "verificado" enganoso).
    // Si ese telefono ya se verifico en este dispositivo dentro de la
    // ventana de 30 minutos, no se vuelve a pedir el codigo (el backend lo
    // acepta y asi no se agota el presupuesto de pedidos por hora).
    setOtpState((prev) => {
      const email = prev.email === emailAnterior || !prev.email ? client.email : prev.email
      // Mismo telefono = mismos digitos: el backend devuelve el verificado
      // normalizado (+54...) y la persona lo tipea con espacios o guiones.
      // Comparar las cadenas crudas des-verificaba ante cualquier edicion
      // cuando no habia sessionStorage que lo rescatara (F11a-08).
      if (phoneDigits(client.phone) === phoneDigits(prev.verifiedPhone)) return { ...prev, email }
      // Con el token del cliente (2026-10-14): sin el, el backend rechaza la
      // reserva con otp_booking aunque la verificacion siga recordada.
      if (
        client.phone.trim() &&
        isOtpStillValid(store.slug, client.phone) &&
        hasClientToken(store.public_id)
      ) {
        return { ...prev, email, verified: true, verifiedPhone: client.phone, error: '' }
      }
      return prev.verified
        ? { ...prev, email, verified: false, code: '', debugCode: '', error: '' }
        : { ...prev, email }
    })
  }

  const handleRequestOtp = async () => {
    const email = otpState.email.trim()
    if (!email) {
      setOtpState((prev) => ({ ...prev, error: 'Ingresá el email donde querés recibir el código' }))
      return
    }
    try {
      const response = await requestOtp.mutateAsync({
        store_public_id: store.public_id,
        phone: bookingState.client.phone,
        channel: otpState.channel,
        email
      })
      // J7 (2026-09-30): debug_code se guarda tal cual vino y se muestra con
      // el aviso de que puede ser un senuelo (AUD2-SYNC-01); sin el, vacio.
      setOtpState((prev) => ({
        ...prev,
        expiresAt: response.expires_at,
        error: '',
        debugCode: response.debug_code || ''
      }))
      resendCooldown.start()
    } catch (error: unknown) {
      // OTP_RATE_LIMITED: se agotaron los codigos del telefono y la ventana
      // del backend es deslizante; no se ofrece pedir otro hasta recargar.
      // Otro 429/503 con Retry-After arranca esa espera (F4-11, 2026-09-30).
      const rateLimited = getErrorCode(error) === 'OTP_RATE_LIMITED'
      setOtpState((prev) => ({
        ...prev,
        rateLimited: prev.rateLimited || rateLimited,
        error: getErrorMessage(error, 'No se pudo enviar el código')
      }))
      const retryAfter = rateLimited ? undefined : getRetryAfterSeconds(error)
      if (retryAfter !== undefined) resendCooldown.start(retryAfter)
    }
  }

  const handleVerifyOtp = async () => {
    try {
      const response = await verifyOtp.mutateAsync({
        store_public_id: store.public_id,
        phone: bookingState.client.phone,
        code: otpState.code
      })
      rememberOtpVerification(store.slug, response.phone, response.verified_at)
      setOtpState((prev) => ({
        ...prev,
        verified: true,
        verifiedPhone: response.phone,
        error: ''
      }))
    } catch (error: unknown) {
      setOtpState((prev) => ({
        ...prev,
        error: getErrorMessage(error, 'Código inválido')
      }))
    }
  }

  const renderStepIndicator = () => (
    <div className="p-4 mb-8 relative overflow-hidden" style={createBookingSurfaceStyle()}>
      <p
        aria-hidden="true"
        className="mb-3 text-center text-xs font-bold md:hidden"
        style={{ color: colors2000s.text.primary }}
      >
        Paso {currentStep + 1} de {steps.length}: {steps[currentStep]}
      </p>
      <ol aria-label="Pasos de la reserva" className="flex items-start">
        {steps.map((label, i) => {
          const isCompleted = i < currentStep
          const isActive = i === currentStep
          const status = isCompleted ? 'completado' : isActive ? 'actual' : 'pendiente'

          return (
            <li
              key={label}
              aria-current={isActive ? 'step' : undefined}
              aria-label={`Paso ${i + 1} de ${steps.length}: ${label}, ${status}`}
              className="relative z-10 flex min-w-0 flex-1 flex-col items-center gap-1"
            >
              <div
                aria-hidden="true"
                className="z-10 w-9 h-9 rounded-full flex items-center justify-center text-xs font-black transition-all cursor-default select-none"
                style={{
                  background: isCompleted
                    ? `linear-gradient(180deg, ${colors2000s.status.success.light} 0%, ${colors2000s.status.success.dark} 100%)`
                    : isActive
                      ? brandColor.fillGradient
                      : `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.disabledBottom} 100%)`,
                  boxShadow: isCompleted
                    ? `${colors2000s.shadows.insetLight}, 0 2px 4px rgba(16,185,129,0.3)`
                    : isActive
                      ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                      : `${colors2000s.shadows.insetLight}, 0 1px 2px rgba(0,0,0,0.05)`,
                  color: isCompleted
                    ? colors2000s.text.onOrange
                    : isActive
                      ? brandColor.onFill
                      : colors2000s.text.secondary
                }}
              >
                {isCompleted ? <Check className="w-4 h-4 font-black" /> : i + 1}
              </div>
              <span
                className={`text-[9px] uppercase tracking-wider hidden md:block mt-1 font-black text-center ${isActive ? '' : isCompleted ? 'text-green-600' : 'text-gray-400'}`}
                style={isActive ? { color: brandColor.ink } : undefined}
              >
                {label}
              </span>
              {i < steps.length - 1 && (
                <span
                  aria-hidden="true"
                  className="absolute top-4 h-1 rounded-full transition-all"
                  style={{
                    left: 'calc(50% + 18px)',
                    right: 'calc(-50% + 18px)',
                    background: isCompleted
                      ? `linear-gradient(90deg, ${colors2000s.status.success.dark} 0%, ${colors2000s.status.success.light} 100%)`
                      : colors2000s.bg.disabled,
                    boxShadow: isCompleted ? 'none' : 'inset 0 1px 1px rgba(0,0,0,0.1)'
                  }}
                />
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )

  // Todos los pasos posteriores al primero requieren un servicio elegido. La
  // guarda en el JSX convierte esa invariante en un chequeo del compilador en
  // lugar de un "!" que promete sin verificar.
  const selectedServiceId = bookingState.serviceId

  return (
    <div
      // Menos relleno en el telefono: con p-8 + p-6 la tarjeta del servicio
      // quedaba de 227 px en 390 y cortaba los nombres (QA movil 2026-10-08).
      className="max-w-2xl mx-auto rounded-lg p-4 sm:p-8 relative overflow-hidden duration-700"
      style={{
        // El color de la tienda (S3), una sola vez: los pasos leen var(--brand-*).
        ...brandCssVariables(resolveBrandTheme(store.primary_color)),
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: `${colors2000s.shadows.insetLight}, 0 10px 30px rgba(0, 0, 0, 0.08)`
      }}
    >
      <div
        className="absolute top-0 left-0 right-0 h-2 opacity-50"
        style={{
          background:
            'linear-gradient(180deg, rgba(255, 255, 255, 0.8) 0%, rgba(255, 255, 255, 0) 100%)',
          zIndex: 5
        }}
      />

      {renderStepIndicator()}

      <div
        ref={stepRegionRef}
        role="region"
        aria-label={`Paso ${currentStep + 1} de ${steps.length}: ${steps[currentStep]}`}
        tabIndex={-1}
        className="min-h-[400px] p-3 sm:p-6 rounded-lg relative focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-2"
        style={{
          background: 'rgba(255, 255, 255, 0.4)',
          border: '1px solid rgba(255, 255, 255, 0.5)',
          boxShadow: 'inset 0 1px 2px rgba(255,255,255,0.7), 0 1px 3px rgba(0,0,0,0.02)'
        }}
      >
        {currentStep === 0 && (
          <BookingStepService
            storePublicId={store.public_id}
            selectedId={bookingState.serviceId}
            onSelect={(id) => {
              // Con adicionales, tocarlo lo elige y abre su contador: se sigue
              // con la barra. Tocar de nuevo el elegido no borra lo elegido.
              const withAddons = serviceHasAddons(id)
              if (withAddons && id === bookingState.serviceId) return
              if (!withAddons) trackBookingEvent('service_selected')
              updateState({
                serviceId: id,
                extraServiceIds: [],
                // Los adicionales y el descuento son de UN servicio: otro
                // servicio arranca sin ellos.
                ...(id === bookingState.serviceId
                  ? {}
                  : { addons: [], promotionCode: '', promotionPreview: null }),
                requestedStaffId: null,
                assignedStaffId: null,
                assignedStaff: null,
                date: null,
                startTime: null,
                startsAt: null
              })
              if (!withAddons) nextStep()
            }}
            addons={{
              groups: addonGroups,
              onChange: handleAddonChange,
              onContinue: continueFromService
            }}
            multiService={
              multiService
                ? {
                    selectedIds: selectedServiceId
                      ? [selectedServiceId, ...bookingState.extraServiceIds]
                      : [],
                    onToggle: handleToggleService,
                    performers: storeStaff ? publicPerformers(storeStaff) : undefined,
                    onContinue: continueFromService
                  }
                : undefined
            }
          />
        )}

        {currentStep === 1 && selectedServiceId && (
          <BookingStepDateTime
            storePublicId={store.public_id}
            serviceId={selectedServiceId}
            extraServiceIds={bookingState.extraServiceIds}
            staffId={bookingState.requestedStaffId}
            selectedDate={bookingState.date}
            selectedTime={bookingState.startTime}
            onEmptyAvailability={() => trackBookingEvent('availability_empty')}
            onDatePageChange={() =>
              updateState({
                assignedStaffId: null,
                assignedStaff: null,
                date: null,
                startTime: null,
                startsAt: null
              })
            }
            onBack={prevStep}
            onSelect={(date, time, assignedStaffId, requestedStaffId, startsAt, slotStaff) => {
              trackBookingEvent('slot_selected')
              updateState({
                date,
                startTime: time,
                assignedStaffId,
                assignedStaff: slotStaff.name ? slotStaff : null,
                requestedStaffId,
                startsAt
              })
              nextStep()
            }}
          />
        )}

        {currentStep === 2 && selectedServiceId && (
          <BookingStepConfirmation
            storePublicId={store.public_id}
            serviceId={selectedServiceId}
            paymentsEnabled={Boolean(store.feature_flags?.payments)}
            storeName={store.name}
            storeSlug={store.slug}
            whatsappNumber={store.whatsapp_number}
            depositPolicy={store.deposit_policy}
            allowManualCoordination={store.allow_manual_coordination}
            bookingState={bookingState}
            customFields={store.custom_client_fields || []}
            requiresOtp={requiresOtp}
            otpState={otpState}
            isRequestingOtp={requestOtp.isPending}
            otpResendSeconds={resendCooldown.secondsLeft}
            isVerifyingOtp={verifyOtp.isPending}
            onRequestOtp={() => {
              void handleRequestOtp()
            }}
            onVerifyOtp={() => {
              void handleVerifyOtp()
            }}
            // Con el pedido bloqueado, el aviso se queda: sin el, el boton
            // deshabilitado no explica por que.
            onOtpEmailChange={(email) =>
              setOtpState((prev) => ({ ...prev, email, error: prev.rateLimited ? prev.error : '' }))
            }
            onOtpCodeChange={(code) =>
              setOtpState((prev) => ({ ...prev, code, error: prev.rateLimited ? prev.error : '' }))
            }
            onBack={prevStep}
            onClientChange={handleClientChange}
            onPromotionCodeChange={(promotionCode, promotionPreview) =>
              updateState({ promotionCode, promotionPreview })
            }
            onAddonsChange={(addons) => updateState({ addons })}
            // Los adicionales se eligen en el paso del servicio (S4): editarlos
            // vuelve ahi, con lo elegido.
            onEditAddons={() => onStepChange({ to: 0, from: currentStep, mode: 'push' })}
            onConfirm={async (paymentMethod, acceptsTerms, addons) => {
              const pedido = {
                store_public_id: store.public_id,
                service_id: selectedServiceId,
                // Solo si hay: sin ellos el pedido (y su huella) es el de siempre.
                ...(bookingState.extraServiceIds.length
                  ? { extra_service_ids: bookingState.extraServiceIds }
                  : {}),
                staff_id:
                  bookingState.assignedStaffId || bookingState.requestedStaffId || undefined,
                // El instante UTC del slot, tal cual lo devolvio la API: nunca se
                // recompone fecha local + hora (un turno de 21:00 caia en el dia anterior).
                starts_at: bookingState.startsAt ?? '',
                client_name: bookingState.client.name,
                // Opcional sin otp_booking: vacio no viaja.
                client_email: bookingState.client.email.trim() || undefined,
                client_phone: bookingState.client.phone,
                notes: bookingState.client.notes,
                custom_fields: bookingState.client.customFields,
                promotion_code: bookingState.promotionCode || undefined,
                payment_method: paymentMethod,
                accepts_terms: acceptsTerms,
                addons
              }
              // La huella es el pedido entero (servicio, profesional, horario,
              // cliente, promo, adicionales y forma de pago): la clave se reusa al recargar
              // solo si se manda exactamente lo mismo (F4-04). Se guarda solo
              // su SHA-256, sin datos del cliente.
              const idempotencyKey = await bookingIdempotencyKey(store.slug, JSON.stringify(pedido))
              let confirmation
              try {
                confirmation = await createBooking.mutateAsync({
                  ...pedido,
                  idempotency_key: idempotencyKey
                })
              } catch (error) {
                trackBookingEvent('booking_error')
                throw error
              }
              trackBookingCreated(confirmation.public_id)
              forgetBookingIdempotency(store.slug)
              return confirmation
            }}
          />
        )}
      </div>
    </div>
  )
}
