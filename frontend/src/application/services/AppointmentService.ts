import { BaseService } from './BaseService'
import type { Appointment } from '../../domain/entities/Appointment'
import type { IBookingRepository } from '../../domain/repositories/IBookingRepository'
import type { CreateBookingRequestDTO } from '../dtos/BookingDTO'

/**
 * Service to manage internal Appointment operations.
 * Extends BaseService<Appointment> to leverage template execute method, logging, and error handling.
 */
export class AppointmentService extends BaseService<Appointment> {
  protected repository: IBookingRepository

  /**
   * Initializes a new instance of the AppointmentService.
   *
   * @param repository The injected Booking repository implementation.
   */
  constructor(repository: IBookingRepository) {
    super()
    this.repository = repository
  }

  async getCalendarRange(fromDate: string, toDate: string, pageSize = 100): Promise<Appointment[]> {
    return await this.execute(async () => {
      return await this.repository.searchByDateRange(fromDate, toDate, pageSize)
    }, 'getCalendarRange')
  }

  /**
   * Books a new appointment from the internal administrative panel.
   *
   * @param data Raw booking parameters.
   * @returns A promise that resolves to the booked Appointment entity.
   */
  async bookAppointment(data: CreateBookingRequestDTO): Promise<Appointment> {
    return await this.execute(async () => {
      return await this.repository.create({
        ...data
      })
    }, 'bookAppointment')
  }

  /**
   * Confirms a pending appointment.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async confirm(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.confirm(id)
    }, 'confirm')
  }

  /**
   * Completes an appointment.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async complete(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.complete(id)
    }, 'complete')
  }

  /**
   * Cancels an appointment.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async cancel(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.cancel(id)
    }, 'cancel')
  }

  async release(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.release(id)
    }, 'release')
  }

  /**
   * Marks the client as absent for the appointment.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async markAbsent(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.markAbsent(id)
    }, 'markAbsent')
  }

  /**
   * Reschedules an appointment to a new start time slot.
   *
   * @param id The unique identifier of the appointment.
   * @param newStartTime New start time ISO string.
   * @param _newEndTime Optional new end time ISO string.
   * @returns A promise resolving to void.
   */
  async reschedule(id: string, newStartTime: string, _newEndTime: string): Promise<void> {
    await this.execute(async () => {
      console.warn(`Rescheduling ${id} to ${newStartTime}`)
    }, 'reschedule')
  }
}
