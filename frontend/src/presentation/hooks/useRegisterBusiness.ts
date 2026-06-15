import { useMutation } from '@tanstack/react-query'

import { authService, type RegisterBusinessPayload } from '@application/services/AuthService'

export const useRegisterBusiness = () =>
  useMutation<void, Error, RegisterBusinessPayload>({
    mutationFn: (payload) => authService.registerBusiness(payload)
  })
