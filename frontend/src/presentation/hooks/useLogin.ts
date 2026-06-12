import { useMutation } from '@tanstack/react-query'
import {
  authService,
  type LoginPayload,
  type LoginResponse
} from '@application/services/AuthService'

export const useLogin = () =>
  useMutation<LoginResponse, Error, LoginPayload>({
    mutationFn: (payload) => authService.login(payload)
  })
