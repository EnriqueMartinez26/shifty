import { AppointmentService } from './AppointmentService'
import type { Appointment } from '../../domain/entities/Appointment'
import type { IBookingRepository } from '../../domain/repositories/IBookingRepository'

describe('AppointmentService', () => {
  let mockRepository: jest.Mocked<IBookingRepository>
  let service: AppointmentService

  beforeEach(() => {
    mockRepository = {
      findByDate: jest.fn(),
      searchByDateRange: jest.fn(),
      getAvailability: jest.fn(),
      create: jest.fn(),
      confirm: jest.fn(),
      complete: jest.fn(),
      cancel: jest.fn(),
      markAbsent: jest.fn()
    } as any

    service = new AppointmentService(mockRepository)
  })

  describe('getCalendarRange', () => {
    it('should retrieve list of appointments for a date range', async () => {
      const appointments = [{ id: 'appt-2' }] as Appointment[]
      mockRepository.searchByDateRange.mockResolvedValue(appointments)

      const result = await service.getCalendarRange('2026-05-18', '2026-05-25')

      expect(result).toBe(appointments)
      expect(mockRepository.searchByDateRange).toHaveBeenCalledWith('2026-05-18', '2026-05-25', 500)
    })
  })

  describe('bookAppointment', () => {
    it('should call repository create with internal admin payload format', async () => {
      const input = {
        service_id: 's-1',
        staff_id: 'st-1',
        starts_at: '2026-05-18T10:00:00Z',
        client_name: 'Bob Ross',
        client_phone: '+5491112345678',
        notes: 'Happy little trees'
      }

      const mockAppt = { id: 'appt-2', ...input } as any as Appointment
      mockRepository.create.mockResolvedValue(mockAppt)

      const result = await service.bookAppointment(input)

      expect(result).toBe(mockAppt)
      expect(mockRepository.create).toHaveBeenCalledWith(input)
    })
  })

  describe('confirm', () => {
    it('should confirm appointment', async () => {
      mockRepository.confirm.mockResolvedValue(undefined)

      await service.confirm('appt-id')

      expect(mockRepository.confirm).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('complete', () => {
    it('should complete appointment', async () => {
      mockRepository.complete.mockResolvedValue(undefined)

      await service.complete('appt-id')

      expect(mockRepository.complete).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('cancel', () => {
    it('should cancel appointment', async () => {
      mockRepository.cancel.mockResolvedValue(undefined)

      await service.cancel('appt-id')

      expect(mockRepository.cancel).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('markAbsent', () => {
    it('should mark client as absent', async () => {
      mockRepository.markAbsent.mockResolvedValue(undefined)

      await service.markAbsent('appt-id')

      expect(mockRepository.markAbsent).toHaveBeenCalledWith('appt-id')
    })
  })

  describe('reschedule', () => {
    it('should output reschedule trace', async () => {
      const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})

      await service.reschedule('appt-id', '2026-05-18T12:00:00Z', '2026-05-18T13:00:00Z')

      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Rescheduling appt-id to 2026-05-18T12:00:00Z')
      )

      consoleWarnSpy.mockRestore()
    })
  })
})
