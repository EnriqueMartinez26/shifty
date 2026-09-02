import { Appointment } from '../entities/Appointment'

/**
 * Datos para crear un turno. Vive en el dominio (no en application) para que el
 * puerto IBookingRepository no dependa de una capa externa: la regla de
 * dependencias apunta hacia adentro. La capa de aplicacion lo reexporta como
 * CreateBookingRequestDTO por compatibilidad.
 */
export interface CreateBookingInput {
  store_public_id?: string
  service_id: string
  staff_id?: string
  starts_at: string
  client_name: string
  client_email?: string
  client_phone: string
  notes?: string
  idempotency_key?: string
}

export interface IBookingRepository {
  findByDate(date: string): Promise<Appointment[]>
  searchByDateRange(fromDate: string, toDate: string, pageSize?: number): Promise<Appointment[]>
  getAvailability(serviceId: string, date: string): Promise<Record<string, unknown>>
  create(payload: CreateBookingInput): Promise<Appointment>
  confirm(id: string): Promise<void>
  complete(id: string): Promise<void>
  cancel(id: string): Promise<void>
  release(id: string): Promise<void>
  markAbsent(id: string): Promise<void>
  reschedule(id: string, newStartTime: string, newEndTime?: string): Promise<void>
}
