import type { ApplicationError } from '@shared/errors'
import { getHttpStatus } from '@shared/errors/getErrorMessage'

import { normalizeApiError } from './api-contract'

/**
 * Coordinacion de la sesion entre pestanas (F4-01, F4-02; decisiones
 * D-20260928-02 y D-20260928-03).
 *
 * Cada refresh rota la sesion en el backend: revoca el sid viejo y crea uno
 * nuevo, asi que el access token de las OTRAS pestanas deja de valer en ese
 * instante, y dos refresh casi simultaneos disparan la deteccion de reuso
 * (logout en todos los dispositivos). Por eso:
 * - el refresh corre dentro de un Web Lock compartido por todas las pestanas
 *   del origen; quien entra al lock y ve que el token ya cambio, lo usa sin
 *   pedir otro;
 * - el token nuevo se reparte por BroadcastChannel y cada pestana lo guarda
 *   SOLO en memoria (nunca localStorage/sessionStorage, regla 28);
 * - solo un 401/403 de /auth/refresh termina la sesion, y solo en esa
 *   pestana: a las demas las cierra unicamente un logout explicito. Red, 429,
 *   503 y 5xx son transitorios: se reintenta respetando Retry-After (la espera
 *   fuera del lock) y la sesion queda.
 */

const SESSION_LOCK_NAME = 'shifty-auth-refresh'
const CHANNEL_NAME = 'shifty-auth'

/** Otra pestana cerro sesion a pedido del usuario (broadcastLogout). */
export const PEER_LOGOUT_EVENT = 'shifty:peer-logout'
/** Otra pestana inicio sesion; `detail` es el `public_id` del usuario. */
export const PEER_SESSION_EVENT = 'shifty:peer-session'
/** Un refresh transitorio se esta reintentando; `detail` es `true`/`false`. */
export const SESSION_RECONNECTING_EVENT = 'shifty:session-reconnecting'

const MAX_RETRIES = 3
const MAX_TOTAL_WAIT_MS = 30_000
const BACKOFF_MS = [1_000, 2_000, 4_000]

export type RefreshResult =
  | { kind: 'ok'; token: string }
  | { kind: 'expired' }
  | { kind: 'transient'; error: ApplicationError; retryAfter: number | undefined }

type SessionMessage =
  | { type: 'token'; token: string }
  | { type: 'logout' }
  | { type: 'session'; publicId: string; token: string | null }

/** Lo que se usa de `navigator.locks`. */
interface LockLike {
  request: (name: string, callback: () => Promise<RefreshResult>) => Promise<RefreshResult>
}

/** Lo que se usa de `BroadcastChannel`. */
interface ChannelLike {
  postMessage: (message: SessionMessage) => void
  onmessage: ((event: MessageEvent) => void) | null
}

interface SessionSyncDeps {
  /** POST /auth/refresh; resuelve con el access token nuevo (o null si no vino). */
  requestRefresh: () => Promise<string | null>
  getToken: () => string | null
  setToken: (token: string | null) => void
  locks: LockLike | undefined
  channel: ChannelLike | undefined
  sleep?: (ms: number) => Promise<void>
  dispatch?: (event: Event) => void
}

const defaultSleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms)
  })

const defaultDispatch = (event: Event) => {
  try {
    window.dispatchEvent(event)
  } catch {
    /* entorno sin window: nadie escucha */
  }
}

/** `navigator.locks` si el navegador lo tiene; si no, refresh por pestana. */
export const detectLocks = (): LockLike | undefined => {
  const nav = typeof window === 'undefined' ? undefined : window.navigator
  return nav && 'locks' in nav && nav.locks ? nav.locks : undefined
}

