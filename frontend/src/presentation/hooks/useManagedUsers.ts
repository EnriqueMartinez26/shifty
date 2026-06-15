import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  userAdminService,
  type CreateUserPayload,
  type ManagedUser,
  type UpdateUserPayload
} from '@application/services/UserAdminService'

export const useManagedUsers = (includeInactive = false) =>
  useQuery({
    queryKey: ['users', includeInactive],
    queryFn: (): Promise<ManagedUser[]> => userAdminService.list(includeInactive)
  })

export const useCreateManagedUser = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateUserPayload) => userAdminService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}

export const useUpdateManagedUser = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ publicId, payload }: { publicId: string; payload: UpdateUserPayload }) =>
      userAdminService.update(publicId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}

export const useDeleteManagedUser = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (publicId: string) => userAdminService.delete(publicId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}
