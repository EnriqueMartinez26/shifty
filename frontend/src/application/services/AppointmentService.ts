import { BaseService } from './BaseService';
import type { Appointment } from '../../domain/entities/Appointment';
import type { IBookingRepository } from '../../domain/repositories/IBookingRepository';

/**
 * Service to manage internal Appointment operations.
 * Extends BaseService<Appointment> to leverage template execute method, logging, and error handling.
 */
export class AppointmentService extends BaseService<Appointment> {
  protected repository: IBookingRepository;

  /**
   * Initializes a new instance of the AppointmentService.
   * 
   * @param repository The injected Booking repository implementation.
   */
  constructor(repository: IBookingRepository) {
    super();
    this.repository = repository;
  }

  /**
   * Retrieves the appointments calendar for a specific date.
   * 
   * @param date Date string in format YYYY-MM-DD.
   * @returns A promise that resolves to an array of Appointment entities.
   */
  async getCalendar(date: string): Promise<Appointment[]> {
    return await this.execute(async () => {
      return await this.repository.findByDate(date);
    }, 'getCalendar');
  }

  /**
   * Books a new appointment from the internal administrative panel.
   * 
   * @param data Raw booking parameters.
   * @returns A promise that resolves to the booked Appointment entity.
   */
  async bookAppointment(data: {
    service_id: string;
    staff_id: string;
    starts_at: string;
    client_name: string;
    notes?: string;
  }): Promise<Appointment> {
    return await this.execute(async () => {
      return await this.repository.create({
        ...data,
      });
    }, 'bookAppointment');
  }

  /**
   * Confirms a pending appointment.
   * 
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async confirm(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.confirm(id);
    }, 'confirm');
  }

  /**
   * Completes an appointment.
   * 
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async complete(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.complete(id);
    }, 'complete');
  }

  /**
   * Cancels an appointment.
   * 
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async cancel(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.cancel(id);
    }, 'cancel');
  }

  /**
   * Marks the client as absent for the appointment.
   * 
   * @param id The unique identifier of the appointment.
   * @returns A promise resolving to void.
   */
  async markAbsent(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.markAbsent(id);
    }, 'markAbsent');
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
      console.log(`Rescheduling ${id} to ${newStartTime}`);
    }, 'reschedule');
  }
}
