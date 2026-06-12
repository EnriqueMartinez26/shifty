import { Appointment } from '../entities/Appointment'

export interface IBookingRepository {
  findByDate(date: string): Promise<Appointment[]>
  getAvailability(serviceId: string, date: string): Promise<any>
  create(payload: any): Promise<Appointment>
  confirm(id: string): Promise<void>
  complete(id: string): Promise<void>
  cancel(id: string): Promise<void>
  markAbsent(id: string): Promise<void>
}
