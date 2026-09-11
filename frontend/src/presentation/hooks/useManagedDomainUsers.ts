import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { User } from '@domain/entities/User'

import { userService, UserService } from '@application/services/UserService'

type CreateManagedUserInput = Parameters<UserService['createUser']>[0]
type UpdateManagedUserInput = Parameters<UserService['updateUser']>[1]

export const useManagedDomainUsers = () => {
  return useQuery<User[]>({
    queryKey: ['managed-users'],
    queryFn: () => userService.listUsers(true)
  })
}

export const useCreateManagedDomainUser = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateManagedUserInput) => userService.createUser(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['managed-users'] })
    }
  })
}

export const useUpdateManagedDomainUser = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateManagedUserInput }) =>
      userService.updateUser(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['managed-users'] })
    }
  })
}

export const useDeleteManagedDomainUser = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => userService.deleteUser(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['managed-users'] })
    }
  })
}
