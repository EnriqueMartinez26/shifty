import React, { useState } from 'react'

import { ShieldCheck } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { isOtpStillValid, rememberOtpVerification } from '@shared/utils/otpSession'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { useRequestPublicOtp, useVerifyPublicOtp } from '../../hooks/usePublic'
import { createBookingInputStyle, createBookingSurfaceStyle } from '../../lib/surfaceStyles'

interface ClientOtpGateProps {
  storePublicId: string
  storeSlug: string
  /** Se llama con el telefono normalizado cuando queda verificado. */
  onVerified: (phone: string) => void
}

/**
 * Puerta de "Mis turnos": telefono + codigo por email. Si el telefono ya se
 * verifico en este dispositivo dentro de la ventana que acepta el backend
 * (30 min), entra directo sin gastar un codigo.
 */
export const ClientOtpGate: React.FC<ClientOtpGateProps> = ({
  storePublicId,
  storeSlug,
  onVerified
}) => {
  const requestOtp = useRequestPublicOtp()
  const verifyOtp = useVerifyPublicOtp()
  const [form, setForm] = useState({ phone: '', email: '', code: '' })
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const continuarSiYaVerificado = (): boolean => {
    if (!form.phone.trim() || !isOtpStillValid(storeSlug, form.phone)) return false
    onVerified(form.phone.trim())
    return true
  }

  const pedirCodigo = async () => {
    setError('')
    if (continuarSiYaVerificado()) return
    if (!form.email.trim()) {
      setError('Ingresá el email donde querés recibir el código')
      return
    }
    try {
      await requestOtp.mutateAsync({
        store_public_id: storePublicId,
        phone: form.phone.trim(),
        channel: 'email',
        email: form.email.trim()
      })
      setSent(true)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'No pudimos enviar el código'))
    }
  }

  const verificar = async () => {
    setError('')
    try {
      const response = await verifyOtp.mutateAsync({
        store_public_id: storePublicId,
        phone: form.phone.trim(),
        code: form.code.trim()
      })
      rememberOtpVerification(storeSlug, response.phone, response.verified_at)
      onVerified(response.phone)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Código inválido'))
    }
  }

  return (
    <section
      className="max-w-md mx-auto rounded-[2rem] p-6 space-y-4"
      style={createBookingSurfaceStyle()}
    >
      <div className="flex items-start gap-3">
        <ShieldCheck className="w-6 h-6 mt-0.5 text-orange-500" />
        <div>
          <h2
            className="text-lg font-black uppercase tracking-tight"
            style={{ color: colors2000s.orange.accent }}
          >
            Mis turnos
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Poné tu teléfono y te mandamos un código por email para ver tus turnos.
          </p>
        </div>
      </div>

      <input
        type="tel"
        inputMode="tel"
        value={form.phone}
        onChange={(e) => setForm({ ...form, phone: e.target.value })}
        placeholder="Tu teléfono (ej: 11 5555 0000)"
        aria-label="Teléfono"
        className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
        style={createBookingInputStyle()}
      />

      {!sent && (
        <>
          <input
            type="email"
            inputMode="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            placeholder="tu@email.com"
            aria-label="Email para recibir el código"
            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
            style={createBookingInputStyle()}
          />
          <button
            type="button"
            disabled={requestOtp.isPending || !form.phone.trim()}
            onClick={() => {
              void pedirCodigo()
            }}
            className="w-full py-3 rounded-2xl text-white text-xs font-black uppercase tracking-widest disabled:opacity-60"
            style={buttonStyles2000s.selected}
          >
            {requestOtp.isPending ? 'Enviando...' : 'Enviarme el código'}
          </button>
        </>
      )}

      {sent && (
        <>
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            placeholder="Código que te llegó por email"
            aria-label="Código"
            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
            style={createBookingInputStyle()}
          />
          <button
            type="button"
            disabled={verifyOtp.isPending || !form.code.trim()}
            onClick={() => {
              void verificar()
            }}
            className="w-full py-3 rounded-2xl text-white text-xs font-black uppercase tracking-widest disabled:opacity-60"
            style={buttonStyles2000s.selected}
          >
            {verifyOtp.isPending ? 'Verificando...' : 'Ver mis turnos'}
          </button>
          <button
            type="button"
            onClick={() => setSent(false)}
            className="w-full py-2 rounded-2xl text-[10px] font-black uppercase tracking-widest"
            style={buttonStyles2000s.default}
          >
            Cambiar teléfono o email
          </button>
        </>
      )}

      {error && (
        <p role="alert" className="text-xs font-bold text-red-600">
          {error}
        </p>
      )}
    </section>
  )
}
