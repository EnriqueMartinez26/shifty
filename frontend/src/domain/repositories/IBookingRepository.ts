import type { CreateBookingRequestDTO } from '../../application/dtos/BookingDTO'
import { Appointment } from '../entities/Appointment'

export interface IBookingRepository {
  findByDate(date: string): Promise<Appointment[]>
  searchByDateRange(fromDate: string, toDate: string, pageSize?: number): Promise<Appointment[]>
  getAvailability(serviceId: string, date: string): Promise<Record<string, unknown>>
  create(payload: CreateBookingRequestDTO): Promise<Appointment>
  confirm(id: string): Promise<void>
  complete(id: string): Promise<void>
  cancel(id: string): Promise<void>
  release(id: string): Promise<void>
  markAbsent(id: string): Promise<void>
}
