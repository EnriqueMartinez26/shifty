import React, { useRef, useState } from 'react'

import { format } from 'date-fns'
import {
  Calendar,
  Clock,
  FileText,
  Loader2,
  Mail,
  Phone,
  Sparkles,
  TriangleAlert,
  User,
  X
} from 'lucide-react'

import type { CreateBookingInput } from '@domain/repositories/IBookingRepository'

import { useCreateAppointment } from '@presentation/hooks/useCalendarAgenda'
import { useManagedServices } from '@presentation/hooks/useManagedServices'
import { useManagedStaff } from '@presentation/hooks/useManagedStaff'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { argentinaLocalToUtcIso } from '@shared/utils/argentinaTime'
import { createUuid } from '@shared/utils/uuid'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'

interface NewAppointmentModalProps {
  onClose: () => void
  defaultDate?: Date
  /**
   * El profesional solo carga turnos en su propia agenda: el backend le
   * responde 403 con otro `staff_id` y, sin ninguno, le asigna el suyo.
   */
  isProfessional?: boolean
}

type BookingDraft = Omit<CreateBookingInput, 'idempotency_key'>

const fieldClass = 'w-full rounded-md px-4 py-3 font-bold outline-none text-xs'

const Field: React.FC<{ icon?: React.ReactNode; label: string; children: React.ReactNode }> = ({
  icon,
  label,
  children
}) => (
  <div className="space-y-1.5">
    <label
      className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
      style={{ color: colors2000s.text.secondary }}
    >
      {icon} {label}
    </label>
    {children}
  </div>
)

/**
 * Envio del alta con idempotencia por intento: un reintento con los MISMOS
 * datos (respuesta perdida, 409 transitorio) reusa la clave y el backend
 * devuelve el turno ya creado; si el formulario cambio, clave nueva, porque
 * reusarla devolveria el turno viejo cacheado en vez de crear el pedido.
 */
const useNewAppointmentSubmit = (onClose: () => void) => {
  const createAppointment = useCreateAppointment()
  const [error, setError] = useState<string | null>(null)
  // Guarda contra doble click antes de que `isPending` deshabilite el boton
  // (mismo fix que BookingStepConfirmation.tsx).
  const isSubmittingRef = useRef(false)
  const lastAttemptRef = useRef<{ fp: string; key: string } | null>(null)

  const submit = async (draft: BookingDraft) => {
    if (isSubmittingRef.current) return
    isSubmittingRef.current = true
    setError(null)

    const fp = JSON.stringify(draft)
    const key = lastAttemptRef.current?.fp === fp ? lastAttemptRef.current.key : createUuid()
    lastAttemptRef.current = { fp, key }

    try {
      await createAppointment.mutateAsync({ ...draft, idempotency_key: key })
      onClose()
    } catch (err) {
      setError(getErrorMessage(err, 'No se pudo crear el turno.'))
    } finally {
      isSubmittingRef.current = false
    }
  }

  return { submit, error, loading: createAppointment.isPending }
}

export const NewAppointmentModal: React.FC<NewAppointmentModalProps> = ({
  onClose,
  defaultDate,
  isProfessional = false
}) => {
  // El modal se monta al abrirse: el estado inicial ya es el formulario limpio.
  const [serviceId, setServiceId] = useState('')
  const [staffId, setStaffId] = useState('')
  const [date, setDate] = useState(() => format(defaultDate ?? new Date(), 'yyyy-MM-dd'))
  const [time, setTime] = useState('')
  const [clientName, setClientName] = useState('')
  const [clientPhone, setClientPhone] = useState('')
  const [clientEmail, setClientEmail] = useState('')
  const [notes, setNotes] = useState('')

  const { data: services } = useManagedServices()
  const { data: staff } = useManagedStaff()
  const { submit, error, loading } = useNewAppointmentSubmit(onClose)

  const activeServices = (services || []).filter((service) => service.isActive)
  // Mismo criterio que el wizard publico: activo + habilitado para el servicio.
  const qualifiedStaff = (staff || []).filter(
    (member) => member.isActive && (!serviceId || member.serviceIds.includes(serviceId))
  )
  // Un profesional elegido que deja de calificar al cambiar el servicio vuelve
  // a "Cualquiera" sin efecto: se deriva en el render.
  const effectiveStaffId = qualifiedStaff.some((member) => member.id === staffId) ? staffId : ''
  const canSubmit = Boolean(serviceId && date && time && clientName.trim() && clientPhone.trim())

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    void submit({
      service_id: serviceId,
      staff_id: effectiveStaffId || undefined,
      // El dueno tipea hora ARGENTINA (F11a-01): este es el conversor
      // sancionado para horas libres (reglas de tiempo de CLAUDE.md). Se
      // aceptan fechas pasadas para cargar turnos atrasados (D-20260925-01).
      starts_at: argentinaLocalToUtcIso(date, time),
      client_name: clientName.trim(),
      client_email: clientEmail.trim() || undefined,
      client_phone: clientPhone.trim(),
      notes: notes.trim() || undefined
    })
  }

  const inputStyle = create2000sModalInputStyle()

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

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 sm:p-8 space-y-6">
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
            <Field label="Servicio">
              <select
                value={serviceId}
                onChange={(e) => setServiceId(e.target.value)}
                className={fieldClass}
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
            </Field>
            {!isProfessional && (
              <Field icon={<Sparkles size={11} />} label="Profesional">
                <select
                  value={effectiveStaffId}
                  onChange={(e) => setStaffId(e.target.value)}
                  className={fieldClass}
                  style={inputStyle}
                >
                  <option value="">Cualquiera</option>
                  {qualifiedStaff.map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.displayName}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field icon={<Calendar size={11} />} label="Fecha">
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className={fieldClass}
                style={inputStyle}
                required
              />
            </Field>
            <Field icon={<Clock size={11} />} label="Hora">
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className={fieldClass}
                style={inputStyle}
                required
              />
            </Field>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field icon={<User size={11} />} label="Nombre del cliente">
              <input
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                className={fieldClass}
                style={inputStyle}
                placeholder="Ej: Juan Pérez"
                required
              />
            </Field>
            <Field icon={<Phone size={11} />} label="Teléfono">
              <input
                type="tel"
                value={clientPhone}
                onChange={(e) => setClientPhone(e.target.value)}
                className={fieldClass}
                style={inputStyle}
                placeholder="PREFIJO + NUM"
                required
              />
            </Field>
          </div>

          <Field icon={<Mail size={11} />} label="Email (Opcional)">
            <input
              type="email"
              value={clientEmail}
              onChange={(e) => setClientEmail(e.target.value)}
              className={fieldClass}
              style={inputStyle}
              placeholder="juan@email.com"
            />
          </Field>

          <Field icon={<FileText size={11} />} label="Notas (Opcional)">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className={`${fieldClass} min-h-[80px] resize-none`}
              style={inputStyle}
              placeholder="Algo que el negocio deba saber?"
            />
          </Field>

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
