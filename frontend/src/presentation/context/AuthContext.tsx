import React, { createContext, useContext, useEffect, useReducer, useRef } from 'react'

import { useQueryClient, type QueryClient } from '@tanstack/react-query'

import { authService, type AuthenticatedUser } from '@application/services/AuthService'

import {
  broadcastLogout,
  broadcastSession,
  getAuthToken,
  setAuthToken,
  SESSION_EXPIRED_EVENT
} from '@infrastructure/http/client'
import {
  PEER_LOGOUT_EVENT,
  PEER_SESSION_EVENT,
  SESSION_RECONNECTING_EVENT
} from '@infrastructure/http/sessionSync'

import { getHttpStatus } from '@shared/errors/getErrorMessage'

import { canonicalRole } from './roles'

type User = AuthenticatedUser

interface AuthContextType {
  user: User | null
  token: string | null
  login: (token: string | null, user: User) => void
  logout: () => void
  isLoading: boolean
  /** Un refresh transitorio se esta reintentando (D-20260928-03). */
  isReconnecting: boolean
  /** No se pudo validar la sesion por una falla transitoria: no es un logout. */
  sessionUnavailable: boolean
  retrySession: () => void
}

type SessionStatus = 'loading' | 'ready' | 'unavailable'

interface SessionState {
  user: User | null
  token: string | null
  status: SessionStatus
  reconnecting: boolean
}

type SessionAction =
  | { type: 'signed-in'; user: User; token: string | null }
  | { type: 'reset'; status: SessionStatus }
  | { type: 'status'; status: SessionStatus }
  | { type: 'reconnecting'; value: boolean }

type SessionLoad =
  { kind: 'user'; user: User; token: string | null } | { kind: 'expired' } | { kind: 'unavailable' }

const SAVED_USER_KEY = 'shifty_user'

const sessionReducer = (state: SessionState, action: SessionAction): SessionState => {
  switch (action.type) {
    case 'signed-in':
      return { ...state, user: action.user, token: action.token, status: 'ready' }
    case 'reset':
      return { user: null, token: null, status: action.status, reconnecting: false }
    case 'status':
      return { ...state, status: action.status }
    case 'reconnecting':
      return state.reconnecting === action.value ? state : { ...state, reconnecting: action.value }
  }
}

const normalizeUser = (raw: User): User => ({
  ...raw,
  role: canonicalRole(raw.role, raw.is_global_admin)
})

const readSavedUser = (): User | null => {
  try {
    const saved = localStorage.getItem(SAVED_USER_KEY)
    // Pintado optimista del perfil mientras se valida la sesion real.
    return saved ? normalizeUser(JSON.parse(saved) as User) : null
  } catch {
    return null
  }
}

const initialState = (): SessionState => ({
  user: readSavedUser(),
  token: null,
  status: 'loading',
  reconnecting: false
})

const saveUser = (user: User | null) => {
  try {
    if (user) localStorage.setItem(SAVED_USER_KEY, JSON.stringify(user))
    else localStorage.removeItem(SAVED_USER_KEY)
  } catch {
    /* almacenamiento no disponible */
  }
}

/**
 * Se cancelan las queries en vuelo ANTES de vaciar: si no, un GET del usuario
 * anterior que responde despues vuelve a escribir en el cache limpio.
 */
const clearCache = (queryClient: QueryClient) => {
  void queryClient.cancelQueries()
  queryClient.clear()
}

/**
 * Fin de sesion o cambio de usuario (FF-26, D-20260928-05): primero el estado
 * (los route guards dejan de pintar pantallas del usuario anterior) y despues
 * TODO el cache de react-query, para que el proximo usuario no vea datos del
 * anterior. Antes lo borraba de rebote la recarga completa a /login del
 * UnauthorizedErrorHandler; esa recarga ya no existe y la garantia vive aca.
 */
const resetSession = (
  dispatch: React.Dispatch<SessionAction>,
  queryClient: QueryClient,
  status: SessionStatus = 'ready'
) => {
  dispatch({ type: 'reset', status })
  saveUser(null)
  clearCache(queryClient)
}

const isSessionRejection = (error: unknown) => {
  const status = getHttpStatus(error)
  return status === 401 || status === 403
}

const loadUser = async (token: string | null): Promise<SessionLoad> => {
  try {
    const user = normalizeUser(await authService.fetchCurrentUser())
    return { kind: 'user', user, token }
  } catch (error) {
    return isSessionRejection(error) ? { kind: 'expired' } : { kind: 'unavailable' }
  }
}

/** Refresh coordinado + /me. Solo un 401/403 cuenta como sesion terminada. */
const loadSession = async (): Promise<SessionLoad> => {
  const result = await authService.refreshSession()
  if (result.kind === 'ok') return loadUser(result.token)
  return result.kind === 'expired' ? { kind: 'expired' } : { kind: 'unavailable' }
}

