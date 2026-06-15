import apiClient from '@infrastructure/http/client'

export interface DashboardStats {
  appointments_today: number
  pending_confirmations: number
  occupancy_rate: number
  new_clients_last_30d: number
  weekly_revenue: number
  revenue_trend: number
  average_appointment_minutes: number
}

export interface UpcomingAppointment {
  public_id: string
  starts_at: string
  status: string
  service_name: string
  staff_name: string
  client_name: string
}

export interface DashboardSummary {
  stats: DashboardStats
  upcoming_appointments: UpcomingAppointment[]
}

export class DashboardService {
  async getSummary(): Promise<DashboardSummary> {
    const { data } = await apiClient.get<DashboardSummary>('/dashboard/summary')
    return data
  }
}

export const dashboardService = new DashboardService()
