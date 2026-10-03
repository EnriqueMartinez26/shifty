import React, { useState } from 'react'

import { mdiShieldAlert } from '@mdi/js'
import { KeyRound } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router'

import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  PASSWORD_REJECTED_MESSAGE,
  validateNewPassword
} from '@domain/value-objects/PasswordRules'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { Icon2000s } from '../components/legacy/Icon2000s'
import { AuthShell } from '../components/organisms/AuthShell'
import { useResetPassword } from '../hooks/useResetPassword'
import { create2000sInputStyle } from '../lib/surfaceStyles'

const inputStyle = create2000sInputStyle()

const ResetPasswordPage: React.FC = () => {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token') || ''

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const resetPasswordMutation = useResetPassword()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setMessage(null)

    if (!token) {
      setError('El enlace no contiene un token válido.')
      return
    }

    // Mismas reglas que `ResetPasswordRequest` en el backend (D-20261001-01).
    const passwordError = validateNewPassword(newPassword)
    if (passwordError) {
      setError(passwordError)
      return
    }

    if (newPassword !== confirmPassword) {
      setError('Las contraseñas no coinciden.')
      return
    }

    try {
      const response = await resetPasswordMutation.mutateAsync({
        token,
        new_password: newPassword
      })
      setMessage(response.message || 'Contraseña actualizada correctamente.')
      setTimeout(() => navigate('/login'), 1200)
    } catch (error: unknown) {
      // Si el 422 señala la clave, se avisa con texto propio; el token
      // rechazado conserva su mensaje específico.
      setError(
        getErrorMessage(
          error,
          'No se pudo restablecer la contraseña',
          {},
          {
            new_password: PASSWORD_REJECTED_MESSAGE
          }
        )
      )
    }
  }

  return (
    <AuthShell
      title="Restablecer contraseña"
      subtitle="Definí una nueva contraseña para tu cuenta."
      showBackToLogin
    >
      <form
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
        className="space-y-6"
      >
        <div>
          <label
            htmlFor="reset-new-password"
            className="block text-xs font-bold uppercase tracking-widest mb-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Nueva contraseña
          </label>
          <div className="relative">
            <KeyRound
              className="absolute left-3 top-3.5 w-4 h-4"
              style={{ color: colors2000s.text.disabled }}
            />
            <input
              id="reset-new-password"
              type="password"
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              maxLength={PASSWORD_MAX_LENGTH * 2}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full rounded-xl pl-10 pr-4 py-3 outline-none transition-all"
              style={inputStyle}
              placeholder={`Mínimo ${PASSWORD_MIN_LENGTH} caracteres, con letra y número`}
              required
            />
          </div>
        </div>

        <div>
          <label
            htmlFor="reset-confirm-password"
            className="block text-xs font-bold uppercase tracking-widest mb-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Confirmar contraseña
          </label>
          <div className="relative">
            <KeyRound
              className="absolute left-3 top-3.5 w-4 h-4"
              style={{ color: colors2000s.text.disabled }}
            />
            <input
              id="reset-confirm-password"
              type="password"
              autoComplete="new-password"
              maxLength={PASSWORD_MAX_LENGTH * 2}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full rounded-xl pl-10 pr-4 py-3 outline-none transition-all"
              style={inputStyle}
              required
            />
          </div>
        </div>

        {message && (
          <div
            role="status"
            aria-live="polite"
            className="text-sm p-3 rounded-xl font-medium"
            style={{
              background: colors2000s.status.success.bg,
              border: `1px solid ${colors2000s.status.success.border}`,
              color: colors2000s.status.success.text,
              boxShadow: colors2000s.shadows.insetDark
            }}
          >
            {message}
          </div>
        )}
        {error && (
          <div
            role="alert"
            aria-live="polite"
            className="text-sm p-3 rounded-xl flex items-center gap-2"
            style={{
              background: colors2000s.status.danger.bg,
              border: `1px solid ${colors2000s.status.danger.border}`,
              color: colors2000s.status.danger.text,
              boxShadow: colors2000s.shadows.insetDark
            }}
          >
            <Icon2000s
              path={mdiShieldAlert}
              size={16}
              variant="idle"
              color={colors2000s.status.danger.text}
            />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={resetPasswordMutation.isPending}
          aria-busy={resetPasswordMutation.isPending}
          className="w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50 group"
          style={
            resetPasswordMutation.isPending
              ? buttonStyles2000s.disabled
              : buttonStyles2000s.selected
          }
        >
          {resetPasswordMutation.isPending ? 'Actualizando...' : 'Actualizar contraseña'}
        </button>
      </form>
    </AuthShell>
  )
}

export default ResetPasswordPage
