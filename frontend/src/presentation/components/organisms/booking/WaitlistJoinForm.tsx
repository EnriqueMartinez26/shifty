import React, { useState } from 'react'

import { BellRing, Check } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { argentinaLocalToUtcIso, formatArgentinaDateDisplay } from '@shared/utils/argentinaTime'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { useJoinWaitlist } from '../../../hooks/usePublic'
import { createBookingInputStyle, createBookingSurfaceStyle } from '../../../lib/surfaceStyles'

interface WaitlistJoinFormProps {
  storePublicId: string
  serviceId: string
  staffId: string | null
  /** Dia elegido (yyyy-MM-dd, hora argentina). La ventana es ese dia entero. */
  date: string
}

/** Ventana de un dia entero en hora argentina, expresada en instantes UTC. */
export const dayWindow = (date: string): { starts: string; ends: string } => ({
  starts: argentinaLocalToUtcIso(date, '00:00'),
  ends: argentinaLocalToUtcIso(date, '23:59')
})

/**
 * "Avisame si se libera un turno": se muestra cuando el dia no tiene cupo.
 * No pide OTP (el backend limita por telefono); el aviso llega por mail a
 * quien deje uno, y el dueno lo ve en su lista de espera igual.
 */
export const WaitlistJoinForm: React.FC<WaitlistJoinFormProps> = ({
  storePublicId,
  serviceId,
  staffId,
  date
}) => {
  const join = useJoinWaitlist()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', phone: '', email: '' })
  const [error, setError] = useState('')
  // El dia al que se anoto, no el que esta mirando: el cartel de exito decia
  // el dia actual y podia afirmar algo falso si el cliente cambiaba de dia.
  const [anotadoPara, setAnotadoPara] = useState<string | null>(null)

  if (join.isSuccess && anotadoPara) {
    return (
      <div
        className="mt-4 rounded-2xl border p-4 flex items-start gap-3"
        style={createBookingSurfaceStyle()}
        role="status"
      >
        <Check className="w-5 h-5 text-emerald-600 mt-0.5" />
        <div>
          <p className="text-xs font-black uppercase tracking-widest text-emerald-700">
            Quedaste en lista de espera
          </p>
          <p className="text-xs font-bold text-gray-500 mt-1">
            Si se libera un turno el {formatArgentinaDateDisplay(dayWindow(anotadoPara).starts)} te
            avisamos{form.email.trim() ? ' por email' : ''}. El cupo se ofrece a una persona por vez
            durante unos minutos.
          </p>
        </div>
      </div>
    )
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-4 w-full py-3 rounded-xl text-[10px] font-black uppercase tracking-widest flex items-center justify-center gap-2"
        style={buttonStyles2000s.default}
      >
        <BellRing className="w-4 h-4" /> Avisame si se libera un turno este dia
      </button>
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    const window = dayWindow(date)
    try {
      await join.mutateAsync({
        store_public_id: storePublicId,
        service_id: serviceId,
        staff_id: staffId,
        window_starts_at: window.starts,
        window_ends_at: window.ends,
        client_name: form.name.trim(),
        client_phone: form.phone.trim(),
        client_email: form.email.trim() || null
      })
      setAnotadoPara(date)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'No pudimos anotarte. Proba de nuevo.'))
    }
  }

  return (
    <form
      onSubmit={(event) => {
        void submit(event)
      }}
      className="mt-4 rounded-2xl border p-4 space-y-3"
      style={createBookingSurfaceStyle()}
    >
      <p
        className="text-[10px] font-black uppercase tracking-widest"
        style={{ color: colors2000s.orange.accent }}
      >
        Lista de espera para el {formatArgentinaDateDisplay(dayWindow(date).starts)}
      </p>
      <input
        required
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.target.value })}
        placeholder="Tu nombre"
        aria-label="Nombre"
        className="w-full rounded-xl px-4 py-3 font-bold outline-none"
        style={createBookingInputStyle()}
      />
      <input
        required
        type="tel"
        inputMode="tel"
        value={form.phone}
        onChange={(e) => setForm({ ...form, phone: e.target.value })}
        placeholder="Tu WhatsApp (ej: 11 5555 0000)"
        aria-label="Telefono"
        className="w-full rounded-xl px-4 py-3 font-bold outline-none"
        style={createBookingInputStyle()}
      />
      <input
        type="email"
        inputMode="email"
        value={form.email}
        onChange={(e) => setForm({ ...form, email: e.target.value })}
        placeholder="Email (para avisarte cuando se libere)"
        aria-label="Email"
        className="w-full rounded-xl px-4 py-3 font-bold outline-none"
        style={createBookingInputStyle()}
      />
      {error && (
        <p role="alert" className="text-xs font-bold text-red-600">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={join.isPending}
        className="w-full py-3 rounded-xl text-white text-[10px] font-black uppercase tracking-widest disabled:opacity-60"
        style={buttonStyles2000s.selected}
      >
        {join.isPending ? 'Anotando...' : 'Anotarme'}
      </button>
    </form>
  )
}
