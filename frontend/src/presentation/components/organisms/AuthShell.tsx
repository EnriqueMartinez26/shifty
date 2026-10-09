import React from 'react'

import { mdiStore } from '@mdi/js'
import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router'

import { colors2000s } from '../../../theme/colors'
import { Icon2000s } from '../legacy/Icon2000s'
import LegalFooterLinks from '../navigation/LegalFooterLinks'

interface AuthShellProps {
  title: string
  subtitle: string
  /** Pie dentro de la tarjeta con el link "Volver a iniciar sesion". */
  showBackToLogin?: boolean
  children: React.ReactNode
}

/**
 * Cascara de las pantallas de acceso (login, olvido y restablecer clave): fondo,
 * marca, titulo, tarjeta con el contenido y el copyright. Cada pagina pone su
 * formulario como `children`.
 */
export const AuthShell: React.FC<AuthShellProps> = ({
  title,
  subtitle,
  showBackToLogin = false,
  children
}) => (
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
          {title}
        </h1>
        <p className="text-sm font-medium" style={{ color: colors2000s.text.secondary }}>
          {subtitle}
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
        {children}

        {showBackToLogin && (
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
        )}
      </div>

      <p className="mt-8 text-center text-xs" style={{ color: colors2000s.text.secondary }}>
        Copyright 2026 Shifty SaaS. Todos los derechos reservados.
      </p>
      {/* Mismos enlaces legales que el portal y el panel: el login es la
          portada de "/" y la 404 tambien la ve quien no tiene sesion. */}
      <LegalFooterLinks className="mt-3" />
    </div>
  </div>
)
