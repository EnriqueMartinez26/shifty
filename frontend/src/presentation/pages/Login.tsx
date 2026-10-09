import React, { useState } from 'react'

import { mdiShieldAlert } from '@mdi/js'
import { ArrowRight } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router'

import { LOGIN_PASSWORD_MAX_LENGTH } from '@domain/value-objects/PasswordRules'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { Icon2000s } from '../components/legacy/Icon2000s'
import { AuthShell } from '../components/organisms/AuthShell'
import { getDefaultAppRoute } from '../context/roles'
import { useLogin } from '../hooks/useLogin'
import { safeReturnPath } from '../lib/returnPath'
import { create2000sInputStyle } from '../lib/surfaceStyles'

const inputStyle = create2000sInputStyle()

/** `from` que deja `ProtectedRoute` al mandar a login (FF-36). */
const readFrom = (state: unknown): unknown =>
  state && typeof state === 'object' ? Reflect.get(state, 'from') : undefined

const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const loginMutation = useLogin()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (Array.from(password).length > LOGIN_PASSWORD_MAX_LENGTH) {
      setError('La contraseña no puede tener más de 128 caracteres')
      return
    }
    const normalizedEmail = email.trim().toLowerCase()

    try {
      const { user: currentUser } = await loginMutation.mutateAsync({
        email: normalizedEmail,
        password
      })
      // Vuelve adonde estaba solo si es interna y el rol la puede abrir;
      // si no, a la ruta por defecto del rol (D-20260928-06).
      const target =
        safeReturnPath(readFrom(location.state), currentUser.role, currentUser.is_global_admin) ??
        getDefaultAppRoute(currentUser.role, currentUser.is_global_admin)
      void navigate(target, { replace: true })
    } catch (error: unknown) {
      setError(getErrorMessage(error, 'Error al iniciar sesión'))
    }
  }

  return (
    <AuthShell title="Shifty" subtitle="Gestiona tus turnos, clientes y equipo">
      <form
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
        className="space-y-6"
      >
        <div>
          <label
            htmlFor="login-email"
            className="block text-xs font-bold uppercase tracking-widest mb-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Email
          </label>
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-xl px-4 py-3 outline-none transition-all"
            style={inputStyle}
            placeholder="nombre@ejemplo.com"
            required
          />
        </div>

        <div>
          <label
            htmlFor="login-password"
            className="block text-xs font-bold uppercase tracking-widest mb-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Contraseña
          </label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            maxLength={LOGIN_PASSWORD_MAX_LENGTH * 2}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl px-4 py-3 outline-none transition-all"
            style={inputStyle}
            placeholder="********"
            required
          />
          <div className="mt-2 text-right">
            <Link
              to="/forgot-password"
              className="text-xs transition-colors font-medium"
              style={{ color: colors2000s.orange.accent }}
            >
              ¿Olvidaste tu contraseña?
            </Link>
          </div>
        </div>

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
          disabled={loginMutation.isPending}
          aria-busy={loginMutation.isPending}
          className="w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50 group"
          style={loginMutation.isPending ? buttonStyles2000s.disabled : buttonStyles2000s.selected}
        >
          {loginMutation.isPending ? (
            'Verificando...'
          ) : (
            <>
              Entrar al Panel
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </>
          )}
        </button>
      </form>
    </AuthShell>
  )
}

export default LoginPage
