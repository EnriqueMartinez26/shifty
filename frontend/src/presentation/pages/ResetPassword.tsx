import React, { useMemo, useState } from 'react'

import { mdiShieldAlert, mdiStore } from '@mdi/js'
import { ArrowLeft, KeyRound } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { Icon2000s } from '../components/legacy/Icon2000s'
import { useResetPassword } from '../hooks/useResetPassword'

const ResetPasswordPage: React.FC = () => {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = useMemo(() => searchParams.get('token') || '', [searchParams])

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

    if (newPassword.length < 8) {
      setError('La contrasena debe tener al menos 8 caracteres.')
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

  const inputStyle = {
    background: 'white',
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    color: colors2000s.text.primary
  }

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center relative overflow-hidden px-4"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`
      }}
    >
      <div className="w-full max-w-md p-8 relative z-10">
        <div className="flex flex-col items-center mb-8 text-center">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 rotate-3 relative overflow-hidden"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              boxShadow: `${colors2000s.shadows.outerOrange}, 0 8px 24px rgba(200,90,15,0.3)`,
              border: `1px solid ${colors2000s.orange.accent}`
            }}
          >
            <div className="absolute top-0 left-0 right-0 h-1/2 bg-white/20 pointer-events-none" />
            <Icon2000s path={mdiStore} size={30} variant="active" />
          </div>
          <h1
            className="text-3xl font-bold tracking-tight mb-1"
            style={{ color: colors2000s.orange.accent }}
          >
            Restablecer contraseña
          </h1>
          <p className="text-sm font-medium" style={{ color: colors2000s.text.secondary }}>
            Definí una nueva contraseña para tu cuenta.
          </p>
        </div>

        <div
          className="p-8 rounded-3xl"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
          }}
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
                  placeholder="Minimo 8 caracteres"
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

          <div
            className="mt-8 pt-8 text-center"
            style={{ borderTop: `1px solid ${colors2000s.border.light}` }}
          >
            <Link
              to="/login"
              className="inline-flex items-center gap-2 text-sm font-bold transition-colors"
              style={{ color: colors2000s.orange.accent }}
            >
              <ArrowLeft className="w-4 h-4" />
              Volver a iniciar sesión
            </Link>
          </div>
        </div>

        <p className="mt-8 text-center text-xs" style={{ color: colors2000s.text.disabled }}>
          Copyright 2026 Shifty SaaS. Todos los derechos reservados.
        </p>
      </div>
    </div>
  )
}

export default ResetPasswordPage
