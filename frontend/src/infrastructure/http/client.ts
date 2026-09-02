import axios from 'axios'

import axiosRetry from 'axios-retry'

import { resolveApiBaseUrl } from './api-base-url'
import { normalizeApiError, isApiEnvelope, unwrapApiEnvelope } from './api-contract'
import { getRuntimeEnv } from './runtime-env'

const { apiUrl, dev } = getRuntimeEnv()
const API_URL = resolveApiBaseUrl(apiUrl, dev)
const LEGACY_TOKEN_KEY = 'shifty_token'

const apiClient = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

// El access token vive SOLO en memoria: en localStorage cualquier XSS lo
// exfiltra. La sesion persistente es la cookie HttpOnly de refresh, que el
// navegador guarda pero el JS no puede leer; al recargar la pagina se
// rehidrata con POST /auth/refresh (ver AuthContext).
let inMemoryToken: string | null = null

export const setAuthToken = (token: string | null) => {
  inMemoryToken = token
  // Limpieza del esquema viejo: si quedo un token persistido, se elimina.
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY)
  } catch {
    /* almacenamiento no disponible */
  }
}

export const getAuthToken = () => inMemoryToken

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Configuración de Retry Inteligente
axiosRetry(apiClient, {
  retries: 3,
  retryDelay: (retryCount) => {
    // Backoff exponencial con Jitter: 1s, 2s, 4s (+ random offset)
    const delay = Math.pow(2, retryCount) * 1000
    const jitter = Math.random() * 1000
    return delay + jitter
  },
  retryCondition: (error) => {
    // NO reintentar si el servidor rechazó la conexión (ERR_CONNECTION_REFUSED)
    // eso significa que el backend directamente no está corriendo.
    if (error.code === 'ERR_NETWORK' || error.code === 'ERR_CONNECTION_REFUSED') {
      return false
    }
    // Reintentar solo en timeouts o errores de concurrencia (409 Conflict)
    return error.code === 'ECONNABORTED' || error.response?.status === 409
  }
})

// Refresh single-flight: muchos requests pueden caer en 401 a la vez cuando el
// access token (15 min) vence; todos esperan el MISMO refresh en vez de
// dispararlo N veces (la rotacion invalidaria los refresh de los demas).
let refreshInFlight: Promise<string | null> | null = null

const refreshAccessToken = async (): Promise<string | null> => {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post<{ access_token?: string; data?: { access_token?: string } }>(
        `${API_URL}/auth/refresh`,
        undefined,
        { withCredentials: true }
      )
      .then((response) => {
        const payload = response.data
        const token = payload?.access_token ?? payload?.data?.access_token ?? null
        setAuthToken(token)
        return token
      })
      .catch(() => {
        setAuthToken(null)
        return null
      })
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

const isAuthPath = (url: string | undefined) =>
  Boolean(url && (url.includes('/auth/login') || url.includes('/auth/refresh')))

apiClient.interceptors.response.use(
  (response) => {
    response.data = unwrapApiEnvelope(response.data, response.status)
    return response
  },
  async (error) => {
    const statusCode: number | undefined = error.response?.status
    const originalRequest = error.config ?? {}

    // Un 401 fuera del propio login/refresh: intentar UNA rehidratacion via
    // cookie de refresh y reintentar el request original.
    if (
      statusCode === 401 &&
      !originalRequest.__shiftyRetried &&
      !isAuthPath(originalRequest.url)
    ) {
      const token = await refreshAccessToken()
      if (token) {
        originalRequest.__shiftyRetried = true
        originalRequest.headers = originalRequest.headers ?? {}
        originalRequest.headers.Authorization = `Bearer ${token}`
        return apiClient.request(originalRequest)
      }
    }

    const normalizedError = normalizeApiError(error)
    const payload = error.response?.data

    if (isApiEnvelope(payload) && !payload.success) {
      if (statusCode === 401) {
        setAuthToken(null)
      }
      return Promise.reject(normalizedError)
    }

    if (normalizedError.statusCode === 401) {
      setAuthToken(null)
    }
    return Promise.reject(normalizedError)
  }
)

export default apiClient
