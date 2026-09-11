import React, { useEffect, useMemo, useRef, useState } from 'react'

import { format } from 'date-fns'
import {
  Calendar,
  Clock,
  FileText,
  Loader2,
  Mail,
  Phone,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  User,
  X
} from 'lucide-react'

import type { CreateBookingInput } from '@domain/repositories/IBookingRepository'

import { useCreateAppointment } from '@presentation/hooks/useCalendarAgenda'
import { useManagedServices } from '@presentation/hooks/useManagedServices'
import { useManagedStaff } from '@presentation/hooks/useManagedStaff'
import { useRequestPublicOtp, useVerifyPublicOtp } from '@presentation/hooks/usePublic'
import { useStoreFeatureFlags, useStoreSettings } from '@presentation/hooks/useStores'

import { ConflictError } from '@shared/errors/ConflictError'
import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { createUuid } from '@shared/utils/uuid'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'

interface NewAppointmentModalProps {
  isOpen: boolean
  onClose: () => void
  defaultDate?: Date
}

interface OtpFlowState {
  channel: 'whatsapp' | 'sms'
  code: string
  verified: boolean
  verifiedPhone: string
  debugCode: string
  error: string
}

const emptyOtpState: OtpFlowState = {
  channel: 'whatsapp',
  code: '',
  verified: false,
  verifiedPhone: '',
  debugCode: '',
  error: ''
}

