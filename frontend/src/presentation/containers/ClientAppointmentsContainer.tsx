import React, { useState } from 'react'

import { CalendarClock, Loader2, XCircle } from 'lucide-react'

import type { ClientAppointmentItem, PublicStore } from '@application/services/PublicBookingService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import {
  argentinaLocalToUtcIso,
  formatArgentinaDate,
  formatArgentinaDateDisplay,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'
import { createUuid } from '@shared/utils/uuid'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { ClientOtpGate } from '../components/organisms/ClientOtpGate'
import {
  useCancelClientAppointment,
  usePublicClientAppointments,
  useRescheduleClientAppointment
} from '../hooks/usePublic'
import { createBookingSurfaceStyle } from '../lib/surfaceStyles'

const ESTADO: Record<string, { label: string; color: string }> = {
  pending: { label: 'A confirmar', color: '#d97706' },
  pending_payment: { label: 'Esperando la seña', color: '#d97706' },
  confirmed: { label: 'Confirmado', color: '#15803d' },
  completed: { label: 'Listo', color: '#2563eb' },
  cancelled: { label: 'Cancelado', color: '#dc2626' },
  absent: { label: 'No viniste', color: '#6b7280' },
  expired: { label: 'Vencido', color: '#6b7280' }
}

interface ClientAppointmentsContainerProps {
  store: PublicStore
}

/**
 * "Mis turnos": el cliente ve, cancela y reprograma desde el telefono. Los
 * endpoints existian desde hace tiempo sin ningun consumidor en el front.
 */
export const ClientAppointmentsContainer: React.FC<ClientAppointmentsContainerProps> = ({
  store
}) => {
  const [phone, setPhone] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [rescheduling, setRescheduling] = useState<{
    id: string
    date: string
    time: string
  } | null>(null)
  const appointments = usePublicClientAppointments(store.public_id, phone ?? '', Boolean(phone))
  const cancelAppointment = useCancelClientAppointment()
  const rescheduleAppointment = useRescheduleClientAppointment()

  if (!phone) {
    return (
      <ClientOtpGate storePublicId={store.public_id} storeSlug={store.slug} onVerified={setPhone} />
    )
  }

  const cancelar = async (item: ClientAppointmentItem) => {
    setMessage('')
    try {
      await cancelAppointment.mutateAsync({ publicId: item.public_id, phone })
      setMessage('Cancelamos tu turno y le avisamos a la tienda.')
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No pudimos cancelar el turno'))
    }
  }

  const reprogramar = async (item: ClientAppointmentItem) => {
    if (!rescheduling) return
    setMessage('')
    try {
      await rescheduleAppointment.mutateAsync({
        publicId: item.public_id,
        phone,
        newStartsAt: argentinaLocalToUtcIso(rescheduling.date, rescheduling.time),
        idempotencyKey: createUuid()
      })
      setRescheduling(null)
      setMessage('Listo, movimos tu turno.')
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No pudimos mover el turno a ese horario'))
    }
  }

  const items = appointments.data?.appointments ?? []

  return (
    <section className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2
          className="text-lg font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.accent }}
        >
          Mis turnos
        </h2>
        <button
          type="button"
          onClick={() => setPhone(null)}
          className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
          style={buttonStyles2000s.default}
        >
          Salir
        </button>
      </div>

      {message && (
        <p role="status" className="text-xs font-bold" style={{ color: colors2000s.text.primary }}>
          {message}
        </p>
      )}

      {appointments.isLoading && (
        <p className="flex items-center gap-2 text-xs font-black uppercase tracking-widest text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin" /> Buscando tus turnos...
        </p>
      )}

      {appointments.isError && (
        <p role="alert" className="text-xs font-bold text-red-600">
          No encontramos turnos para ese teléfono en {store.name}.
        </p>
      )}

      {!appointments.isLoading && !appointments.isError && items.length === 0 && (
        <p className="text-xs font-bold text-gray-500">Todavía no tenés turnos acá.</p>
      )}

      {items.map((item) => {
        const estado = ESTADO[item.status] ?? { label: item.status, color: '#6b7280' }
        const editando = rescheduling?.id === item.public_id
        return (
          <article
            key={item.public_id}
            className="rounded-2xl p-4 space-y-3"
            style={createBookingSurfaceStyle()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-black text-sm">{item.service_name}</p>
                <p className="text-[11px] font-bold text-gray-500">
                  {formatArgentinaDateDisplay(item.starts_at)} a las{' '}
                  {formatArgentinaTime(item.starts_at)} hs · {item.staff_name}
                </p>
              </div>
              <span
                className="text-[9px] font-black uppercase tracking-widest whitespace-nowrap"
                style={{ color: estado.color }}
              >
                {estado.label}
              </span>
            </div>

            {(item.can_cancel || item.can_reschedule) && (
              <div className="flex flex-wrap gap-2">
                {item.can_reschedule && (
                  <button
                    type="button"
                    onClick={() =>
                      setRescheduling(
                        editando
                          ? null
                          : {
                              id: item.public_id,
                              // El dia LOCAL del turno: slice(0,10) del ISO da
                              // el dia UTC y corre el turno de la noche.
                              date: formatArgentinaDate(item.starts_at),
                              time: formatArgentinaTime(item.starts_at)
                            }
                      )
                    }
                    className="inline-flex items-center gap-1 rounded-lg px-3 py-2 text-[9px] font-black uppercase tracking-widest"
                    style={buttonStyles2000s.default}
                  >
                    <CalendarClock className="w-3 h-3" /> Cambiar
                  </button>
                )}
                {item.can_cancel && (
                  <button
                    type="button"
                    disabled={cancelAppointment.isPending}
                    onClick={() => {
                      void cancelar(item)
                    }}
                    className="inline-flex items-center gap-1 rounded-lg px-3 py-2 text-[9px] font-black uppercase tracking-widest disabled:opacity-50"
                    style={{ ...buttonStyles2000s.default, color: '#dc2626' }}
                  >
                    <XCircle className="w-3 h-3" /> Cancelar
                  </button>
                )}
              </div>
            )}

            {editando && rescheduling && (
              <div className="grid grid-cols-[1fr_auto_auto] gap-2 items-end">
                <label className="text-[9px] font-black uppercase tracking-widest text-gray-500">
                  Nueva fecha
                  <input
                    type="date"
                    value={rescheduling.date}
                    onChange={(e) => setRescheduling({ ...rescheduling, date: e.target.value })}
                    className="mt-1 w-full rounded-lg px-2 py-2 text-xs font-bold border"
                    style={{ borderColor: colors2000s.border.default }}
                  />
                </label>
                <label className="text-[9px] font-black uppercase tracking-widest text-gray-500">
                  Hora
                  <input
                    type="time"
                    value={rescheduling.time}
                    onChange={(e) => setRescheduling({ ...rescheduling, time: e.target.value })}
                    className="mt-1 rounded-lg px-2 py-2 text-xs font-bold border"
                    style={{ borderColor: colors2000s.border.default }}
                  />
                </label>
                <button
                  type="button"
                  disabled={rescheduleAppointment.isPending}
                  onClick={() => {
                    void reprogramar(item)
                  }}
                  className="px-4 py-2 rounded-lg text-white text-[9px] font-black uppercase tracking-widest disabled:opacity-60"
                  style={buttonStyles2000s.selected}
                >
                  {rescheduleAppointment.isPending ? '...' : 'Mover'}
                </button>
              </div>
            )}
          </article>
        )
      })}
    </section>
  )
}
