const DEFAULT_DEV_API_URL = 'http://localhost:8000'

export const resolveApiBaseUrl = (
  configuredUrl: string | undefined,
  isDev: boolean
): string => {
  const normalizedUrl = configuredUrl?.trim().replace(/\/+$/, '')

  if (normalizedUrl) {
    return normalizedUrl
  }

  if (isDev) {
    return DEFAULT_DEV_API_URL
  }

  throw new Error(
    'VITE_API_URL is required in production. Set it to the backend path or public URL, for example /api behind Nginx.'
  )
}
