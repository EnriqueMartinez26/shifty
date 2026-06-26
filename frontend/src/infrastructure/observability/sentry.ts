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
    tracesSampleRate: parseSampleRate(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE)
  })

  return true
}

export { Sentry }
