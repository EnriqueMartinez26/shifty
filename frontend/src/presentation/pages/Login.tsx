import React, { useState } from 'react'

import { mdiShieldAlert, mdiStore } from '@mdi/js'
import { ArrowRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { Icon2000s } from '../components/legacy/Icon2000s'
import { getDefaultAppRoute } from '../context/roles'
import { useLogin } from '../hooks/useLogin'

const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const loginMutation = useLogin()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    const normalizedEmail = email.trim().toLowerCase()

    try {
      const { user: currentUser } = await loginMutation.mutateAsync({
        email: normalizedEmail,
        password
      })
      void navigate(getDefaultAppRoute(currentUser.role, currentUser.is_global_admin), {
        replace: true
      })
    } catch (error: unknown) {
      setError(getErrorMessage(error, 'Error al iniciar sesión'))
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
      className="min-h-screen w-full flex items-center justify-center relative overflow-hidden"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`
      }}
    >
      <div className="w-full max-w-md p-8 relative z-10">
        <div className="flex flex-col items-center mb-8">
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
            Shifty v2
          </h1>
          <p className="text-sm font-medium" style={{ color: colors2000s.text.secondary }}>
            Gestiona tus turnos, clientes y equipo
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
                htmlFor="login-email"
                className="block text-xs font-bold uppercase tracking-widest mb-2"
                style={{ color: colors2000s.text.secondary }}
              >
                Email
              </label>
              <input
                id="login-email"
                type="email"
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
              style={
                loginMutation.isPending ? buttonStyles2000s.disabled : buttonStyles2000s.selected
              }
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

          <div
            className="mt-8 pt-8 text-center"
            style={{ borderTop: `1px solid ${colors2000s.border.light}` }}
          >
            <p className="text-sm" style={{ color: colors2000s.text.secondary }}>
              ¿No tenés una cuenta?{' '}
              <Link
                to="/register"
                className="font-bold transition-colors"
                style={{ color: colors2000s.orange.accent }}
              >
                Registra tu negocio
              </Link>
            </p>
          </div>
        </div>

        <p className="mt-8 text-center text-xs" style={{ color: colors2000s.text.disabled }}>
          Copyright 2026 Shifty SaaS. Todos los derechos reservados.
        </p>
      </div>
    </div>
  )
}

export default LoginPage
