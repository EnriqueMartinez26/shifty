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
  /** Diseño previo (S7). Opcionales: un backend anterior no los manda. */
  requires_prior_design?: boolean
  prior_design_message?: string | null
  /** Ordenados por `position`. Opcional: se tolera un payload que no los traiga. */
  addons?: ServiceAddonDTO[]
}

interface ServiceAddonDTO {
  id: string
  name: string
  unit_price: number
  max_quantity: number
  position: number
}
