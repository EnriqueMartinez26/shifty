import { useMutation } from '@tanstack/react-query'

import {
  authService,
  type AuthenticatedUser,
  type LoginPayload
} from '@application/services/AuthService'

import { setAuthToken } from '@infrastructure/http/client'

import { UnauthorizedError, ValidationError } from '@shared/errors'

import { useAuth } from '../context/AuthContext'

interface LoginResult {
  access_token: string
  user: AuthenticatedUser
}

export const useLogin = () => {
  const { login } = useAuth()

  return useMutation<LoginResult, Error, LoginPayload>({
    mutationFn: async (payload) => {
      let access_token: string
      try {
        ;({ access_token } = await authService.login(payload))
      } catch (error) {
        // El `MutationCache` global de `main.tsx` manda TODO `UnauthorizedError`
        // al handler que muestra "Sesion expirada" y redirige. Una clave mal
        // tipeada no es una sesion vencida: se relanza como error de
        // credenciales para que el formulario lo muestre y la pantalla no se
        // recargue (F11c-03, 2026-09-20).
        if (error instanceof UnauthorizedError) {
          throw new ValidationError(error.message || 'Email o contraseña incorrectos')
        }
        throw error
      }
      setAuthToken(access_token)
      const currentUser = await authService.fetchCurrentUser()
      login(access_token, currentUser)
      return { access_token, user: currentUser }
    }
  })
}
