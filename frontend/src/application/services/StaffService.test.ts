// El singleton `staffService` exportado por StaffService.ts importa el
// apiClient real (que a su vez toca runtime-env.ts / import.meta, que
// ts-jest no compila fuera de node_modules). Se mockea el módulo del
// cliente HTTP para poder cargar la clase bajo test sin arrastrar esa cadena.
jest.mock('../../infrastructure/http/client', () => ({
  __esModule: true,
  default: {}
}))

import { NotFoundError } from '@shared/errors'

import { StaffService } from './StaffService'
import { Staff } from '../../domain/entities/Staff'
import type { IStaffRepository } from '../../domain/repositories/IStaffRepository'

describe('StaffService', () => {
  let mockRepository: jest.Mocked<IStaffRepository>
  let service: StaffService

  beforeEach(() => {
    mockRepository = {
      findAll: jest.fn(),
      findById: jest.fn(),
      create: jest.fn(),
      update: jest.fn(),
      delete: jest.fn()
    } as jest.Mocked<IStaffRepository>

    service = new StaffService(mockRepository)
  })

  describe('listStaff', () => {
    it('should retrieve list of all staff', async () => {
      const staffList = [
        Staff.fromPrimitives({
          public_id: 'staff-1',
          first_name: 'Jane',
          last_name: 'Doe',
          email: 'jane@example.com',
          display_name: 'Jane D.',
          is_active: true,
          service_ids: ['s1']
        })
      ]
      mockRepository.findAll.mockResolvedValue(staffList)

      const result = await service.listStaff()

      expect(result).toBe(staffList)
      expect(mockRepository.findAll).toHaveBeenCalledTimes(1)
    })
  })

  describe('createStaff', () => {
    it('should validate and create new staff', async () => {
      const input = {
        first_name: 'Jane',
        last_name: 'Doe',
        email: 'jane@example.com',
        display_name: 'Jane D.',
        service_ids: ['service-1', 'service-2']
      }

      const createdStaff = Staff.fromPrimitives({
        public_id: 'uuid-1234',
        ...input,
        is_active: true
      })

      mockRepository.create.mockResolvedValue(createdStaff)

      const result = await service.createStaff(input)

      expect(result).toBe(createdStaff)
      expect(mockRepository.create).toHaveBeenCalledWith(expect.any(Staff))
    })

    it('should throw validation error if email is invalid', async () => {
      const input = {
        first_name: 'Jane',
        last_name: 'Doe',
        email: 'invalid-email',
        display_name: 'Jane D.',
        service_ids: []
      }

      await expect(service.createStaff(input)).rejects.toThrow(
        'Error de validación: Verifique los datos ingresados.'
      )
      expect(mockRepository.create).not.toHaveBeenCalled()
    })

    it('un recurso (cancha, sala) se crea sin email ni nombre', async () => {
      mockRepository.create.mockImplementation(async (staff) => staff)

      const result = await service.createStaff({
        kind: 'resource',
        display_name: 'Cancha 2',
        service_ids: ['service-1']
      })

      expect(result.isResource).toBe(true)
      expect(result.email).toBeNull()
      expect(result.displayName).toBe('Cancha 2')
      expect(result.toPrimitives()).toMatchObject({ kind: 'resource', email: null })
    })

    it('una persona sin email sigue siendo rechazada', async () => {
      await expect(
        service.createStaff({
          kind: 'person',
          display_name: 'Ana P.',
          service_ids: ['service-1']
        })
      ).rejects.toThrow('Error de validación')
      expect(mockRepository.create).not.toHaveBeenCalled()
    })
  })

  describe('updateStaff', () => {
    it('manda solo lo editado, sin leer el staff entero antes (F8-13)', async () => {
      const saved = Staff.fromPrimitives({
        public_id: 'staff-id',
        first_name: 'Jane',
        last_name: 'Doe',
        email: 'jane@example.com',
        display_name: 'Jane D.',
        is_active: true,
        service_ids: ['s2']
      })
      mockRepository.update.mockResolvedValue(saved)

      const result = await service.updateStaff('staff-id', {
        kind: 'person',
        first_name: 'Jane',
        last_name: 'Doe',
        email: 'jane@example.com',
        display_name: 'Jane D.',
        service_ids: ['s2']
      })

      expect(result).toBe(saved)
      expect(mockRepository.findById).not.toHaveBeenCalled()
      expect(mockRepository.update).toHaveBeenCalledWith('staff-id', {
        firstName: 'Jane',
        lastName: 'Doe',
        email: 'jane@example.com',
        displayName: 'Jane D.',
        serviceIds: ['s2']
      })
    })

    it('editar un recurso no le manda nombre, apellido ni email', async () => {
      const cancha = Staff.fromPrimitives({
        public_id: 'cancha-1',
        kind: 'resource',
        first_name: '',
        last_name: '',
        email: null,
        display_name: 'Cancha 1 (techada)',
        is_active: true,
        service_ids: ['s1', 's2']
      })
      mockRepository.update.mockResolvedValue(cancha)

      await service.updateStaff('cancha-1', {
        kind: 'resource',
        display_name: 'Cancha 1 (techada)',
        service_ids: ['s1', 's2']
      })

      expect(mockRepository.update).toHaveBeenCalledWith('cancha-1', {
        displayName: 'Cancha 1 (techada)',
        serviceIds: ['s1', 's2']
      })
    })

    it('el staff inexistente viaja como NotFoundError, no como Error crudo (F9-10)', async () => {
      // El 404 del backend llega normalizado como NotFoundError desde el repo.
      mockRepository.update.mockRejectedValue(new NotFoundError('Staff no encontrado'))

      // handleError re-envuelve, pero conserva el original en `originalError`.
      const error: unknown = await service
        .updateStaff('invalid-id', {
          first_name: 'Jane',
          last_name: 'Doe',
          email: 'jane@example.com',
          display_name: 'Jane D.',
          service_ids: ['service-1']
        })
        .catch((reason: unknown) => reason)

      expect(error).toMatchObject({ message: 'Staff no encontrado' })
      expect((error as { originalError?: unknown }).originalError).toBeInstanceOf(NotFoundError)
    })
  })

  describe('deleteStaff', () => {
    it('should call delete on repository', async () => {
      mockRepository.delete.mockResolvedValue(undefined)

      await service.deleteStaff('staff-id')

      expect(mockRepository.delete).toHaveBeenCalledWith('staff-id')
    })
  })
})
