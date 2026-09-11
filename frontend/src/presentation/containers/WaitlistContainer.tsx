import React, { useState } from 'react'

import { CalendarPlus, Clock, Loader2, MessageCircle, Trash2 } from 'lucide-react'

import type { WaitlistEntry } from '@application/services/WaitlistService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import {
  argentinaLocalToUtcIso,
  formatArgentinaDate,
  formatArgentinaDateDisplay,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'
import { buildRebookUrl, buildWaMeUrl } from '@shared/utils/clientWhatsApp'
import { buildWaitlistMessage } from '@shared/utils/waitlistWhatsApp'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { useAuth } from '../context/AuthContext'
import { useStoreSettings } from '../hooks/useStores'
import { useBookFromWaitlist, useRemoveWaitlistEntry, useWaitlist } from '../hooks/useWaitlist'

const STATUS_LABEL: Record<string, string> = {
  waiting: 'En espera',
  offered: 'Cupo ofrecido'
}

/**
 * Lista de espera del dueno: es el canal principal (el mail solo llega a
 * quien dejo uno). Telefono con link wa.me y alta directa del turno, que no
 * exige antelacion minima porque la hace la tienda.
 */
export const WaitlistContainer: React.FC = () => {
  const { user } = useAuth()
  const canManage = user?.role === 'admin' || Boolean(user?.is_global_admin)
  const waitlist = useWaitlist()
  const { data: storeSettings } = useStoreSettings()
  const removeEntry = useRemoveWaitlistEntry()
  const bookEntry = useBookFromWaitlist()
  const [booking, setBooking] = useState<{ entryId: string; date: string; time: string } | null>(
    null
  )
  const [message, setMessage] = useState('')

  const entries = waitlist.data ?? []

  const startBooking = (entry: WaitlistEntry) => {
    const base = entry.offered_starts_at ?? entry.window_starts_at
    setBooking({
      entryId: entry.public_id,
      date: formatArgentinaDate(base),
      time: entry.offered_starts_at ? formatArgentinaTime(entry.offered_starts_at) : '10:00'
    })
    setMessage('')
  }

  const confirmBooking = async (entry: WaitlistEntry) => {
    if (!booking) return
    try {
      await bookEntry.mutateAsync({
        entryId: entry.public_id,
        payload: {
          starts_at: argentinaLocalToUtcIso(booking.date, booking.time),
          staff_id: entry.staff_id ?? entry.offered_staff_id ?? null
        }
      })
      setBooking(null)
      setMessage(`Turno reservado para ${entry.client_name}. Le mandamos la confirmacion.`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo reservar ese horario'))
    }
  }

  const whatsappHref = (entry: WaitlistEntry): string | null => {
    if (!entry.client_phone) return null
    const bookingUrl = storeSettings?.slug
      ? buildRebookUrl(
          window.location.origin,
          storeSettings.slug,
          entry.service_id,
          entry.staff_id ?? entry.offered_staff_id ?? ''
        )
      : null
    return buildWaMeUrl(
      entry.client_phone,
      buildWaitlistMessage({
        clientName: entry.client_name,
        serviceName: entry.service_name,
        staffName: entry.staff_name,
        windowStartsAt: entry.offered_starts_at ?? entry.window_starts_at,
        storeName: storeSettings?.name ?? '',
        bookingUrl
      })
    )
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-700">
      <div
        className="flex flex-wrap gap-4 items-center justify-between p-6 rounded-3xl"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
        }}
      >
        <div>
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Lista de espera
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Cuando se libera un cupo, se le ofrece a una persona por vez. Desde aca podes avisar por
            WhatsApp o reservarle el turno directamente.
          </p>
        </div>
        <span
          className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
          style={{ background: 'white', border: `1px solid ${colors2000s.border.default}` }}
        >
          {waitlist.isError ? 'Sin datos' : `${entries.length} en espera`}
        </span>
      </div>

      {message && (
        <p
          role="status"
          className="text-xs font-bold px-2"
          style={{ color: colors2000s.text.primary }}
        >
          {message}
        </p>
      )}

      {waitlist.isLoading ? (
        <div className="flex items-center gap-2 text-xs font-black uppercase tracking-widest text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin" /> Cargando lista de espera...
        </div>
      ) : waitlist.isError ? (
        // Un error no es una lista vacia: decir "nadie en espera" cuando la
        // consulta fallo le hace perder clientes al duenio sin que se entere.
        <div
          role="alert"
          className="rounded-3xl p-10 text-center"
          style={{ background: 'white', border: `1px solid ${colors2000s.border.default}` }}
        >
          <p className="text-xs font-black uppercase tracking-widest text-red-600">
            No pudimos cargar la lista de espera
          </p>
          <p className="text-xs font-bold text-gray-500 mt-2">
            Actualizá la página en unos instantes.
          </p>
        </div>
      ) : entries.length === 0 ? (
        <div
          className="rounded-3xl p-10 text-center"
          style={{ background: 'white', border: `1px solid ${colors2000s.border.default}` }}
        >
          <Clock className="w-10 h-10 mx-auto text-gray-300 mb-3" />
          <p className="text-xs font-black uppercase tracking-widest text-gray-400">
            Nadie en lista de espera
          </p>
          <p className="text-xs font-bold text-gray-400 mt-2">
            Los clientes se anotan desde tu pagina publica cuando un dia no tiene cupo.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {entries.map((entry) => {
            const href = whatsappHref(entry)
            const isBookingThis = booking?.entryId === entry.public_id
            return (
              <div
                key={entry.public_id}
                className="rounded-3xl p-5 space-y-3"
                style={{
                  background: 'white',
                  border: `1px solid ${colors2000s.border.default}`,
                  boxShadow: colors2000s.shadows.outer
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-black text-sm uppercase tracking-tight truncate">
                      {entry.client_name}
                    </p>
                    <p className="text-[10px] font-bold text-gray-500">
                      {entry.service_name} · {entry.staff_name ?? 'Cualquier profesional'}
                    </p>
                    <p className="text-[10px] font-bold text-gray-500">
                      Quiere el {formatArgentinaDateDisplay(entry.window_starts_at)}
                      {entry.client_phone ? ` · ${entry.client_phone}` : ''}
                    </p>
                  </div>
                  <span
                    className="px-2 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest whitespace-nowrap"
                    style={{
                      background: entry.status === 'offered' ? '#fef3c7' : '#ecfdf5',
                      color: entry.status === 'offered' ? '#92400e' : '#166534'
                    }}
                  >
                    {STATUS_LABEL[entry.status] ?? entry.status}
                  </span>
                </div>

                {entry.status === 'offered' && entry.offered_starts_at && (
                  <p className="text-[10px] font-bold text-amber-700">
                    Se le ofrecio el {formatArgentinaDateDisplay(entry.offered_starts_at)} a las{' '}
                    {formatArgentinaTime(entry.offered_starts_at)} hs
                    {entry.offer_expires_at
                      ? ` (hasta las ${formatArgentinaTime(entry.offer_expires_at)})`
                      : ''}
                    .
                  </p>
                )}
                {entry.notes && (
                  <p className="text-[10px] font-medium text-gray-500 italic">"{entry.notes}"</p>
                )}

                <div
                  className="flex flex-wrap gap-2 pt-2 border-t"
                  style={{ borderColor: colors2000s.border.light }}
                >
                  {href && (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 rounded-lg bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest border text-green-700 border-green-200"
                    >
                      <MessageCircle className="w-3 h-3" /> WhatsApp
                    </a>
                  )}
                  {canManage && (
                    <>
                      <button
                        type="button"
                        onClick={() => (isBookingThis ? setBooking(null) : startBooking(entry))}
                        className="inline-flex items-center gap-1 rounded-lg bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest border text-blue-700 border-blue-200"
                      >
                        <CalendarPlus className="w-3 h-3" /> Reservar
                      </button>
                      <button
                        type="button"
                        disabled={removeEntry.isPending}
                        onClick={() => {
                          void removeEntry.mutateAsync(entry.public_id)
                        }}
                        className="inline-flex items-center gap-1 rounded-lg bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest border text-red-700 border-red-200 disabled:opacity-50"
                      >
                        <Trash2 className="w-3 h-3" /> Quitar
                      </button>
                    </>
                  )}
                </div>

                {isBookingThis && booking && (
                  <div className="grid grid-cols-[1fr_auto_auto] gap-2 items-end">
                    <label className="text-[9px] font-black uppercase tracking-widest text-gray-500">
                      Fecha
                      <input
                        type="date"
                        value={booking.date}
                        onChange={(e) => setBooking({ ...booking, date: e.target.value })}
                        className="mt-1 w-full rounded-lg px-2 py-2 text-xs font-bold border"
                        style={{ borderColor: colors2000s.border.default }}
                      />
                    </label>
                    <label className="text-[9px] font-black uppercase tracking-widest text-gray-500">
                      Hora
                      <input
                        type="time"
                        value={booking.time}
                        onChange={(e) => setBooking({ ...booking, time: e.target.value })}
                        className="mt-1 rounded-lg px-2 py-2 text-xs font-bold border"
                        style={{ borderColor: colors2000s.border.default }}
                      />
                    </label>
                    <button
                      type="button"
                      disabled={bookEntry.isPending}
                      onClick={() => {
                        void confirmBooking(entry)
                      }}
                      className="px-4 py-2 rounded-lg text-white text-[9px] font-black uppercase tracking-widest disabled:opacity-60"
                      style={buttonStyles2000s.selected}
                    >
                      {bookEntry.isPending ? '...' : 'Confirmar'}
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
