import type { ServiceDepositMode, ServiceDepositType } from '@domain/entities/Service'

export interface ServiceFormValues {
  name: string
  description: string
  durationMinutes: number
  price: number
  color: string
  imageUrl: string
  youtubeTrailerUrl: string
  depositMode: ServiceDepositMode
  depositType: ServiceDepositType
  depositAmount: number | null
  /**
   * Conjunto completo de adicionales; el orden es la posicion. Ausente en una
   * edicion: no se tocan (el formulario lo omite si la lista no cambio).
   */
  addons?: ServiceAddonFormValue[]
}

/** Un adicional en el formulario. `key` es solo para React: no viaja. */
export interface ServiceAddonFormValue {
  key: string
  /** Id del adicional guardado; null en uno nuevo. */
  id: string | null
  name: string
  unitPrice: number
  maxQuantity: number
}

export interface StaffFormValues {
  kind: 'person' | 'resource'
  first_name: string
  last_name: string
  email: string
  display_name: string
  service_ids: string[]
}

export interface UserFormValues {
  email: string
  password: string
  first_name: string
  last_name: string
  phone: string
  role: 'admin' | 'staff' | 'receptionist' | 'client'
}
