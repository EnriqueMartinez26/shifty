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
  const [token, setToken] = useState<string | null>(localStorage.getItem('shifty_token'))
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const normalizeUser = (raw: User): User => ({
      ...raw,
      role: canonicalRole(raw.role, raw.is_global_admin)
    })

    const initializeAuth = async () => {
      const savedToken = localStorage.getItem('shifty_token')
      const savedUser = localStorage.getItem('shifty_user')

      if (!savedToken) {
        localStorage.removeItem('shifty_user')
        setToken(null)
        setUser(null)
        setIsLoading(false)
        return
      }

      setAuthToken(savedToken)
      setToken(savedToken)

      if (savedUser) {
        setUser(normalizeUser(JSON.parse(savedUser) as User))
      }

      try {
        const currentUser = await authService.fetchCurrentUser()
        const normalized = normalizeUser(currentUser)
        setUser(normalized)
        setToken(savedToken)
        localStorage.setItem('shifty_user', JSON.stringify(normalized))
      } catch {
        setAuthToken(null)
        localStorage.removeItem('shifty_token')
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
    if (newToken) {
      localStorage.setItem('shifty_token', newToken)
    } else {
      localStorage.removeItem('shifty_token')
    }
    localStorage.setItem('shifty_user', JSON.stringify(normalized))
  }

  const logout = () => {
    setAuthToken(null)
    setToken(null)
    setUser(null)
    localStorage.removeItem('shifty_token')
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
