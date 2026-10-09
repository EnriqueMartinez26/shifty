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
    window.addEventListener('storage', sync)
    return () => {
      leave()
      window.removeEventListener('storage', sync)
    }
  }, [eligible, pathname])

  if (!eligible) return null
  const choose = (value: Consent) => {
    setAnalyticsConsent(value)
    setConsent(value)
    setEditing(false)
  }

  if (consent !== null && !editing) {
    return (
      <button
        type="button"
        className="fixed bottom-3 left-3 z-50 rounded border bg-white px-3 py-2 text-xs text-gray-800 shadow"
        onClick={() => setEditing(true)}
      >
        Preferencias de analítica
      </button>
    )
  }
  return (
    <section
      aria-label="Preferencias de analítica"
      className="fixed bottom-3 inset-x-3 z-50 mx-auto max-w-xl rounded-lg border bg-white p-4 text-gray-800 shadow-lg"
    >
      <p className="text-sm">
        ¿Aceptás Google Analytics para medir el uso de la reserva con cookies? Es opcional. Podés
        reservar sin aceptar y cambiar tu elección en Preferencias de analítica.
      </p>
      <Link className="text-sm underline" to="/legal/privacidad">
        Política de Privacidad
      </Link>
      <div className="mt-3 flex flex-wrap gap-3">
        {(['accepted', 'rejected'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className="rounded border border-gray-500 bg-white px-4 py-2 text-sm font-bold"
            onClick={() => choose(value)}
          >
            {value === 'accepted' ? 'Aceptar analítica' : 'Rechazar analítica'}
          </button>
        ))}
        {editing && (
          <button type="button" className="text-sm underline" onClick={() => setEditing(false)}>
            Cerrar
          </button>
        )}
      </div>
    </section>
  )
}
