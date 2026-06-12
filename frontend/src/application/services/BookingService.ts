import { BaseService } from './BaseService'
import type { Appointment } from '../../domain/entities/Appointment'
import type { IBookingRepository } from '../../domain/repositories/IBookingRepository'
import { createBookingSchema } from '../validators/booking.validators'
import type { CreateBookingRequestDTO } from '../dtos/BookingDTO'

/**
 * Service to manage client-facing Booking operations.
 * Extends BaseService<Appointment> to leverage template execute method, logging, and error handling.
 */
export class BookingService extends BaseService<Appointment> {
  protected repository: IBookingRepository

  /**
   * Initializes a new instance of the BookingService.
   *
   * @param bookingRepository The injected Booking repository implementation.
   */
  constructor(bookingRepository: IBookingRepository) {
    super()
    this.repository = bookingRepository
  }

  /**
   * Gets all appointments booked on a specific date.
   *
   * @param date Date string in format YYYY-MM-DD.
   * @returns A promise that resolves to an array of Appointment entities.
   */
  async getAppointmentsByDate(date: string): Promise<Appointment[]> {
    return await this.execute(async () => {
      return await this.repository.findByDate(date)
    }, 'getAppointmentsByDate')
  }

  /**
   * Gets available time slots for a specific service and date.
   *
   * @param serviceId Service ID.
   * @param date Date string in format YYYY-MM-DD.
   * @returns A promise that resolves to the availability object.
   */
  async getAvailability(serviceId: string, date: string): Promise<any> {
    return await this.execute(async () => {
      return await this.repository.getAvailability(serviceId, date)
    }, 'getAvailability')
  }

  /**
   * Creates a new client booking appointment.
   * Validates the input with createBookingSchema.
   *
   * @param data DTO structure containing registration fields.
   * @returns A promise that resolves to the created Appointment entity.
   */
  async createAppointment(data: CreateBookingRequestDTO): Promise<Appointment> {
    return await this.execute(async () => {
      this.validate(data, createBookingSchema)
      const validated = createBookingSchema.parse(data)

      return await this.repository.create(validated)
    }, 'createAppointment')
  }

  /**
   * Confirms a client booking.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async confirmAppointment(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.confirm(id)
    }, 'confirmAppointment')
  }

  /**
   * Completes a client booking.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async completeAppointment(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.complete(id)
    }, 'completeAppointment')
  }

  /**
   * Cancels a client booking.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async cancelAppointment(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.cancel(id)
    }, 'cancelAppointment')
  }

  /**
   * Marks a client booking as absent.
   *
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async markAppointmentAbsent(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.markAbsent(id)
    }, 'markAppointmentAbsent')
  }
}
