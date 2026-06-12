import { BookingService } from './BookingService'
import type { IBookingRepository } from '../../domain/repositories/IBookingRepository'
import type { Appointment } from '../../domain/entities/Appointment'
import type { CreateBookingRequestDTO } from '../dtos/BookingDTO'

describe('BookingService', () => {
  let mockRepository: jest.Mocked<IBookingRepository>
  let service: BookingService

  beforeEach(() => {
    mockRepository = {
      findByDate: jest.fn(),
      getAvailability: jest.fn(),
      create: jest.fn(),
      confirm: jest.fn(),
      complete: jest.fn(),
      cancel: jest.fn(),
      markAbsent: jest.fn()
    } as any

    service = new BookingService(mockRepository)
  })

  describe('getAppointmentsByDate', () => {
    it('should query appointments by date', async () => {
      const appointments = [{ id: 'appt-1' }] as Appointment[]
      mockRepository.findByDate.mockResolvedValue(appointments)

      const result = await service.getAppointmentsByDate('2026-05-18')

      expect(result).toBe(appointments)
      expect(mockRepository.findByDate).toHaveBeenCalledWith('2026-05-18')
    })
  })

  describe('getAvailability', () => {
    it('should query availability slots', async () => {
      const mockSlots = { date: '2026-05-18', slots: ['09:00', '10:00'] }
      mockRepository.getAvailability.mockResolvedValue(mockSlots)

      const result = await service.getAvailability('service-id', '2026-05-18')

      expect(result).toBe(mockSlots)
      expect(mockRepository.getAvailability).toHaveBeenCalledWith('service-id', '2026-05-18')
    })
  })

  describe('createAppointment', () => {
    it('should validate and create client booking', async () => {
      const input: CreateBookingRequestDTO = {
        service_id: 's-123',
        staff_id: 'st-456',
        starts_at: '2026-05-18T10:00:00Z',
        client_name: 'Alice Johnson',
        client_email: 'alice@example.com',
        client_phone: '123456789',
        notes: 'Some note'
      }

      const expectedAppt = { id: 'appt-uuid-1', ...input } as any as Appointment
      mockRepository.create.mockResolvedValue(expectedAppt)

      const result = await service.createAppointment(input)

      expect(result).toBe(expectedAppt)
      // Validate mapping in repository payload
      expect(mockRepository.create).toHaveBeenCalledWith({
        service_id: input.service_id,
        staff_id: input.staff_id,
        starts_at: input.starts_at,
        client_name: input.client_name,
        client_email: input.client_email,
        client_phone: input.client_phone,
        notes: input.notes
      })
    })

    it('should throw validation error on invalid input formats', async () => {
      const invalidInput = {
        service_id: '', // Invalid empty ID
        staff_id: 'st-456',
        starts_at: '2026-05-18T10:00:00Z',
        client_name: 'Alice',
        client_email: 'not-an-email', // Invalid email format
        client_phone: ''
      }

      await expect(service.createAppointment(invalidInput as any)).rejects.toThrow(
        'Error de validación: Verifique los datos ingresados.'
      )
      expect(mockRepository.create).not.toHaveBeenCalled()
    })
  })

  describe('confirmAppointment', () => {
    it('should call repository confirm', async () => {
      mockRepository.confirm.mockResolvedValue(undefined)

      await service.confirmAppointment('appt-id')

      expect(mockRepository.confirm).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('completeAppointment', () => {
    it('should call repository complete', async () => {
      mockRepository.complete.mockResolvedValue(undefined)

      await service.completeAppointment('appt-id')

      expect(mockRepository.complete).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('cancelAppointment', () => {
    it('should call repository cancel', async () => {
      mockRepository.cancel.mockResolvedValue(undefined)

      await service.cancelAppointment('appt-id')

      expect(mockRepository.cancel).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('markAppointmentAbsent', () => {
    it('should call repository markAbsent', async () => {
      mockRepository.markAbsent.mockResolvedValue(undefined)

      await service.markAppointmentAbsent('appt-id')

      expect(mockRepository.markAbsent).toHaveBeenCalledWith('appt-id')
    })
  })
})
