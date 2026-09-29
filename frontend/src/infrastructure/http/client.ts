import axios from 'axios'

import { resolveApiBaseUrl } from './api-base-url'
import { normalizeApiError, isApiEnvelope, unwrapApiEnvelope } from './api-contract'
import { getRuntimeEnv } from './runtime-env'
import { createSessionSync, detectLocks, openChannel } from './sessionSync'

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
// rehidrata con POST /auth/refresh (ver AuthContext y sessionSync.ts).
let inMemoryToken: string | null = null

// Limpieza del esquema viejo, una vez por carga: si quedo un token persistido
// en localStorage de una version anterior, se elimina. setAuthToken nunca
// toca el almacenamiento.
try {
  localStorage.removeItem(LEGACY_TOKEN_KEY)
} catch {
  /* almacenamiento no disponible */
}

export const setAuthToken = (token: string | null) => {
  inMemoryToken = token
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

// Refresh coordinado entre pestanas (F4-01, F4-02; D-20260928-02/03): ver
// sessionSync.ts. Muchos requests pueden caer en 401 a la vez cuando el access
// token (15 min) vence; todos esperan el MISMO refresh, y entre pestanas un Web
// Lock evita que dos rotaciones se pisen (la segunda seria "reuso" y cerraria
// la sesion en todos los dispositivos).
type RefreshPayload = { access_token?: string; data?: { access_token?: string } }

const sessionSync = createSessionSync({
  // Pasa por apiClient: el interceptor de respuesta ya normaliza el error
  // (RateLimitError/ServiceUnavailableError con retryAfter, NetworkError).
  requestRefresh: async () => {
    const { data } = await apiClient.post<RefreshPayload>('/auth/refresh')
    return data?.access_token ?? data?.data?.access_token ?? null
  },
  getToken: getAuthToken,
  setToken: setAuthToken,
  locks: detectLocks(),
  channel: openChannel()
})

/** Rehidrata la sesion desde la cookie de refresh, coordinado entre pestanas. */
export const refreshSession = () => sessionSync.refreshAccessToken(getAuthToken())

/** Avisa a las otras pestanas que esta cerro sesion. */
export const broadcastLogout = () => sessionSync.broadcastLogout()

/** Avisa a las otras pestanas quien inicio sesion y con que token. */
export const broadcastSession = (publicId: string, token: string | null) =>
  sessionSync.broadcastSession(publicId, token)

/** Token con el que salio el request: si ya no es el vigente, no hace falta otro refresh. */
const bearerOf = (headers: unknown): string | null => {
  const value =
    headers && typeof headers === 'object' ? Reflect.get(headers, 'Authorization') : null
  return typeof value === 'string' && value.startsWith('Bearer ') ? value.slice(7) : null
}

const retryWithToken = (
  originalRequest: { __shiftyRetried?: boolean; headers?: Record<string, string> },
  token: string
) => {
  originalRequest.__shiftyRetried = true
  originalRequest.headers = originalRequest.headers ?? {}
  originalRequest.headers.Authorization = `Bearer ${token}`
  return apiClient.request(originalRequest)
}

const isAuthPath = (url: string | undefined) =>
  Boolean(url && (url.includes('/auth/login') || url.includes('/auth/refresh')))

/**
 * Un 401 del propio login es "credenciales mal", no "sesion vencida": avisar
 * sesion expirada ahi recargaba la pantalla con el cartel "Sesion expirada.
 * Redirigiendo..." y borraba el error del formulario, asi que quien tipeaba
 * mal la clave nunca se enteraba de por que (F11c-03, 2026-09-20).
 * El 401 de `/auth/refresh` tampoco avisa aca: lo decide sessionSync (puede
 * ser una carrera perdida con el token del ganador ya en memoria) y avisa una
 * sola vez quien llamo: este interceptor, al caer con el 401 original, o
 * AuthContext al montar (2026-09-28: se avisaba dos veces).
 */
const skipsExpiredNotice = isAuthPath

const readBlobText = (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '')
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })

/**
 * Con `responseType: 'blob'` (exportar reportes) el cuerpo del error tambien
 * llega como Blob y normalizeApiError no veia ni el `error_code` ni el
 * mensaje. Si el texto es JSON se reemplaza por el objeto; si no (el HTML de
 * un 502 de nginx), queda como vino.
 */
const parseBlobErrorBody = async (error: { response?: { data?: unknown } }) => {
  const data = error.response?.data
  if (!error.response || !(data instanceof Blob)) return
  try {
    error.response.data = JSON.parse(await readBlobText(data)) as unknown
  } catch {
    /* cuerpo ilegible: se normaliza como error sin sobre */
  }
}

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
      const result = await sessionSync.refreshAccessToken(bearerOf(originalRequest.headers))
      if (result.kind === 'ok') return retryWithToken(originalRequest, result.token)
      // Red, 429, 503 o 5xx en el refresh: la sesion sigue viva, solo no se
      // pudo renovar ahora (D-20260928-03). Se devuelve ESE error, no el 401,
      // para que no se avise sesion expirada.
      if (result.kind === 'transient') return Promise.reject(result.error)
    }

    await parseBlobErrorBody(error)
    const normalizedError = normalizeApiError(error)
    const payload = error.response?.data

    // Llegar aca con 401 significa que la rehidratacion no ocurrio o fallo:
    // sesion muerta. Se avisa a la UI para que cierre sesion de verdad.
    const sinAviso = skipsExpiredNotice(originalRequest.url)

    if (isApiEnvelope(payload) && !payload.success) {
      if (statusCode === 401 && !sinAviso) {
        notifySessionExpired()
      }
      return Promise.reject(normalizedError)
    }

    if (normalizedError.statusCode === 401 && !sinAviso) {
      notifySessionExpired()
    }
    return Promise.reject(normalizedError)
  }
)

export default apiClient
