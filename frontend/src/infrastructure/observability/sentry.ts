import * as Sentry from '@sentry/react'

import { isRequestCanceledError } from '@shared/errors/RequestCanceledError'

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
    // Sentry 11 reemplazo `sendDefaultPii` por `dataCollection` y, sin
    // configurarlo, recolecta MAS que la v10 (usuario e IP inferida, cookies,
    // headers sin depurar, cuerpos HTTP). Se apaga cada categoria de forma
    // explicita; `userInfo: false` ademas le pide a Sentry que no infiera la
    // IP del cliente (`infer_ip: never`), tambien en los builds sin tunel.
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: { request: false, response: false },
      httpBodies: [],
      urlQueryParams: false,
      genAI: { inputs: false, outputs: false },
      databaseQueryData: false,
      queues: false,
      graphQL: { document: false, variables: false }
    },
    // En la v11 el default paso a true: un captureMessage llevaria un stack
    // trace sintetico. Se conserva el comportamiento de la v10.
    attachStacktrace: false,
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
    // Recorte de datos sensibles del evento antes de enviarlo. Una consulta
    // cancelada a proposito que termine sin atrapar (unhandledrejection) no es
    // un error: no se manda.
    beforeSend: (event, hint) => {
      if (isRequestCanceledError(hint?.originalException)) return null
      if (event.request) {
        if (event.request.url) event.request.url = stripQuery(event.request.url)
        delete event.request.query_string
        delete event.request.data
        delete event.request.cookies
        if (event.request.headers) {
          delete event.request.headers.Authorization
          delete event.request.headers.authorization
          delete event.request.headers.Cookie
          delete event.request.headers.cookie
          // El Referer es la URL de la pagina anterior: puede traer un token
          // en la query (`/reset-password?token=...`).
          delete event.request.headers.Referer
          delete event.request.headers.referer
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
