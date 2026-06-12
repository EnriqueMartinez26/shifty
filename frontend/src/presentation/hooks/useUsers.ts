import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useService } from './useService'
import { UserService } from '../../application/services/UserService'
import { CreateUserInput } from '../../domain/use-cases/user/CreateUserUseCase'
import { User } from '../../domain/entities/User'

/**
 * Hook para manejar todas las consultas y mutaciones relacionadas con Usuarios.
 * Integra React Query y resuelve de forma segura el UserService.
 */
export function useUsers() {
  const queryClient = useQueryClient()
  const userService = useService<UserService>('userService')

  // Query: Obtener todos los usuarios
  const getAllUsersQuery = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: () => userService.listUsers(),
    staleTime: 5 * 60 * 1000 // 5 minutos de caché antes de considerar los datos obsoletos
  })

  // Mutation: Crear usuario
  const createUserMutation = useMutation<User, Error, CreateUserInput>({
    mutationFn: (data) => userService.createUser(data),
    onSuccess: () => {
      // Invalidar cache para refrescar lista
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })

  // Mutation: Actualizar usuario
  const updateUserMutation = useMutation<User, Error, { id: string; data: Partial<User> }>({
    mutationFn: ({ id, data }) => userService.updateUser(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['users', variables.id] })
    }
  })

  // Mutation: Eliminar usuario
  const deleteUserMutation = useMutation<void, Error, string>({
    mutationFn: (id) => userService.deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })

  return {
    getAllUsersQuery,
    createUserMutation,
    updateUserMutation,
    deleteUserMutation
  }
}
export default useUsers
