import React, { useState } from 'react'

import { mdiShieldAlert } from '@mdi/js'
import { Mail, Send } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { Icon2000s } from '../components/legacy/Icon2000s'
import { AuthShell } from '../components/organisms/AuthShell'
import { useForgotPassword } from '../hooks/useForgotPassword'
import { create2000sInputStyle } from '../lib/surfaceStyles'

const inputStyle = create2000sInputStyle()

const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const forgotPasswordMutation = useForgotPassword()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setMessage(null)

    try {
      const response = await forgotPasswordMutation.mutateAsync({ email })
      setMessage(response.message || 'Si el email existe, recibirás un enlace de recuperación.')
    } catch (error: unknown) {
      setError(getErrorMessage(error, 'No se pudo procesar la solicitud'))
    }
  }

  return (
    <AuthShell
      title="Recuperar contraseña"
      subtitle="Ingresá tu email y te enviamos un enlace de recuperación."
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
            htmlFor="forgot-email"
            className="block text-xs font-bold uppercase tracking-widest mb-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Email
          </label>
          <div className="relative">
            <Mail
              className="absolute left-3 top-3.5 w-4 h-4"
              style={{ color: colors2000s.text.disabled }}
            />
            <input
              id="forgot-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl pl-10 pr-4 py-3 outline-none transition-all"
              style={inputStyle}
              placeholder="nombre@ejemplo.com"
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
              background: '#ecfdf5',
              border: '1px solid #bbf7d0',
              color: '#166534',
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
              background: '#ffeeee',
              border: '1px solid #ffcccc',
              color: '#cc0000',
              boxShadow: colors2000s.shadows.insetDark
            }}
          >
            <Icon2000s path={mdiShieldAlert} size={16} variant="idle" color="#cc0000" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={forgotPasswordMutation.isPending}
          aria-busy={forgotPasswordMutation.isPending}
          className="w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50 group"
          style={
            forgotPasswordMutation.isPending
              ? buttonStyles2000s.disabled
              : buttonStyles2000s.selected
          }
        >
          {forgotPasswordMutation.isPending ? (
            'Enviando...'
          ) : (
            <>
              Enviar enlace
              <Send className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </>
          )}
        </button>
      </form>
    </AuthShell>
  )
}

export default ForgotPasswordPage
