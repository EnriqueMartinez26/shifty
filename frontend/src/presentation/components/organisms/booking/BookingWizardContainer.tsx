import React, { useEffect, useMemo, useState } from 'react'

import { Check } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { rememberOtpVerification } from '@shared/utils/otpSession'

import { BookingStepConfirmation } from './BookingStepConfirmation'
import { BookingStepDateTime } from './BookingStepDateTime'
import { BookingStepService } from './BookingStepService'
import { EMPTY_PRESELECT, type BookingPreselect } from './deepLink'
import type { BookingOtpState, BookingWizardState } from './types'
import { createUuid } from '../../../../shared/utils/uuid'
import { colors2000s } from '../../../../theme/colors'
import {
  type PublicStore,
  useCreatePublicBooking,
  useRequestPublicOtp,
  useVerifyPublicOtp
} from '../../../hooks/usePublic'
import { createBookingSurfaceStyle } from '../../../lib/surfaceStyles'

interface BookingWizardContainerProps {
  store: PublicStore
  /** Servicio y profesional ya validados contra las listas publicas (deep-link). */
  preselect?: BookingPreselect
}

export const BookingWizardContainer: React.FC<BookingWizardContainerProps> = ({
  store,
  preselect = EMPTY_PRESELECT
}) => {
  const requiresOtp = Boolean(store.feature_flags?.otp_booking)
  const initialCustomFields = useMemo(
    () => Object.fromEntries((store.custom_client_fields || []).map((field) => [field.key, ''])),
    [store.custom_client_fields]
  )
  // Siempre 3 pasos, incluidas las tiendas con OTP: el paso de validacion se
  // muestra como sub-fase dentro de "Datos y Confirmacion" en vez de ocupar
  // un paso propio.
  const steps = useMemo(() => ['Servicio', 'Horario y Profesional', 'Datos y Confirmacion'], [])

  const [currentStep, setCurrentStep] = useState(0)
  const [otpState, setOtpState] = useState<BookingOtpState>({
    code: '',
    channel: 'whatsapp',
    verified: false,
    verifiedPhone: '',
    debugCode: '',
    expiresAt: '',
    error: ''
  })
  const [bookingState, setBookingState] = useState<BookingWizardState>({
    serviceId: preselect.serviceId,
    requestedStaffId: preselect.staffId,
    assignedStaffId: null,
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
    idempotencyKey: createUuid()
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

  const updateState = (updates: Partial<typeof bookingState>) => {
    setBookingState((prev) => ({ ...prev, ...updates }))
  }

  const nextStep = () => setCurrentStep((prev) => Math.min(prev + 1, steps.length - 1))
  const prevStep = () => setCurrentStep((prev) => Math.max(prev - 1, 0))

  const handleClientChange = (client: BookingWizardState['client']) => {
    updateState({ client })
    // Una verificacion de OTP queda atada al telefono que se valido. Si el
    // usuario lo edita despues de verificar, el gate vuelve a cerrarse para
    // ese telefono nuevo (create_public_booking la exige de nuevo en el
    // backend; esto solo evita mostrar un estado "verificado" enganoso).
    setOtpState((prev) =>
      prev.verified && client.phone !== prev.verifiedPhone
        ? { ...prev, verified: false, code: '', debugCode: '', error: '' }
        : prev
    )
  }

  const handleRequestOtp = async () => {
    try {
      const response = await requestOtp.mutateAsync({
        store_public_id: store.public_id,
        phone: bookingState.client.phone,
        channel: otpState.channel
      })
      setOtpState((prev) => ({
        ...prev,
        debugCode: response.debug_code || '',
        expiresAt: response.expires_at,
        error: ''
      }))
    } catch (error: unknown) {
      setOtpState((prev) => ({
        ...prev,
        error: getErrorMessage(error, 'No se pudo enviar el codigo')
      }))
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
        error: getErrorMessage(error, 'Codigo invalido')
      }))
    }
  }

  const renderStepIndicator = () => (
    <div
      className="flex items-center justify-between p-4 mb-8 relative overflow-hidden"
      style={createBookingSurfaceStyle()}
    >
      {steps.map((label, i) => {
        const isCompleted = i < currentStep
        const isActive = i === currentStep

        return (
          <React.Fragment key={label}>
            <div className="flex flex-col items-center gap-1 z-10 flex-1">
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-black transition-all cursor-default select-none"
                style={{
                  background: isCompleted
                    ? `linear-gradient(180deg, ${colors2000s.status.success.light} 0%, ${colors2000s.status.success.dark} 100%)`
                    : isActive
                      ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
                      : `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.disabledBottom} 100%)`,
                  boxShadow: isCompleted
                    ? `${colors2000s.shadows.insetLight}, 0 2px 4px rgba(16,185,129,0.3)`
                    : isActive
                      ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                      : `${colors2000s.shadows.insetLight}, 0 1px 2px rgba(0,0,0,0.05)`,
                  color: isCompleted || isActive ? '#ffffff' : colors2000s.text.secondary
                }}
              >
                {isCompleted ? <Check className="w-4 h-4 font-black" /> : i + 1}
              </div>
              <span
                className={`text-[9px] uppercase tracking-wider hidden md:block mt-1 font-black text-center ${isActive ? 'text-orange-600' : isCompleted ? 'text-green-600' : 'text-gray-400'}`}
              >
                {label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div
                className="h-1 flex-1 mx-2 rounded-full transition-all"
                style={{
                  background: isCompleted
                    ? `linear-gradient(90deg, ${colors2000s.status.success.dark} 0%, ${colors2000s.status.success.light} 100%)`
                    : colors2000s.bg.disabled,
                  boxShadow: isCompleted ? 'none' : 'inset 0 1px 1px rgba(0,0,0,0.1)'
                }}
              />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )

  // Todos los pasos posteriores al primero requieren un servicio elegido. La
  // guarda en el JSX convierte esa invariante en un chequeo del compilador en
  // lugar de un "!" que promete sin verificar.
  const selectedServiceId = bookingState.serviceId

  return (
    <div
      className="max-w-2xl mx-auto rounded-lg p-8 relative overflow-hidden animate-in fade-in zoom-in-95 duration-700"
      style={{
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
        className="min-h-[400px] p-6 rounded-lg relative"
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
              updateState({
                serviceId: id,
                requestedStaffId: null,
                assignedStaffId: null,
                date: null,
                startTime: null,
                startsAt: null
              })
              nextStep()
            }}
          />
        )}

        {currentStep === 1 && selectedServiceId && (
          <BookingStepDateTime
            storePublicId={store.public_id}
            serviceId={selectedServiceId}
            staffId={bookingState.requestedStaffId}
            selectedDate={bookingState.date}
            selectedTime={bookingState.startTime}
            onBack={prevStep}
            onSelect={(date, time, assignedStaffId, requestedStaffId, startsAt) => {
              updateState({ date, startTime: time, assignedStaffId, requestedStaffId, startsAt })
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
            isVerifyingOtp={verifyOtp.isPending}
            onRequestOtp={() => {
              void handleRequestOtp()
            }}
            onVerifyOtp={() => {
              void handleVerifyOtp()
            }}
            onOtpChannelChange={(channel) => setOtpState((prev) => ({ ...prev, channel }))}
            onOtpCodeChange={(code) => setOtpState((prev) => ({ ...prev, code, error: '' }))}
            onBack={prevStep}
            onClientChange={handleClientChange}
            onPromotionCodeChange={(promotionCode) => updateState({ promotionCode })}
            onConfirm={async (paymentMethod, acceptsTerms) =>
              await createBooking.mutateAsync({
                store_public_id: store.public_id,
                service_id: selectedServiceId,
                staff_id:
                  bookingState.assignedStaffId || bookingState.requestedStaffId || undefined,
                // El instante UTC del slot, tal cual lo devolvio la API: nunca se
                // recompone fecha local + hora (un turno de 21:00 caia en el dia anterior).
                starts_at: bookingState.startsAt ?? '',
                client_name: bookingState.client.name,
                client_email: bookingState.client.email || undefined,
                client_phone: bookingState.client.phone,
                notes: bookingState.client.notes,
                custom_fields: bookingState.client.customFields,
                promotion_code: bookingState.promotionCode || undefined,
                payment_method: paymentMethod,
                accepts_terms: acceptsTerms,
                idempotency_key: bookingState.idempotencyKey
              })
            }
          />
        )}
      </div>
    </div>
  )
}

export default BookingWizardContainer
