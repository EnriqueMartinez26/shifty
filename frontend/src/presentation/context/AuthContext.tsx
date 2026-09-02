import React, { createContext, useContext, useEffect, useState } from 'react'

import { authService, type AuthenticatedUser } from '@application/services/AuthService'

import { setAuthToken } from '@infrastructure/http/client'

import { canonicalRole } from './roles'

type User = AuthenticatedUser

interface AuthContextType {
  user: User | null
  token: string | null
  login: (token: string | null, user: User) => void
  logout: () => void
  isLoading: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const normalizeUser = (raw: User): User => ({
      ...raw,
      role: canonicalRole(raw.role, raw.is_global_admin)
    })

    const initializeAuth = async () => {
      // El token ya no se persiste en localStorage (robable por XSS): la
      // sesion vive en la cookie HttpOnly de refresh. Al montar, se rehidrata
      // el access token contra /auth/refresh; si no hay sesion, login normal.
      const savedUser = localStorage.getItem('shifty_user')
      if (savedUser) {
        // Pintado optimista del perfil mientras se valida la sesion real.
        setUser(normalizeUser(JSON.parse(savedUser) as User))
      }

      try {
        const { access_token } = await authService.refreshSession()
        setAuthToken(access_token)
        setToken(access_token)

        const currentUser = await authService.fetchCurrentUser()
        const normalized = normalizeUser(currentUser)
        setUser(normalized)
        localStorage.setItem('shifty_user', JSON.stringify(normalized))
      } catch {
        setAuthToken(null)
        localStorage.removeItem('shifty_user')
        setToken(null)
        setUser(null)
      } finally {
        setIsLoading(false)
      }
    }

    void initializeAuth()
  }, [])

  const login = (newToken: string | null, newUser: User) => {
    const normalized = {
      ...newUser,
      role: canonicalRole(newUser.role, newUser.is_global_admin)
    }
    setAuthToken(newToken)
    setToken(newToken)
    setUser(normalized)
    localStorage.setItem('shifty_user', JSON.stringify(normalized))
  }

  const logout = () => {
    // Primero el servidor: revoca la sesion (y con ella el access token, que
    // esta atado por sid) y borra la cookie de refresh. Sin esto, "cerrar
    // sesion" solo limpiaba la pestaña y la sesion seguia viva 30 dias.
    void authService.logout().catch(() => {
      /* si el backend no responde, igual se limpia el estado local */
    })
    setAuthToken(null)
    setToken(null)
    setUser(null)
    localStorage.removeItem('shifty_user')
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
