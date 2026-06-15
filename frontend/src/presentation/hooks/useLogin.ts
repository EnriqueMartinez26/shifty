import { useMutation } from '@tanstack/react-query'

import {
  authService,
  type AuthenticatedUser,
  type LoginPayload
} from '@application/services/AuthService'

import { setAuthToken } from '@infrastructure/http/client'

import { useAuth } from '../context/AuthContext'

export interface LoginResult {
  access_token: string
  user: AuthenticatedUser
}

export const useLogin = () => {
  const { login } = useAuth()

  return useMutation<LoginResult, Error, LoginPayload>({
    mutationFn: async (payload) => {
      const { access_token } = await authService.login(payload)
      setAuthToken(access_token)
      const currentUser = await authService.fetchCurrentUser()
      login(access_token, currentUser)
      return { access_token, user: currentUser }
    }
  })
}

export default useLogin
