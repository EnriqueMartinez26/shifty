import React, { useState } from 'react'

import { mdiShieldAlert } from '@mdi/js'
import { KeyRound } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router'

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
      setError('El enlace no contiene un token valido.')
      return
    }

    // Mismo piso que `ResetPasswordRequest` en el backend (min_length=12).
    if (newPassword.length < 12) {
      setError('La contrasena debe tener al menos 12 caracteres.')
      return
    }

    if (newPassword !== confirmPassword) {
      setError('Las contrasenas no coinciden.')
      return
    }

    try {
      const response = await resetPasswordMutation.mutateAsync({
        token,
        new_password: newPassword
      })
      setMessage(response.message || 'Contrasena actualizada correctamente.')
      setTimeout(() => navigate('/login'), 1200)
    } catch (error: unknown) {
      setError(getErrorMessage(error, 'No se pudo restablecer la contrasena'))
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
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full rounded-xl pl-10 pr-4 py-3 outline-none transition-all"
              style={inputStyle}
              placeholder="Minimo 12 caracteres"
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
