export interface AppointmentResponseDTO {
  public_id: string
  service_id: string
  service_name: string
  staff_id: string
  client_name: string
  starts_at: string
  ends_at: string
  status: string
  notes: string | null
}

// El input de creacion vive en el dominio (IBookingRepository) para no invertir
// la direccion de dependencias; aca se reexporta con el nombre historico.
export type { CreateBookingInput as CreateBookingRequestDTO } from '../../domain/repositories/IBookingRepository'
