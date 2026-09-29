import { Appointment } from '../entities/Appointment'

/**
 * Alta de un turno para un cliente desde el panel (POST /appointments/, FF-04).
 * Vive en el dominio para que el puerto no dependa de una capa externa.
 * `idempotency_key` es obligatoria: la genera quien arma el formulario, que es
 * el unico que sabe si un envio es un reintento del mismo turno.
 */
export interface CreateBookingInput {
  service_id: string
  staff_id?: string
  starts_at: string
  client_name: string
  client_email?: string
  client_phone: string
  notes?: string
  idempotency_key: string
}

/**
 * Turnos de un rango. `total` es lo que el servidor dice que hay; si supera
 * `appointments.length`, la lista vino recortada por el tope de paginas y el
 * llamador tiene que avisarlo en vez de mostrarla como completa.
 */
export interface AppointmentRange {
  appointments: Appointment[]
  total: number
}

export interface IBookingRepository {
  searchByDateRange(fromDate: string, toDate: string, pageSize?: number): Promise<AppointmentRange>
  /** Devuelve el `public_id` del turno creado. */
  create(payload: CreateBookingInput): Promise<string>
  confirm(id: string): Promise<void>
  complete(id: string): Promise<void>
  cancel(id: string): Promise<void>
  release(id: string): Promise<void>
  markAbsent(id: string): Promise<void>
  reschedule(id: string, newStartTime: string, newEndTime?: string): Promise<void>
}
