import React, { useLayoutEffect, useState } from 'react'

import { Link, useLocation } from 'react-router'

import {
  ANALYTICS_CONSENT_KEY,
  enterBookingAnalytics,
  isAnalyticsConfigured,
  isBookingAnalyticsPath,
  readAnalyticsConsent,
  setAnalyticsConsent,
  type AnalyticsConsent as Consent
} from '@infrastructure/analytics/bookingAnalytics'

import { ANALYTICS_PREFERENCES_EVENT } from '@presentation/lib/analyticsPreferences'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'

const CHOICE_BUTTON_CLASS = 'min-h-11 px-4 py-2 text-xs font-black uppercase tracking-widest'

/**
 * Aviso de Google Analytics del portal de reservas.
 *
 * Aparece mientras no hay una eleccion guardada. Despues no queda nada
 * flotando sobre el portal: la eleccion se cambia desde el enlace
 * "Preferencias de analitica" del pie (`LegalFooterLinks`), que reabre este
 * aviso. (2026-11-02: el boton flotante tapaba "Continuar" en el celular.)
 */
export const AnalyticsConsent: React.FC = () => {
  const { pathname } = useLocation()
  const eligible = isAnalyticsConfigured() && isBookingAnalyticsPath(pathname)
  const [consent, setConsent] = useState(readAnalyticsConsent)
  const [editing, setEditing] = useState(false)

  useLayoutEffect(() => {
    if (!eligible) return undefined
    setConsent(readAnalyticsConsent())
    const leave = enterBookingAnalytics()
    const sync = (event: StorageEvent) => {
      if (event.key !== ANALYTICS_CONSENT_KEY && event.key !== null) return
      const value = readAnalyticsConsent()
      setConsent(value)
      setAnalyticsConsent(value, false)
    }
    const openPreferences = () => setEditing(true)
    window.addEventListener('storage', sync)
    window.addEventListener(ANALYTICS_PREFERENCES_EVENT, openPreferences)
    return () => {
      leave()
      window.removeEventListener('storage', sync)
      window.removeEventListener(ANALYTICS_PREFERENCES_EVENT, openPreferences)
    }
  }, [eligible, pathname])

  if (!eligible) return null
  if (consent !== null && !editing) return null

  const choose = (value: Consent) => {
    setAnalyticsConsent(value)
    setConsent(value)
    setEditing(false)
  }

  return (
    <section
      aria-label="Preferencias de analítica"
      className="fixed inset-x-3 bottom-3 z-50 mx-auto max-w-xl rounded-lg border p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        borderColor: colors2000s.border.default,
        boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
        color: colors2000s.text.primary
      }}
    >
      <p className="text-sm font-bold leading-relaxed">
        ¿Aceptás Google Analytics para medir el uso de la reserva con cookies? Es opcional. Podés
        reservar sin aceptar y cambiar tu elección desde Preferencias de analítica, al pie de la
        página.
      </p>
      <Link
        className="mt-1 inline-flex min-h-11 items-center text-xs font-bold uppercase tracking-widest underline"
        style={{ color: colors2000s.text.secondary }}
        to="/legal/privacidad"
      >
        Política de Privacidad
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {(['accepted', 'rejected'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={CHOICE_BUTTON_CLASS}
            style={buttonStyles2000s.default}
            onClick={() => choose(value)}
          >
            {value === 'accepted' ? 'Aceptar analítica' : 'Rechazar analítica'}
          </button>
        ))}
        {editing && (
          <button
            type="button"
            className="min-h-11 px-2 text-xs font-bold uppercase tracking-widest underline"
            style={{ color: colors2000s.text.secondary }}
            onClick={() => setEditing(false)}
          >
            Cerrar
          </button>
        )}
      </div>
    </section>
  )
}
