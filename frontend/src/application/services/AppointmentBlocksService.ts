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

export class AppointmentBlocksService {
  async list(): Promise<AppointmentBlock[]> {
    const { data } = await apiClient.get<AppointmentBlock[]>('/appointment-blocks/')
    return data
  }

  async getTemplates(): Promise<BlockTemplate[]> {
    const { data } = await apiClient.get<BlockTemplate[]>('/appointment-blocks/templates')
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
    payload: Partial<AppointmentBlockPayload> & { is_active?: boolean }
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
