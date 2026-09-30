import React from 'react'

import { ShieldCheck, TriangleAlert } from 'lucide-react'

import type { BookingOtpState } from './types'
import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import {
  createBookingAccentBoxStyle,
  createBookingClientInputStyle,
  createBookingSurfaceStyle
} from '../../../lib/surfaceStyles'

interface BookingOtpSectionProps {
  /** Telefono que se verifica, tal como lo tipeo el cliente. */
  phone: string
  otpState: BookingOtpState
  isRequestingOtp: boolean
  /** Segundos que faltan para poder pedir otro codigo (0: se puede). */
  otpResendSeconds: number
  isVerifyingOtp: boolean
  onRequestOtp: () => void
  onVerifyOtp: () => void
  onOtpEmailChange: (email: string) => void
  onOtpCodeChange: (code: string) => void
}

/**
 * Pedido y verificacion del codigo OTP de la reserva. BookingStepConfirmation
 * decide cuando se muestra y sostiene el gate que exige el telefono verificado.
 */
export const BookingOtpSection: React.FC<BookingOtpSectionProps> = ({
  phone,
  otpState,
  isRequestingOtp,
  otpResendSeconds,
  isVerifyingOtp,
  onRequestOtp,
  onVerifyOtp,
  onOtpEmailChange,
  onOtpCodeChange
}) => {
  const clientInputStyle = createBookingClientInputStyle()

  return (
    <div className="p-5 bg-white space-y-4" style={createBookingSurfaceStyle()}>
      <div className="flex items-start gap-3">
        <ShieldCheck className="w-5 h-5 mt-0.5 text-orange-500" />
        <div>
          <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
            Verificamos tu telefono
          </p>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Te mandamos un codigo por email para confirmar el {phone}
          </p>
          {/* Si el telefono ya tiene ficha con email cargado, el backend manda
              el codigo a ESE email y no al que se tipee aca: quien pide el
              codigo no elige el buzon (2026-09-20). Decirlo evita que alguien
              espere el mail en una casilla que nunca lo va a recibir. */}
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Si ya reservaste en este negocio, el codigo va al email que tenes registrado.
          </p>
        </div>
      </div>

      <div className="grid sm:grid-cols-[1fr_auto] gap-3">
        <input
          type="email"
          inputMode="email"
          autoComplete="email"
          aria-label="Email para el codigo"
          value={otpState.email}
          onChange={(e) => onOtpEmailChange(e.target.value)}
          className="px-4 py-3 font-bold outline-none"
          style={clientInputStyle}
          placeholder="tu@email.com"
        />
        <button
          type="button"
          disabled={
            isRequestingOtp ||
            !otpState.email.trim() ||
            otpResendSeconds > 0 ||
            otpState.rateLimited
          }
          onClick={onRequestOtp}
          className="px-4 py-3 text-xs font-black uppercase tracking-widest"
          style={{ ...buttonStyles2000s.default, borderRadius: 6 }}
        >
          {isRequestingOtp
            ? 'Enviando...'
            : otpResendSeconds > 0
              ? `Reenviar en ${otpResendSeconds} s`
              : 'Enviar codigo'}
        </button>
      </div>

      <div className="space-y-3">
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={otpState.code}
          // Solo digitos: inputMode no impide tipear letras en un teclado fisico.
          onChange={(e) => onOtpCodeChange(e.target.value.replace(/\D/g, ''))}
          className="w-full px-4 py-3 font-bold outline-none"
          style={clientInputStyle}
          placeholder="Codigo que te llego por email"
        />

        {/* J7 (2026-09-30): debug_code tal cual lo devolvio la API, solo si
            vino. Si el codigo fue al email de la ficha y no al tipeado, el
            backend devuelve un senuelo (AUD2-SYNC-01): por eso el aviso. */}
        {otpState.debugCode && (
          <div
            role="status"
            className="p-3 text-xs font-bold"
            style={createBookingAccentBoxStyle(
              colors2000s.status.info.bg,
              colors2000s.status.info.border,
              colors2000s.status.info.text
            )}
          >
            Codigo debug (solo desarrollo): {otpState.debugCode}. Si el telefono ya tiene ficha con
            email, el codigo real fue a ese buzon y este puede no servir.
          </div>
        )}

        {otpState.error && (
          <div
            role="alert"
            aria-live="polite"
            className="p-3 text-xs font-bold flex items-center gap-2"
            style={createBookingAccentBoxStyle(
              colors2000s.status.danger.bg,
              colors2000s.status.danger.border,
              colors2000s.status.danger.text
            )}
          >
            <TriangleAlert className="w-4 h-4" />
            {otpState.error}
          </div>
        )}

        {otpState.verified ? (
          <div
            className="p-3 text-xs font-bold flex items-center gap-2"
            style={createBookingAccentBoxStyle(
              colors2000s.status.success.bg,
              colors2000s.status.success.border,
              colors2000s.status.success.text
            )}
          >
            <ShieldCheck className="w-4 h-4" />
            Telefono validado correctamente
          </div>
        ) : (
          <button
            type="button"
            disabled={!otpState.code || isVerifyingOtp}
            onClick={onVerifyOtp}
            className="w-full px-4 py-3 text-xs font-black uppercase tracking-widest disabled:opacity-50"
            style={{ ...buttonStyles2000s.selected, borderRadius: 6 }}
          >
            {isVerifyingOtp ? 'Verificando...' : 'Verificar codigo'}
          </button>
        )}
      </div>
    </div>
  )
}
