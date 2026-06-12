import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useService } from './useService'

export interface Credentials {
  email: string
  password?: string
  token?: string
}

export interface SessionInfo {
  token: string
  user: { id: string; email: string; name: string }
}

export interface AuthService {
  getCurrentSession(): Promise<SessionInfo | null>
  login(credentials: Credentials): Promise<SessionInfo>
  logout(): Promise<void>
}

/**
 * Hook para la gestión de autenticación y sesión actual.
 */
export function useAuth() {
  const queryClient = useQueryClient()
  const authService = useService<AuthService>('authService')

  // Query: Obtener usuario/sesión actualmente activa
  const currentUserQuery = useQuery<SessionInfo | null>({
    queryKey: ['currentUser'],
    queryFn: () => authService.getCurrentSession(),
    staleTime: 10 * 60 * 1000, // 10 min
    retry: false // No reintentar si no está autenticado
  })

  // Mutation: Iniciar sesión
  const loginMutation = useMutation<SessionInfo, Error, Credentials>({
    mutationFn: (credentials) => authService.login(credentials),
    onSuccess: (data) => {
      queryClient.setQueryData(['currentUser'], data)
    }
  })

  // Mutation: Cerrar sesión
  const logoutMutation = useMutation<void, Error, void>({
    mutationFn: () => authService.logout(),
    onSuccess: () => {
      queryClient.setQueryData(['currentUser'], null)
      queryClient.clear() // Limpiar todo el cache al desloguearse por seguridad
    }
  })

  return {
    currentUserQuery,
    loginMutation,
    logoutMutation
  }
}
export default useAuth
