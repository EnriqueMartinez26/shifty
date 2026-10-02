import React from 'react'

import { mdiStore } from '@mdi/js'
import { ArrowLeft, Home } from 'lucide-react'
import { Link, NavigationType, useLocation, useNavigate, useNavigationType } from 'react-router'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { Icon2000s } from '../legacy/Icon2000s'

interface LegalLayoutProps {
  title: string
  intro: string
  children: React.ReactNode
}

const NAV_BUTTON_CLASS =
  'inline-flex items-center gap-2 px-4 py-2.5 text-xs font-black uppercase tracking-widest'

/**
 * Cascara de las paginas legales: barra con la marca y la navegacion de salida
 * arriba, y el documento en una columna de lectura centrada.
 *
 * "Volver" usa el historial solo si esta pestaña ya navego dentro de la app
 * (`location.key` vale `'default'` en la primera entrada): abierta en una
 * pestaña nueva, desde el checkbox de la reserva o el manual, `navigate(-1)`
 * no tendria a donde ir. "Inicio" esta siempre.
 */
export const LegalLayout: React.FC<LegalLayoutProps> = ({ title, intro, children }) => {
  const location = useLocation()
  const navigationType = useNavigationType()
  const navigate = useNavigate()
  // REPLACE: se llego por la redireccion de /legal, que no deja una pagina
  // propia detras (abierta directo, -1 sacaria de la app).
  const canGoBack = location.key !== 'default' && navigationType !== NavigationType.Replace

  return (
    <div
      className="min-h-screen font-sans px-4 pb-12"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`,
        color: colors2000s.text.primary
      }}
    >
      <header className="max-w-3xl mx-auto py-5 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center gap-3">
          <span
            className="w-10 h-10 rounded-xl flex items-center justify-center relative overflow-hidden"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              boxShadow: colors2000s.shadows.outerOrange,
              border: `1px solid ${colors2000s.orange.accent}`
            }}
          >
            <Icon2000s path={mdiStore} size={20} variant="active" />
          </span>
          <span
            className="text-xl font-bold tracking-tight"
            style={{ color: colors2000s.orange.accent }}
          >
            Shifty
          </span>
        </div>
        <nav aria-label="Navegación" className="flex items-center gap-2">
          {canGoBack && (
            <button
              type="button"
              onClick={() => void navigate(-1)}
              className={NAV_BUTTON_CLASS}
              style={buttonStyles2000s.default}
            >
              <ArrowLeft className="w-4 h-4" aria-hidden="true" />
              Volver
            </button>
          )}
          <Link to="/" className={NAV_BUTTON_CLASS} style={buttonStyles2000s.default}>
            <Home className="w-4 h-4" aria-hidden="true" />
            Inicio
          </Link>
        </nav>
      </header>

      <main className="max-w-3xl mx-auto">
        <article
          className="rounded-xl px-5 py-8 sm:p-12"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: colors2000s.shadows.outerMedium
          }}
        >
          <h1
            className="text-3xl font-black tracking-tight mb-3 uppercase"
            style={{ color: colors2000s.orange.accent }}
          >
            {title}
          </h1>
          <p className="text-base leading-7 mb-10" style={{ color: colors2000s.text.primary }}>
            {intro}
          </p>
          {children}
        </article>
      </main>
    </div>
  )
}
