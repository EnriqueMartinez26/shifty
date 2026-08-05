import apiClient from '@infrastructure/http/client'

export type ReportExportFormat = 'csv' | 'excel' | 'pdf'

export interface ReportSummaryStats {
  total_appointments: number
  completed_appointments: number
  cancelled_appointments: number
  pending_appointments: number
  confirmed_appointments: number
  total_revenue: number
  average_ticket: number
}

export interface ReportClientStats {
  total_clients: number
  new_clients: number
  returning_clients: number
  inactive_clients: number
}

export interface ReportTopServiceItem {
  service_id: string
  service_name: string
  appointments: number
  completed_appointments: number
  revenue: number
}

export interface ReportTopClientItem {
  client_id: string
  client_name: string
  appointments: number
  completed_appointments: number
  revenue: number
}

export interface ReportDebtClientItem {
  client_id: string
  client_name: string
  balance: number
}

export interface ReportDebtSummary {
  outstanding_balance: number
  debtors_count: number
  average_debt: number
  top_debtors: ReportDebtClientItem[]
}

export interface ReportAppointmentItem {
  public_id: string
  starts_at: string
  ends_at: string
  status: string
  service_name: string
  staff_name: string
  client_name: string
  service_price: number
}

export interface ReportSummary {
  from_date: string
  to_date: string
  stats: ReportSummaryStats
  client_stats: ReportClientStats
  top_services: ReportTopServiceItem[]
  top_clients: ReportTopClientItem[]
  debt_summary: ReportDebtSummary
  appointments: ReportAppointmentItem[]
}

export interface ProfessionalReportItem {
  staff_id: string
  staff_name: string
  appointments: number
  completed_appointments: number
  confirmed_appointments: number
  absent_appointments: number
  cancelled_appointments: number
  used_minutes: number
  used_hours: number
  available_minutes: number
  available_hours: number
  blocked_minutes: number
  blocked_hours: number
  occupancy_rate: number
  revenue: number
}

export interface ProfessionalReports {
  from_date: string
  to_date: string
  professionals: ProfessionalReportItem[]
}

export interface ExportedReport {
  blob: Blob
  filename: string
}

export class ReportsService {
  async getSummary(fromDate: string, toDate: string): Promise<ReportSummary> {
    const { data } = await apiClient.get<ReportSummary>(
      `/reports/summary?from_date=${fromDate}&to_date=${toDate}`
    )
    return data
  }

  async getProfessionalReports(fromDate: string, toDate: string): Promise<ProfessionalReports> {
    const { data } = await apiClient.get<ProfessionalReports>(
      `/reports/professionals?from_date=${fromDate}&to_date=${toDate}`
    )
    return data
  }

  async exportReport(params: {
    format: ReportExportFormat
    fromDate: string
    toDate: string
  }): Promise<ExportedReport> {
    const { data, headers } = await apiClient.post(
      '/reports/export',
      {
        format: params.format,
        from_date: params.fromDate,
        to_date: params.toDate
      },
      { responseType: 'blob' }
    )

    const blob = new Blob([data], {
      type:
        params.format === 'csv'
          ? 'text/csv'
          : params.format === 'excel'
            ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            : 'application/pdf'
    })

    const contentDisposition = headers['content-disposition'] as string | undefined
    let filename = `reporte-turnos.${params.format === 'excel' ? 'xlsx' : params.format}`
    const dispositionFilename = contentDisposition?.split('filename=')[1]
    if (dispositionFilename) {
      filename = dispositionFilename.replace(/"/g, '').trim()
    }

    return { blob, filename }
  }
}

export const reportsService = new ReportsService()
