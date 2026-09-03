import * as Sentry from '@sentry/react'

const parseSampleRate = (rawValue: string | undefined): number | undefined => {
  if (!rawValue) return undefined

  const sampleRate = Number(rawValue)
  if (!Number.isFinite(sampleRate)) return undefined

  return Math.min(1, Math.max(0, sampleRate))
}

export const initSentry = (): boolean => {
  const dsn = import.meta.env.VITE_SENTRY_DSN
  if (!dsn) return false

  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
    tracesSampleRate: parseSampleRate(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE),
    // No mandar PII por defecto (queda en false, pero explicito) ni cookies/headers.
    sendDefaultPii: false,
    // Los breadcrumbs de consola arrastran lo que se loguea (datos de cliente,
    // respuestas del server): se descartan para no filtrar PII a la telemetria.
    beforeBreadcrumb: (breadcrumb) =>
      breadcrumb.category === 'console' ? null : breadcrumb,
    // Recorte de datos sensibles del evento antes de enviarlo.
    beforeSend: (event) => {
      if (event.request) {
        delete event.request.data
        delete event.request.cookies
        if (event.request.headers) {
          delete event.request.headers.Authorization
          delete event.request.headers.authorization
          delete event.request.headers.Cookie
        }
      }
      delete event.extra
      return event
    }
  })

  return true
}

export { Sentry }