/** Canal entre pestanas si existe `BroadcastChannel`; si no, sin difusion. */
export const openChannel = (): ChannelLike | undefined => {
  if (typeof BroadcastChannel === 'undefined') return undefined
  try {
    return new BroadcastChannel(CHANNEL_NAME)
  } catch {
    return undefined
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const parseMessage = (data: unknown): SessionMessage | null => {
  if (!isRecord(data)) return null
  if (data.type === 'token' && typeof data.token === 'string') {
    return { type: 'token', token: data.token }
  }
  if (data.type === 'logout') return { type: 'logout' }
  if (data.type === 'session' && typeof data.publicId === 'string') {
    const token = typeof data.token === 'string' ? data.token : null
    return { type: 'session', publicId: data.publicId, token }
  }
  return null
}

/** Sin respuesta, 429 o 5xx: puede pasar solo, vale reintentar. */
const isRetryable = (error: ApplicationError) => {
  const status = getHttpStatus(error) ?? 0
  return status === 0 || status === 429 || status >= 500
}

const classifyFailure = (error: unknown): RefreshResult => {
  const normalized = normalizeApiError(error)
  const status = getHttpStatus(normalized)
  if (status === 401 || status === 403) return { kind: 'expired' }
  const retryAfter = normalized.context?.retryAfter
  return {
    kind: 'transient',
    error: normalized,
    retryAfter: typeof retryAfter === 'number' ? retryAfter : undefined
  }
}

const retryDelayMs = (retryAfter: number | undefined, attempt: number) =>
  retryAfter !== undefined ? retryAfter * 1_000 : (BACKOFF_MS[attempt] ?? MAX_TOTAL_WAIT_MS)

const refreshOnce = async (requestRefresh: SessionSyncDeps['requestRefresh']) => {
  try {
    const token = await requestRefresh()
    // Un 200 sin token no deja sesion utilizable: se trata como vencida.
    return token ? ({ kind: 'ok', token } as const) : ({ kind: 'expired' } as const)
  } catch (error) {
    return classifyFailure(error)
  }
}

interface RetryDeps {
  /** Un intento: toma el lock, hace a lo sumo un POST y lo suelta. */
  attempt: () => Promise<RefreshResult>
  sleep: (ms: number) => Promise<void>
  dispatch: (event: Event) => void
}

/**
 * Hasta MAX_RETRIES reintentos ante red/429/5xx, sin pasar MAX_TOTAL_WAIT_MS.
 * La espera va FUERA del lock: otra pestana puede refrescar mientras tanto y
 * el proximo intento adopta su token sin otro POST.
 */
const refreshWithRetries = async (
  deps: RetryDeps,
  attempt = 0,
  waited = 0
): Promise<RefreshResult> => {
  const result = await deps.attempt()
  if (result.kind !== 'transient' || !isRetryable(result.error) || attempt >= MAX_RETRIES) {
    return result
  }
  const delay = retryDelayMs(result.retryAfter, attempt)
  if (waited + delay > MAX_TOTAL_WAIT_MS) return result
  deps.dispatch(new CustomEvent(SESSION_RECONNECTING_EVENT, { detail: true }))
  await deps.sleep(delay)
  return refreshWithRetries(deps, attempt + 1, waited + delay)
}

/** Mensajes de otras pestanas: el token va a memoria y se avisa como evento de window. */
const createMessageHandler =
  (setToken: SessionSyncDeps['setToken'], dispatch: (event: Event) => void) =>
  (event: MessageEvent) => {
    const message = parseMessage(event.data)
    if (!message) return
    if (message.type === 'token') {
      setToken(message.token)
    } else if (message.type === 'logout') {
      setToken(null)
      dispatch(new Event(PEER_LOGOUT_EVENT))
    } else {
      setToken(message.token)
      dispatch(new CustomEvent(PEER_SESSION_EVENT, { detail: message.publicId }))
    }
  }

export const createSessionSync = (deps: SessionSyncDeps) => {
  const { requestRefresh, getToken, setToken, locks, channel } = deps
  const sleep = deps.sleep ?? defaultSleep
  const dispatch = deps.dispatch ?? defaultDispatch
  let inFlight: Promise<RefreshResult> | null = null

  const post = (message: SessionMessage) => {
    try {
      channel?.postMessage(message)
    } catch {
      /* canal cerrado: las demas pestanas refrescan por su cuenta */
    }
  }

  /** Token que otra pestana ya renovo (llego por el canal), si lo hay. */
  const peerToken = (staleToken: string | null) => {
    const current = getToken()
    return current && current !== staleToken ? current : null
  }

  const attemptUnderLock = async (staleToken: string | null): Promise<RefreshResult> => {
    // Otra pestana refresco mientras esta esperaba el lock: un POST mas
    // revocaria su token.
    const adopted = peerToken(staleToken)
    if (adopted) return { kind: 'ok', token: adopted }

    const result = await refreshOnce(requestRefresh)
    if (result.kind === 'ok') {
      setToken(result.token)
      // Antes de soltar el lock: la siguiente pestana ya ve el token nuevo.
      post({ type: 'token', token: result.token })
      return result
    }
    if (result.kind !== 'expired') return result
    // Un 401 puede ser de haber perdido la carrera (sin locks, o la ventana de
    // gracia del backend): si el token del ganador llego mientras tanto, vale.
    const late = peerToken(staleToken)
    if (late) return { kind: 'ok', token: late }
    // La sesion termina SOLO en esta pestana; a las demas solo las cierra un
    // logout explicito (broadcastLogout). Avisar a la UI es de quien llama.
    setToken(null)
    return result
  }

  const withLock = (run: () => Promise<RefreshResult>) =>
    locks ? locks.request(SESSION_LOCK_NAME, run) : run()

  const runRefresh = async (staleToken: string | null) => {
    const attempt = () => withLock(() => attemptUnderLock(staleToken))
    const result = await refreshWithRetries({ attempt, sleep, dispatch })
    dispatch(new CustomEvent(SESSION_RECONNECTING_EVENT, { detail: false }))
    return result
  }

  /**
   * Refresh coordinado. `staleToken` es el token con el que fallo el request
   * (o el que habia al llamar): si al entrar al lock ya es otro, no se pide
   * uno nuevo. Dentro de la pestana, todos esperan la misma promesa.
   */
  const refreshAccessToken = (staleToken: string | null): Promise<RefreshResult> => {
    if (!inFlight) {
      inFlight = runRefresh(staleToken).finally(() => {
        inFlight = null
      })
    }
    return inFlight
  }

  if (channel) channel.onmessage = createMessageHandler(setToken, dispatch)

  return {
    refreshAccessToken,
    broadcastLogout: () => post({ type: 'logout' }),
    broadcastSession: (publicId: string, token: string | null) =>
      post({ type: 'session', publicId, token })
  }
}
