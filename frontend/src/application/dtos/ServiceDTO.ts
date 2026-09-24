import type { ServiceDepositMode, ServiceDepositType } from '../../domain/entities/Service'

export interface ServiceResponseDTO {
  public_id: string
  name: string
  description: string | null
  duration_minutes: number
  price: number
  color: string | null
  image_url: string | null
  youtube_trailer_url: string | null
  // La politica de sena la devuelve `ServiceResponse` por herencia de
  // `ServiceBase`. Sin leerla, el formulario de edicion arrancaba en "none" y
  // guardar apagaba la sena de un servicio que la tenia configurada.
  deposit_mode: ServiceDepositMode
  deposit_type: ServiceDepositType
  deposit_amount: number | null
  is_active: boolean
}
