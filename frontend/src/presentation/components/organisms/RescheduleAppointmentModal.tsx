import React, { useState } from 'react'

import { Calendar, Clock, Loader2, X } from 'lucide-react'

import {
  argentinaLocalToUtcIso,
  formatArgentinaDate,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import { FormErrorAlert } from '../molecules/FormErrorAlert'

export interface RescheduleRequest {
  /** Nuevo inicio en UTC (ISO); el dueno tipea hora argentina. */
  newStartsAt: string
  allowOutsideSchedule: boolean
}

interface RescheduleAppointmentModalProps {
  clientName: string
  serviceName: string
  staffName: string
  /** Inicio actual (ISO): precarga fecha y hora. */
  currentStartsAt: string
  /** Solo el administrador puede mover fuera del horario (D-20260929-04). */
  canOverrideSchedule: boolean
  busy: boolean
  error: string | null
  onSubmit: (request: RescheduleRequest) => void
  onClose: () => void
}

const fieldClass = 'w-full rounded-md px-4 py-3 font-bold outline-none text-xs'
const labelClass = 'text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1'

/**
 * Reprogramar un turno desde la agenda (FF-31). Solo pinta y junta fecha y
 * hora: el envio, la idempotencia y los errores los resuelve el contenedor.
 * Se monta al abrirse, asi que el estado inicial ya es el turno a mover.
 */
export const RescheduleAppointmentModal: React.FC<RescheduleAppointmentModalProps> = ({
  clientName,
  serviceName,
  staffName,
  currentStartsAt,
  canOverrideSchedule,
  busy,
  error,
  onSubmit,
  onClose
}) => {
  const [date, setDate] = useState(() => formatArgentinaDate(currentStartsAt))
  const [time, setTime] = useState(() => formatArgentinaTime(currentStartsAt))
  const [allowOutsideSchedule, setAllowOutsideSchedule] = useState(false)

  const newStartsAt = date && time ? argentinaLocalToUtcIso(date, time) : null
  // El panel puede mover a un horario pasado (D-20260925-01), pero entonces
  // el cliente no recibe aviso (D-20260929-07).
  const isPast = newStartsAt !== null && new Date(newStartsAt).getTime() < Date.now()
  const inputStyle = create2000sModalInputStyle()

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!newStartsAt || busy) return
    onSubmit({ newStartsAt, allowOutsideSchedule: canOverrideSchedule && allowOutsideSchedule })
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reschedule-title"
        className="relative w-full max-w-lg rounded-md shadow-2xl flex flex-col overflow-hidden max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div
          className="p-4 sm:p-6 flex justify-between items-center"
          style={{ background: colors2000s.bg.disabled }}
        >
          <div>
            <h3
              id="reschedule-title"
              className="text-xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Reprogramar turno
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              {clientName} · {serviceName} · {staffName}
            </p>
          </div>
          <button
            onClick={onClose}
            type="button"
            aria-label="Cerrar"
            className="p-2.5"
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
          <FormErrorAlert message={error} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label
                htmlFor="reschedule-date"
                className={labelClass}
                style={{ color: colors2000s.text.secondary }}
              >
                <Calendar size={11} /> Nueva fecha
              </label>
              <input
                id="reschedule-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className={fieldClass}
                style={inputStyle}
                required
              />
            </div>
            <div className="space-y-1.5">
              <label
                htmlFor="reschedule-time"
                className={labelClass}
                style={{ color: colors2000s.text.secondary }}
              >
                <Clock size={11} /> Nueva hora
              </label>
              <input
                id="reschedule-time"
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
                className={fieldClass}
                style={inputStyle}
                required
              />
            </div>
          </div>

          {canOverrideSchedule && (
            <label
              className="flex items-start gap-2 text-xs font-bold"
              style={{ color: colors2000s.text.primary }}
            >
              <input
                type="checkbox"
                checked={allowOutsideSchedule}
                onChange={(event) => setAllowOutsideSchedule(event.target.checked)}
                className="mt-0.5"
              />
              Permitir fuera del horario del profesional
            </label>
          )}

          {isPast && (
            <p
              role="status"
              className="rounded-md px-4 py-3 text-xs font-bold"
              style={{ background: '#fff7ed', color: '#c2410c' }}
            >
              Ese horario ya pasó: el cliente no recibe aviso del cambio.
            </p>
          )}

          <div className="flex gap-4 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 font-black uppercase tracking-widest text-xs"
              style={buttonStyles2000s.default}
            >
              Volver
            </button>
            <button
              type="submit"
              disabled={busy || !newStartsAt}
              className="flex-1 font-black py-3 rounded-xl uppercase tracking-widest text-xs disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {busy ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : 'Reprogramar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
