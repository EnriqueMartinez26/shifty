// El singleton `userService` exportado por UserService.ts importa el
// apiClient real (que a su vez toca runtime-env.ts / import.meta, que
// ts-jest no compila fuera de node_modules). Se mockea el módulo del
// cliente HTTP para poder cargar la clase bajo test sin arrastrar esa cadena.
jest.mock('../../infrastructure/http/client', () => ({
  __esModule: true,
  default: {}
}))

import { UserService } from './UserService'
import { User } from '../../domain/entities/User'
import type { IUserRepository } from '../../domain/repositories/IUserRepository'
import type { CreateUserInput } from '../../domain/use-cases/user/CreateUserUseCase'
import { InMemoryUserRepository } from '../../infrastructure/repositories/InMemoryUserRepository'

describe('UserService', () => {
  let mockRepository: jest.Mocked<IUserRepository>
  let service: UserService

  beforeEach(() => {
    mockRepository = {
      create: jest.fn(),
      findAll: jest.fn(),
      findById: jest.fn(),
      update: jest.fn(),
      delete: jest.fn(),
      findByEmail: jest.fn(),
      findByRole: jest.fn()
    } as unknown as jest.Mocked<IUserRepository>

    service = new UserService(mockRepository)
  })

  describe('createUser', () => {
    it('should successfully validate input, trigger CreateUserUseCase, and create a user', async () => {
      const input: CreateUserInput = {
        email: 'test@example.com',
        password: 'securePassword123',
        firstName: 'John',
        lastName: 'Doe',
        phone: '123456789',
        role: 'client'
      }

      const expectedUser = User.fromPrimitives({
        id: 'user-id-123',
        email: input.email,
        firstName: input.firstName ?? null,
        lastName: input.lastName ?? null,
        phone: input.phone ?? null,
        role: input.role,
        isActive: true,
        createdAt: new Date().toISOString()
      })

      mockRepository.create.mockResolvedValue(expectedUser)

      const result = await service.createUser(input)

      expect(result).toBe(expectedUser)
      expect(mockRepository.create).toHaveBeenCalledTimes(1)
      expect(mockRepository.create).toHaveBeenCalledWith(expect.any(User), input.password)
    })

    it('el nombre y apellido llegan al usuario creado (bug real del panel)', async () => {
      // El panel mandaba el formulario snake_case y el nombre se pisaba con
      // undefined; ahora UserManagementContainer mapea a CreateUserInput y el
      // servicio no adivina convenciones.
      const input: CreateUserInput = {
        email: 'panel@example.com',
        password: 'securePassword123',
        firstName: 'Ana',
        lastName: 'Gómez',
        phone: '123456789',
        role: 'receptionist'
      }

      mockRepository.create.mockImplementation(async (user) => user as User)

      await service.createUser(input)

      const createdUser = mockRepository.create.mock.calls[0]![0] as User
      expect(createdUser.firstName).toBe('Ana')
      expect(createdUser.lastName).toBe('Gómez')
    })

    it('rechaza una contraseña de menos de 12 caracteres, el mismo piso que el backend', async () => {
      const input: CreateUserInput = {
        email: 'test@example.com',
        password: 'abcdefgh123',
        role: 'client'
      }

      await expect(service.createUser(input)).rejects.toThrow(
        'Error de validación: Verifique los datos ingresados.'
      )
      expect(mockRepository.create).not.toHaveBeenCalled()
    })

    it('should throw validation error when email is invalid', async () => {
      const input = {
        email: 'invalid-email',
        password: '123',
        firstName: 'John',
        lastName: 'Doe',
        role: 'client'
      }

      await expect(service.createUser(input as unknown as CreateUserInput)).rejects.toThrow(
        'Error de validación: Verifique los datos ingresados.'
      )
      expect(mockRepository.create).not.toHaveBeenCalled()
    })
  })

  describe('listUsers', () => {
    it('should call repository findAll with correct parameters', async () => {
      const users = [
        User.fromPrimitives({
          id: '1',
          email: 'user1@example.com',
          firstName: 'U1',
          lastName: 'L1',
          phone: '',
          role: 'client',
          isActive: true,
          createdAt: new Date().toISOString()
        })
      ]
      mockRepository.findAll.mockResolvedValue(users)

      const result = await service.listUsers(true)

      expect(result).toEqual(users)
      expect(mockRepository.findAll).toHaveBeenCalledWith(true)
    })
  })

  describe('deleteUser', () => {
    it('should call repository delete with correct id', async () => {
      mockRepository.delete.mockResolvedValue(undefined)

      await service.deleteUser('user-id')

      expect(mockRepository.delete).toHaveBeenCalledWith('user-id')
    })
  })

  describe('updateUser', () => {
    it('should call repository update with correct arguments', async () => {
      const updatedUser = User.fromPrimitives({
        id: 'user-id',
        email: 'updated@example.com',
        firstName: 'John',
        lastName: 'Doe',
        phone: '',
        role: 'client',
        isActive: true,
        createdAt: new Date().toISOString()
      })

      mockRepository.update.mockResolvedValue(updatedUser)

      const result = await service.updateUser('user-id', { firstName: 'John' })

      expect(result).toBe(updatedUser)
      expect(mockRepository.update).toHaveBeenCalledWith('user-id', {
        firstName: 'John'
      })
    })
  })

  describe('listClients', () => {
    it('pide los usuarios con rol client al repositorio', async () => {
      const repository = new InMemoryUserRepository()
      const clientUser = User.fromPrimitives({
        id: 'cli-1',
        email: 'ana@example.com',
        firstName: 'Ana',
        lastName: null,
        phone: null,
        role: 'client',
        isActive: true,
        createdAt: '2026-09-01T12:00:00+00:00'
      })
      const staffUser = User.fromPrimitives({
        id: 'stf-1',
        email: 'staff@example.com',
        firstName: 'Beto',
        lastName: null,
        phone: null,
        role: 'staff',
        isActive: true,
        createdAt: '2026-09-01T12:00:00+00:00'
      })
      await repository.create(clientUser)
      await repository.create(staffUser)

      const clients = await new UserService(repository).listClients()

      expect(clients.map((user) => user.id)).toEqual(['cli-1'])
    })
  })
})
