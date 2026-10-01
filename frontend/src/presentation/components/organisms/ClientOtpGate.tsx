import React, { useState } from 'react'

import { ShieldCheck } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import {
  forgetOtpVerification,
  isOtpStillValid,
  rememberOtpVerification
} from '@shared/utils/otpSession'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { useRequestPublicOtp, useVerifyPublicOtp } from '../../hooks/usePublic'
import { createBookingInputStyle, createBookingSurfaceStyle } from '../../lib/surfaceStyles'

interface ClientOtpGateProps {
  storePublicId: string
  storeSlug: string
  /** Se llama con el telefono normalizado cuando queda verificado. */
  onVerified: (phone: string) => void
  /** Por que se vuelve a pedir el codigo (el backend rechazo la verificacion). */
  notice?: string
  /**
   * El backend ya rechazo la verificacion recordada: "Enviarme el código" la
   * olvida y siempre pide un codigo nuevo, sin entrar por el atajo.
   */
  skipRemembered?: boolean
  /** Telefono con el que arranca el campo (el que el backend rechazo). */
  initialPhone?: string
}

/**
 * Puerta de "Mis turnos": telefono + codigo por email. Si el telefono ya se
 * verifico en este dispositivo dentro de la ventana que acepta el backend
 * (30 min), entra directo sin gastar un codigo. Si el backend igual la
 * rechaza, el contenedor vuelve a mostrar la puerta con `skipRemembered` y
 * `notice`: pedir el codigo olvida esa verificacion y manda uno nuevo.
 */
export const ClientOtpGate: React.FC<ClientOtpGateProps> = ({
  storePublicId,
  storeSlug,
  onVerified,
  notice,
  skipRemembered = false,
  initialPhone = ''
}) => {
  const requestOtp = useRequestPublicOtp()
  const verifyOtp = useVerifyPublicOtp()
  const [form, setForm] = useState({ phone: initialPhone, email: '', code: '' })
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const continuarSiYaVerificado = (): boolean => {
    if (!form.phone.trim() || !isOtpStillValid(storeSlug, form.phone)) return false
    onVerified(form.phone.trim())
    return true
  }

  const pedirCodigo = async () => {
    setError('')
    // FF-05 (2026-09-30): el backend respondio 403 OTP_VERIFICATION_REQUIRED
    // con una verificacion que el front daba por vigente; entrar por el atajo
    // repetia el 403 sin mandar ningun codigo. Se olvida y se pide uno nuevo.
    if (skipRemembered) forgetOtpVerification(storeSlug)
    else if (continuarSiYaVerificado()) return
    if (!form.email.trim()) {
      setError('Ingresá tu email para poder buscarte')
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
          {/* El código va al email registrado en el negocio, no al que se
              tipee acá: quien pide el código no elige el buzón (2026-09-20).
              Acá el cliente SIEMPRE tiene ficha, así que el campo de email es
              solo el respaldo del contrato de la API. */}
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Poné tu teléfono y te mandamos un código al email que tenés registrado en el negocio.
          </p>
        </div>
      </div>

      {notice && (
        <p role="status" className="text-xs font-bold text-red-600">
          {notice}
        </p>
      )}

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
            aria-label="Tu email"
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
