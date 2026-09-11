// El singleton `staffService` exportado por StaffService.ts importa el
// apiClient real (que a su vez toca runtime-env.ts / import.meta, que
// ts-jest no compila fuera de node_modules). Se mockea el módulo del
// cliente HTTP para poder cargar la clase bajo test sin arrastrar esa cadena.
jest.mock('../../infrastructure/http/client', () => ({
  __esModule: true,
  default: {}
}))

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
    it('should retrieve existing, validate updates, and save them', async () => {
      const existingStaff = Staff.fromPrimitives({
        public_id: 'staff-id',
        first_name: 'OldName',
        last_name: 'OldLastName',
        email: 'old@example.com',
        display_name: 'Old D.',
        is_active: true,
        service_ids: ['s1']
      })

      const updatedInput = {
        first_name: 'Jane',
        last_name: 'Doe',
        email: 'jane@example.com',
        display_name: 'Jane D.',
        service_ids: ['s2']
      }

      const expectedStaff = Staff.fromPrimitives({
        public_id: 'staff-id',
        ...updatedInput,
        is_active: true
      })

      mockRepository.findById.mockResolvedValue(existingStaff)
      mockRepository.update.mockResolvedValue(expectedStaff)

      const result = await service.updateStaff('staff-id', updatedInput)

      expect(result).toBe(expectedStaff)
      expect(mockRepository.findById).toHaveBeenCalledWith('staff-id')
      expect(mockRepository.update).toHaveBeenCalledWith('staff-id', expect.any(Staff))
    })

    it('editar un recurso no le inventa un email', async () => {
      const cancha = Staff.fromPrimitives({
        public_id: 'cancha-1',
        kind: 'resource',
        first_name: '',
        last_name: '',
        email: null,
        display_name: 'Cancha 1',
        is_active: true,
        service_ids: ['s1']
      })
      mockRepository.findById.mockResolvedValue(cancha)
      mockRepository.update.mockImplementation(async (_id, staff) => staff)

      const result = await service.updateStaff('cancha-1', {
        kind: 'resource',
        display_name: 'Cancha 1 (techada)',
        service_ids: ['s1', 's2']
      })

      expect(result.isResource).toBe(true)
      expect(result.email).toBeNull()
      expect(result.displayName).toBe('Cancha 1 (techada)')
    })

    it('should throw error if staff is not found', async () => {
      mockRepository.findById.mockResolvedValue(null)

      await expect(
        service.updateStaff('invalid-id', {
          first_name: 'Jane',
          last_name: 'Doe',
          email: 'jane@example.com',
          display_name: 'Jane D.',
          service_ids: []
        })
      ).rejects.toThrow('Staff no encontrado')
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