export const NewAppointmentModal: React.FC<NewAppointmentModalProps> = ({
  isOpen,
  onClose,
  defaultDate
}) => {
  const [serviceId, setServiceId] = useState('')
  const [staffId, setStaffId] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [clientName, setClientName] = useState('')
  const [clientPhone, setClientPhone] = useState('')
  const [clientEmail, setClientEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [otpState, setOtpState] = useState<OtpFlowState>(emptyOtpState)

  const { data: services } = useManagedServices()
  const { data: staff } = useManagedStaff()
  const { data: featureFlags } = useStoreFeatureFlags()
  const { data: storeSettings } = useStoreSettings()
  const createAppointment = useCreateAppointment()
  const requestOtp = useRequestPublicOtp()
  const verifyOtp = useVerifyPublicOtp()
  // Guarda contra reenvios concurrentes (doble click/tap antes de que React
  // desmonte el boton via `loading`): ver el mismo fix en
  // BookingStepConfirmation.tsx para el porque no alcanza con el estado solo.
  const isSubmittingRef = useRef(false)

  const requiresOtp = Boolean(featureFlags?.flags.otp_booking)

  useEffect(() => {
    if (!isOpen) return
    setServiceId('')
    setStaffId('')
    setDate(format(defaultDate ?? new Date(), 'yyyy-MM-dd'))
    setTime('')
    setClientName('')
    setClientPhone('')
    setClientEmail('')
    setNotes('')
    setError(null)
    setOtpState(emptyOtpState)
  }, [isOpen, defaultDate])

  const activeServices = useMemo(
    () => (services || []).filter((service) => service.isActive),
    [services]
  )

  // Mismo criterio de calificacion que usa el wizard publico: activo + habilitado
  // para el servicio elegido.
  const qualifiedStaff = useMemo(
    () =>
      (staff || []).filter(
        (member) => member.isActive && (!serviceId || member.serviceIds.includes(serviceId))
      ),
    [staff, serviceId]
  )

  useEffect(() => {
    if (staffId && !qualifiedStaff.some((member) => member.id === staffId)) {
      setStaffId('')
    }
  }, [qualifiedStaff, staffId])

  if (!isOpen) return null

  const showOtpSection = requiresOtp && clientPhone.trim().length >= 6
  // Igual que create_public_booking en el backend: si la tienda exige OTP, el
  // gate no cede hasta que el telefono actual quede verificado.
  const otpVerifiedGate =
    !requiresOtp || (otpState.verified && otpState.verifiedPhone === clientPhone.trim())
  const canSubmit = Boolean(
    serviceId && date && time && clientName.trim() && clientPhone.trim() && otpVerifiedGate
  )

  const handleRequestOtp = async () => {
    if (!storeSettings) return
    try {
      const response = await requestOtp.mutateAsync({
        store_public_id: storeSettings.public_id,
        phone: clientPhone.trim(),
        channel: otpState.channel
      })
      setOtpState((prev) => ({ ...prev, debugCode: response.debug_code || '', error: '' }))
    } catch (err) {
      setOtpState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'No se pudo enviar el codigo')
      }))
    }
  }

  const handleVerifyOtp = async () => {
    if (!storeSettings) return
    try {
      const response = await verifyOtp.mutateAsync({
        store_public_id: storeSettings.public_id,
        phone: clientPhone.trim(),
        code: otpState.code
      })
      setOtpState((prev) => ({
        ...prev,
        verified: true,
        verifiedPhone: response.phone,
        error: ''
      }))
    } catch (err) {
      setOtpState((prev) => ({ ...prev, error: getErrorMessage(err, 'Codigo invalido') }))
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || isSubmittingRef.current) return
    isSubmittingRef.current = true
    setError(null)

    const payload: CreateBookingInput = {
      service_id: serviceId,
      staff_id: staffId || undefined,
      starts_at: `${date}T${time}:00Z`,
      client_name: clientName.trim(),
      client_email: clientEmail.trim() || undefined,
      client_phone: clientPhone.trim(),
      notes: notes.trim() || undefined,
      idempotency_key: createUuid()
    }

    try {
      await createAppointment.mutateAsync(payload)
      onClose()
    } catch (err) {
      // El repositorio traduce el 409 del backend a ConflictError, pero
      // AppointmentService.execute() lo re-envuelve en un Error generico y
      // conserva el original en `originalError` (BaseService.handleError).
      const originalError = (err as { originalError?: unknown } | undefined)?.originalError
      if (originalError instanceof ConflictError) {
        setError('Ese horario ya está ocupado para ese profesional.')
      } else {
        setError(getErrorMessage(err, 'No se pudo crear el turno'))
      }
    } finally {
      isSubmittingRef.current = false
    }
  }

  const inputStyle = { ...create2000sModalInputStyle() }
  const loading = createAppointment.isPending

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-2xl rounded-md shadow-2xl animate-in zoom-in-95 duration-200 flex flex-col overflow-hidden max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div
          className="p-4 sm:p-8 flex justify-between items-center"
          style={{ background: colors2000s.bg.disabled }}
        >
          <div>
            <h3
              className="text-2xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Nuevo Turno
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Reservá un turno manualmente para un cliente.
            </p>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="p-2.5 transition-all"
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e)
          }}
          className="flex-1 overflow-y-auto p-4 sm:p-8 space-y-6"
        >
          {error && (
            <div
              role="alert"
              className="rounded-2xl px-4 py-3 text-xs font-bold flex items-center gap-2"
              style={{ background: '#fff1f2', color: '#be123c' }}
            >
              <TriangleAlert size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label
                className="text-[10px] font-black uppercase tracking-widest ml-1"
                style={{ color: colors2000s.text.secondary }}
              >
                Servicio
              </label>
              <select
                value={serviceId}
                onChange={(e) => setServiceId(e.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
                style={inputStyle}
                required
              >
                <option value="">Seleccionar servicio...</option>
                {activeServices.map((service) => (
                  <option key={service.id} value={service.id}>
                    {service.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <label
                className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
                style={{ color: colors2000s.text.secondary }}
              >
                <Sparkles size={11} /> Profesional
              </label>
              <select
                value={staffId}
                onChange={(e) => setStaffId(e.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
                style={inputStyle}
              >
                <option value="">Cualquiera</option>
                {qualifiedStaff.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.displayName}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label
                className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
                style={{ color: colors2000s.text.secondary }}
              >
                <Calendar size={11} /> Fecha
              </label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
                style={inputStyle}
                required
              />
            </div>
            <div className="space-y-1.5">
              <label
                className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
                style={{ color: colors2000s.text.secondary }}
              >
                <Clock size={11} /> Hora
              </label>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
                style={inputStyle}
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label
                className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
                style={{ color: colors2000s.text.secondary }}
              >
                <User size={11} /> Nombre del cliente
              </label>
              <input
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
                style={inputStyle}
                placeholder="Ej: Juan Pérez"
                required
              />
            </div>
            <div className="space-y-1.5">
              <label
                className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
                style={{ color: colors2000s.text.secondary }}
              >
                <Phone size={11} /> Teléfono
              </label>
              <input
                type="tel"
                value={clientPhone}
                onChange={(e) => setClientPhone(e.target.value)}
                className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
                style={inputStyle}
                placeholder="PREFIJO + NUM"
                required
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label
              className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
              style={{ color: colors2000s.text.secondary }}
            >
              <Mail size={11} /> Email (Opcional)
            </label>
            <input
              type="email"
              value={clientEmail}
              onChange={(e) => setClientEmail(e.target.value)}
              className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs"
              style={inputStyle}
              placeholder="juan@email.com"
            />
          </div>

          <div className="space-y-1.5">
            <label
              className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
              style={{ color: colors2000s.text.secondary }}
            >
              <FileText size={11} /> Notas (Opcional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full rounded-md px-4 py-3 font-bold outline-none text-xs min-h-[80px] resize-none"
              style={inputStyle}
              placeholder="Algo que el negocio deba saber?"
            />
          </div>

          {showOtpSection && (
            <div
              className="rounded-md p-4 space-y-3"
              style={{ background: 'white', border: `1px solid ${colors2000s.border.light}` }}
            >
              <div className="flex items-start gap-2">
                <ShieldCheck
                  size={16}
                  className="mt-0.5"
                  style={{ color: colors2000s.orange.accent }}
                />
                <div>
                  <p
                    className="text-xs font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.primary }}
                  >
                    Verificar teléfono
                  </p>
                  <p
                    className="text-[10px] font-bold"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Esta tienda exige validar el teléfono antes de crear el turno.
                  </p>
                </div>
              </div>

              <div className="grid sm:grid-cols-[1fr_auto] gap-3">
                <select
                  value={otpState.channel}
                  onChange={(e) =>
                    setOtpState((prev) => ({
                      ...prev,
                      channel: e.target.value as 'whatsapp' | 'sms'
                    }))
                  }
                  className="px-4 py-3 rounded-md font-bold outline-none text-xs"
                  style={inputStyle}
                >
                  <option value="whatsapp">WhatsApp</option>
                  <option value="sms">SMS</option>
                </select>
                <button
                  type="button"
                  onClick={() => {
                    void handleRequestOtp()
                  }}
                  disabled={requestOtp.isPending || !storeSettings || !clientPhone.trim()}
                  className="px-4 py-3 text-xs font-black uppercase tracking-widest disabled:opacity-50"
                  style={buttonStyles2000s.default}
                >
                  {requestOtp.isPending ? 'Enviando...' : 'Enviar código'}
                </button>
              </div>

              <input
                value={otpState.code}
                onChange={(e) =>
                  setOtpState((prev) => ({ ...prev, code: e.target.value, error: '' }))
                }
                className="w-full px-4 py-3 rounded-md font-bold outline-none text-xs"
                style={inputStyle}
                placeholder="Ingresá el código OTP"
              />

              {otpState.debugCode && (
                <div
                  className="p-3 rounded-md text-[10px] font-black uppercase tracking-widest"
                  style={{
                    background: colors2000s.status.info.bg,
                    border: `1px solid ${colors2000s.status.info.border}`,
                    color: colors2000s.status.info.text
                  }}
                >
                  Código debug: {otpState.debugCode}
                </div>
              )}

              {otpState.error && (
                <div
                  role="alert"
                  className="p-3 rounded-md text-xs font-bold flex items-center gap-2"
                  style={{
                    background: colors2000s.status.danger.bg,
                    border: `1px solid ${colors2000s.status.danger.border}`,
                    color: colors2000s.status.danger.text
                  }}
                >
                  <TriangleAlert size={14} />
                  {otpState.error}
                </div>
              )}

              {otpState.verified && otpState.verifiedPhone === clientPhone.trim() ? (
                <div
                  className="p-3 rounded-md text-xs font-bold flex items-center gap-2"
                  style={{
                    background: colors2000s.status.success.bg,
                    border: `1px solid ${colors2000s.status.success.border}`,
                    color: colors2000s.status.success.text
                  }}
                >
                  <ShieldCheck size={14} />
                  Teléfono validado correctamente
                </div>
              ) : (
                <button
                  type="button"
                  disabled={!otpState.code || verifyOtp.isPending}
                  onClick={() => {
                    void handleVerifyOtp()
                  }}
                  className="w-full px-4 py-3 rounded-md text-xs font-black uppercase tracking-widest disabled:opacity-50"
                  style={buttonStyles2000s.selected}
                >
                  {verifyOtp.isPending ? 'Verificando...' : 'Verificar código'}
                </button>
              )}
            </div>
          )}
          {requiresOtp && !showOtpSection && (
            <p
              className="text-[10px] font-bold text-center"
              style={{ color: colors2000s.text.secondary }}
            >
              Completá el teléfono del cliente para verificarlo antes de crear el turno.
            </p>
          )}

          <div className="flex gap-4 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-8 py-4 font-black uppercase tracking-widest text-xs transition-all active:scale-95"
              style={buttonStyles2000s.default}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading || !canSubmit}
              className="flex-1 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {loading ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : 'Crear Turno'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default NewAppointmentModal
