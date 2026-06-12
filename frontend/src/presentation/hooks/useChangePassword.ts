import { useMutation } from '@tanstack/react-query'
import { authService, type ChangePasswordPayload } from '@application/services/AuthService'

export const useChangePassword = () => {
  return useMutation<void, Error, ChangePasswordPayload>({
    mutationFn: (payload) => authService.changePassword(payload)
  })
}
