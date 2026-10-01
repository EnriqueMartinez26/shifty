import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient
} from '@tanstack/react-query'

import { User } from '@domain/entities/User'
import type { UserListQuery } from '@domain/repositories/IUserRepository'

import { userService, UserService } from '@application/services/UserService'

type CreateManagedUserInput = Parameters<UserService['createUser']>[0]
type UpdateManagedUserInput = Parameters<UserService['updateUser']>[1]

/**
 * Una sola familia de claves para los usuarios de la tienda. Las mutaciones
 * invalidan `all`, que por prefijo refresca todas las paginas de cada `list`
 * cargada (F11c-07, F4-03).
 */
const managedUsersKeys = {
  all: ['managed-users'] as const,
  list: (query: UserListQuery) => ['managed-users', 'list', query] as const
}

/** Une las paginas sin repetir: el backend ordena solo por `created_at` y con
 * empates el offset puede devolver otra vez una fila de la pagina anterior. */
const flattenUniqueById = (pages: User[][]): User[] => {
  const byId = new Map<string, User>()
  for (const user of pages.flat()) {
    if (!byId.has(user.id)) byId.set(user.id, user)
  }
  return [...byId.values()]
}

/**
 * Busqueda en el servidor, por paginas de `query.limit` con offset (F4-03).
 * Sin total en la respuesta, una pagina llena se toma como "puede haber mas":
 * si el resto es exactamente cero, "Ver mas" trae una pagina vacia y se apaga.
 * `keepPreviousData` deja la lista anterior a la vista mientras llega la
 * nueva, en vez de parpadear al cargando.
 */
export const useManagedDomainUsers = (query: UserListQuery) => {
  const result = useInfiniteQuery({
    queryKey: managedUsersKeys.list(query),
    queryFn: ({ pageParam }) => userService.listUsers({ ...query, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last: User[], all: User[][]) =>
      last.length === query.limit ? all.length * query.limit : undefined,
    placeholderData: keepPreviousData
  })
  return {
    data: result.data ? flattenUniqueById(result.data.pages) : undefined,
    isLoading: result.isLoading,
    error: result.error,
    hasNextPage: result.hasNextPage,
    fetchNextPage: result.fetchNextPage,
    isFetchingNextPage: result.isFetchingNextPage
  }
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
