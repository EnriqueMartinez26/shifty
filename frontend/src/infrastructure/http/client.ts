import axios from 'axios'

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

// Nombre del evento que avisa a la capa de UI que la sesion murio de verdad
// (el refresh via cookie fallo). AuthContext lo escucha para limpiar el user
// y disparar la redireccion a login, en vez de dejar un cascaron logueado que
// vuelve a dar 401 en cada request.
export const SESSION_EXPIRED_EVENT = 'shifty:session-expired'

const notifySessionExpired = () => {
  setAuthToken(null)
  try {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  } catch {
    /* entorno sin window (SSR/tests): el token ya quedo limpio */
  }
}

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Sin reintentos automaticos: todo 409 del backend es determinista (choque
// de integridad, estado viejo, conflicto de agenda), asi que reintentarlo no
// lo resuelve y solo demora el error; y un reintento de reprogramacion podia
// aplicarse en silencio porque el backend libera la clave de idempotencia. Un
// POST tampoco se reenvia: el servidor pudo haberlo aplicado. No hay `timeout`
// a proposito: el proxy (nginx, 30s) ya acota y uno mas corto dejaria POST
// fantasma aplicados en el servidor pero dados por fallidos aca.

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

/**
 * Un 401 del propio login es "credenciales mal", no "sesion vencida": avisar
 * sesion expirada ahi recargaba la pantalla con el cartel "Sesion expirada.
 * Redirigiendo..." y borraba el error del formulario, asi que quien tipeaba
 * mal la clave nunca se enteraba de por que (F11c-03, 2026-09-20).
 * El 401 de `/auth/refresh` SI es sesion muerta y se sigue avisando.
 */
const isLoginPath = (url: string | undefined) => Boolean(url && url.includes('/auth/login'))

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

    // Llegar aca con 401 significa que la rehidratacion no ocurrio o fallo:
    // sesion muerta. Se avisa a la UI para que cierre sesion de verdad.
    const esLogin = isLoginPath(originalRequest.url)

    if (isApiEnvelope(payload) && !payload.success) {
      if (statusCode === 401 && !esLogin) {
        notifySessionExpired()
      }
      return Promise.reject(normalizedError)
    }

    if (normalizedError.statusCode === 401 && !esLogin) {
      notifySessionExpired()
    }
    return Promise.reject(normalizedError)
  }
)

export default apiClient
