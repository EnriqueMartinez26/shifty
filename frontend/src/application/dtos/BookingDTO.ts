export interface AppointmentResponseDTO {
  public_id: string
  service_id: string
  service_name: string
  staff_id: string
  // Nombre autoritativo del profesional (viene del join en el backend). Opcional
  // para tolerar payloads que aun no lo traigan.
  staff_name?: string | null
  client_name: string
  // Solo lo manda el backend a administradores; el resto recibe null.
  client_phone?: string | null
  starts_at: string
  ends_at: string
  status: string
  notes: string | null
}

// El input de creacion vive en el dominio (IBookingRepository) para no invertir
// la direccion de dependencias; aca se reexporta con el nombre historico.
export type { CreateBookingInput as CreateBookingRequestDTO } from '../../domain/repositories/IBookingRepository'
