import apiClient from '@infrastructure/http/client'

export type WaitlistStatus = 'waiting' | 'offered' | 'booked' | 'cancelled' | 'expired'

export interface WaitlistEntry {
  public_id: string
  status: WaitlistStatus
  service_id: string
  service_name: string
  staff_id: string | null
  staff_name: string | null
  window_starts_at: string
  window_ends_at: string
  client_name: string
  /** Solo lo recibe un administrador; el resto del personal ve null. */
  client_phone: string | null
  client_email: string | null
  notes: string | null
  notified_at: string | null
  offer_expires_at: string | null
  offered_starts_at: string | null
  offered_staff_id: string | null
  created_at: string
}

export interface WaitlistBookPayload {
  starts_at: string
  staff_id?: string | null
}

export interface WaitlistBookedAppointment {
  public_id: string
  service_id: string
  staff_id: string
  starts_at: string
  ends_at: string
  status: string
}

/** Lista de espera del panel del dueno. */
export class WaitlistService {
  async list(): Promise<WaitlistEntry[]> {
    const { data } = await apiClient.get<WaitlistEntry[]>('/waitlist/')
    return data
  }

  async remove(entryId: string): Promise<void> {
    await apiClient.delete(`/waitlist/${entryId}`)
  }

  async book(entryId: string, payload: WaitlistBookPayload): Promise<WaitlistBookedAppointment> {
    const { data } = await apiClient.post<WaitlistBookedAppointment>(
      `/waitlist/${entryId}/book`,
      payload
    )
    return data
  }
}

export const waitlistService = new WaitlistService()
