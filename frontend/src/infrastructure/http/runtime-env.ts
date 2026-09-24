/* istanbul ignore file */

type RuntimeEnv = {
  apiUrl?: string
  dev: boolean
  mode: string
  sentryDsn?: string
  sentryEnvironment?: string
  sentryTracesSampleRate?: string
  sentryTunnel?: string
}

export const getRuntimeEnv = (): RuntimeEnv => ({
  apiUrl: import.meta.env.VITE_API_URL,
  dev: import.meta.env.DEV,
  mode: import.meta.env.MODE,
  sentryDsn: import.meta.env.VITE_SENTRY_DSN,
  sentryEnvironment: import.meta.env.VITE_SENTRY_ENVIRONMENT,
  sentryTracesSampleRate: import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE,
  sentryTunnel: import.meta.env.VITE_SENTRY_TUNNEL
})