const applyLoad = (
  load: SessionLoad,
  dispatch: React.Dispatch<SessionAction>,
  queryClient: QueryClient
) => {
  if (load.kind === 'user') {
    saveUser(load.user)
    dispatch({ type: 'signed-in', user: load.user, token: load.token })
  } else if (load.kind === 'expired') {
    setAuthToken(null)
    resetSession(dispatch, queryClient)
  } else {
    // Falla transitoria: se conserva el perfil guardado y se ofrece reintentar
    // en vez de mandar a /login (D-20260928-03).
    dispatch({ type: 'status', status: 'unavailable' })
  }
}

/**
 * Suscripcion a los avisos de sesion (este cliente HTTP y otras pestanas).
 * `currentUserId` es un ref para no re-suscribir en cada cambio de usuario.
 */
const useSessionEvents = (
  dispatch: React.Dispatch<SessionAction>,
  queryClient: QueryClient,
  currentUserId: React.RefObject<string | null>
) => {
  useEffect(() => {
    // La sesion murio (refresh 401/403, aca o en otra pestana): se limpia el
    // perfil y el cache para que los route guards manden a login.
    const handleEnded = () => resetSession(dispatch, queryClient)
    const handlePeerSession = (event: Event) => {
      const publicId = event instanceof CustomEvent ? (event.detail as unknown) : null
      if (typeof publicId !== 'string' || publicId === currentUserId.current) return
      // Otra pestana entro con OTRO usuario: la cookie ya es la suya y su
      // token llego por el canal. Nada del usuario anterior puede quedar.
      resetSession(dispatch, queryClient, 'loading')
      const token = getAuthToken()
      void loadUser(token).then((load) => applyLoad(load, dispatch, queryClient))
    }
    const handleReconnecting = (event: Event) => {
      const value = event instanceof CustomEvent && event.detail === true
      dispatch({ type: 'reconnecting', value })
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleEnded)
    window.addEventListener(PEER_LOGOUT_EVENT, handleEnded)
    window.addEventListener(PEER_SESSION_EVENT, handlePeerSession)
    window.addEventListener(SESSION_RECONNECTING_EVENT, handleReconnecting)
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleEnded)
      window.removeEventListener(PEER_LOGOUT_EVENT, handleEnded)
      window.removeEventListener(PEER_SESSION_EVENT, handlePeerSession)
      window.removeEventListener(SESSION_RECONNECTING_EVENT, handleReconnecting)
    }
  }, [dispatch, queryClient, currentUserId])
}

const AuthContext = createContext<AuthContextType | null>(null)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const queryClient = useQueryClient()
  const [state, dispatch] = useReducer(sessionReducer, undefined, initialState)
  // Usuario vigente para los listeners de otras pestanas, sin re-suscribirlos.
  const currentUserId = useRef<string | null>(null)
  currentUserId.current = state.user?.public_id ?? null

  useEffect(() => {
    // Rehidratacion al montar: el access token vive solo en memoria y la
    // sesion en la cookie HttpOnly de refresh. Con StrictMode el efecto corre
    // dos veces, pero las dos esperan el mismo refresh (single-flight).
    let active = true
    void loadSession().then((load) => {
      if (active) applyLoad(load, dispatch, queryClient)
    })
    return () => {
      active = false
    }
  }, [queryClient])

  useSessionEvents(dispatch, queryClient, currentUserId)

  const login = (newToken: string | null, newUser: User) => {
    const normalized = normalizeUser(newUser)
    // Otro usuario en el mismo navegador: nada del cache anterior (FF-26).
    if (currentUserId.current !== normalized.public_id) clearCache(queryClient)
    setAuthToken(newToken)
    saveUser(normalized)
    dispatch({ type: 'signed-in', user: normalized, token: newToken })
    broadcastSession(normalized.public_id, newToken)
  }

  const logout = () => {
    // Primero el servidor: revoca la sesion (y con ella el access token, que
    // esta atado por sid) y borra la cookie de refresh. Sin esto, "cerrar
    // sesion" solo limpiaba la pestaña y la sesion seguia viva 30 dias.
    void authService.logout().catch(() => {
      /* si el backend no responde, igual se limpia el estado local */
    })
    setAuthToken(null)
    broadcastLogout()
    resetSession(dispatch, queryClient)
  }

  const retrySession = () => {
    dispatch({ type: 'status', status: 'loading' })
    void loadSession().then((load) => applyLoad(load, dispatch, queryClient))
  }

  const value: AuthContextType = {
    user: state.user,
    token: state.token,
    login,
    logout,
    isLoading: state.status === 'loading',
    isReconnecting: state.reconnecting,
    sessionUnavailable: state.status === 'unavailable',
    retrySession
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
