import apiClient from '@infrastructure/http/client'

export interface AppointmentBlock {
  public_id: string
  staff_id: string
  starts_at: string
  ends_at: string
  reason: string
  is_active: boolean
}

export interface AppointmentBlockPayload {
  staff_id: string
  starts_at: string
  ends_at: string
  reason: string
  /** Cancela en bloque los turnos reservados adentro (solo administradores). */
  cancel_affected?: boolean
}

/**
 * PATCH de un bloqueo. Sin `staff_id` ni `is_active`: el backend no cambia el
 * profesional de un bloqueo (lo descartaba en silencio, FF-11) y editar no
 * reactiva uno desactivado (D-20260929-11).
 */
export type AppointmentBlockUpdatePayload = Partial<
  Pick<AppointmentBlockPayload, 'starts_at' | 'ends_at' | 'reason' | 'cancel_affected'>
>

export interface BlockPreviewPayload {
  staff_id: string | null
  starts_at: string
  ends_at: string
  recurrence?: 'none' | 'daily' | 'weekly'
  recurrence_until?: string
  max_occurrences?: number
}

export interface AffectedAppointment {
  public_id: string
  client_name: string
  client_phone: string | null
  service_name: string
  staff_name: string
  starts_at: string
  ends_at: string
  status: string
  /** null = se cancela; 'pending_payment' | 'has_deposit' = requiere decision humana. */
  blocker: string | null
  cancellable: boolean
}

export interface BlockPreviewResult {
  ranges: number
  affected: AffectedAppointment[]
}

export interface RecurringAppointmentBlockPayload extends AppointmentBlockPayload {
  recurrence: 'none' | 'daily' | 'weekly'
  recurrence_until?: string
  max_occurrences?: number
}

export interface BlockTemplate {
  key: string
  label: string
  reason: string
}

export interface RecurringBlocksResult {
  created: number
  blocks: AppointmentBlock[]
}

/**
 * Filtro del listado (F4-07, FF-12). `from_date` y `to_date` son dias locales
 * `YYYY-MM-DD` y van juntos (el backend acepta hasta 400 dias);
 * `include_inactive: false` saca los bloqueos desactivados.
 */
export interface AppointmentBlockListParams {
  from_date: string
  to_date: string
  include_inactive?: boolean
}

class AppointmentBlocksService {
  async list(params: AppointmentBlockListParams): Promise<AppointmentBlock[]> {
    const { data } = await apiClient.get<AppointmentBlock[]>('/appointment-blocks/', { params })
    return data
  }

  async getTemplates(): Promise<BlockTemplate[]> {
    const { data } = await apiClient.get<BlockTemplate[]>('/appointment-blocks/templates')
    return data
  }

  async preview(payload: BlockPreviewPayload): Promise<BlockPreviewResult> {
    const { data } = await apiClient.post<BlockPreviewResult>(
      '/appointment-blocks/preview',
      payload
    )
    return data
  }

  async create(payload: AppointmentBlockPayload): Promise<AppointmentBlock> {
    const { data } = await apiClient.post<AppointmentBlock>('/appointment-blocks/', payload)
    return data
  }

  async createRecurring(payload: RecurringAppointmentBlockPayload): Promise<RecurringBlocksResult> {
    const { data } = await apiClient.post<RecurringBlocksResult>(
      '/appointment-blocks/batch',
      payload
    )
    return data
  }

  async update(
    publicId: string,
    payload: AppointmentBlockUpdatePayload
  ): Promise<AppointmentBlock> {
    const { data } = await apiClient.patch<AppointmentBlock>(
      `/appointment-blocks/${publicId}`,
      payload
    )
    return data
  }

  async delete(publicId: string): Promise<void> {
    await apiClient.delete(`/appointment-blocks/${publicId}`)
  }
}

export const appointmentBlocksService = new AppointmentBlocksService()
