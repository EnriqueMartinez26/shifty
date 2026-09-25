import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { User } from '@domain/entities/User'

import { userService, UserService } from '@application/services/UserService'

type CreateManagedUserInput = Parameters<UserService['createUser']>[0]
type UpdateManagedUserInput = Parameters<UserService['updateUser']>[1]

/**
 * Una sola familia de claves para los usuarios de la tienda. Las mutaciones
 * invalidan `all`, que por prefijo refresca tambien `clients` (lo que lee
 * Cuentas pendientes): antes eran dos stacks con claves distintas y un alta
 * no aparecia en la otra pantalla (F11c-07).
 */
const managedUsersKeys = {
  all: ['managed-users'] as const,
  clients: ['managed-users', 'clients'] as const
}

export const useManagedDomainUsers = () => {
  return useQuery<User[]>({
    queryKey: managedUsersKeys.all,
    queryFn: () => userService.listUsers(true)
  })
}

export const useStoreClients = () => {
  return useQuery<User[]>({
    queryKey: managedUsersKeys.clients,
    queryFn: () => userService.listClients()
  })
}

export const useCreateManagedDomainUser = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateManagedUserInput) => userService.createUser(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: managedUsersKeys.all })
    }
  })
}

export const useUpdateManagedDomainUser = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateManagedUserInput }) =>
      userService.updateUser(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: managedUsersKeys.all })
    }
  })
}

export const useDeleteManagedDomainUser = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => userService.deleteUser(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: managedUsersKeys.all })
    }
  })
}
