import * as Sentry from '@sentry/react'

import { getRuntimeEnv } from '../http/runtime-env'

export const parseSampleRate = (rawValue: string | undefined): number | undefined => {
  if (!rawValue) return undefined

  const sampleRate = Number(rawValue)
  if (!Number.isFinite(sampleRate)) return undefined

  return Math.min(1, Math.max(0, sampleRate))
}

/**
 * Saca query string y fragmento de una URL. `/reset-password?token=...` (y
 * cualquier otro link con un secreto en la query) llegaba entero a Sentry en
 * `request.url` y en los breadcrumbs de navegacion y fetch.
 */
export const stripQuery = (url: string): string => url.split(/[?#]/, 1)[0] ?? url

const URL_BREADCRUMB_KEYS = ['url', 'from', 'to'] as const

export const initSentry = (): boolean => {
  const env = getRuntimeEnv()
  if (!env.sentryDsn) return false

  Sentry.init({
    dsn: env.sentryDsn,
    // Mismo origen (nginx reenvia a un destino fijado en el build): lo que
    // bloquea un adblocker o la CSP (connect-src 'self') igual llega.
    tunnel: env.sentryTunnel || undefined,
    maxBreadcrumbs: 30,
    environment: env.sentryEnvironment || env.mode,
    tracesSampleRate: parseSampleRate(env.sentryTracesSampleRate),
    // No mandar PII por defecto (queda en false, pero explicito) ni cookies/headers.
    sendDefaultPii: false,
    // Los breadcrumbs de consola arrastran lo que se loguea (datos de cliente,
    // respuestas del server): se descartan para no filtrar PII a la telemetria.
    beforeBreadcrumb: (breadcrumb) => {
      if (breadcrumb.category === 'console') return null
      const data = breadcrumb.data
      if (data) {
        for (const key of URL_BREADCRUMB_KEYS) {
          const value: unknown = data[key]
          if (typeof value === 'string') data[key] = stripQuery(value)
        }
      }
      return breadcrumb
    },
    // Recorte de datos sensibles del evento antes de enviarlo.
    beforeSend: (event) => {
      if (event.request) {
        if (event.request.url) event.request.url = stripQuery(event.request.url)
        delete event.request.query_string
        delete event.request.data
        delete event.request.cookies
        if (event.request.headers) {
          delete event.request.headers.Authorization
          delete event.request.headers.authorization
          delete event.request.headers.Cookie
        }
      }
      delete event.extra
      delete event.user
      return event
    }
  })

  return true
}

export { Sentry }
