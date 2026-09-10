import { useMutation, useQuery } from '@tanstack/react-query'

import {
  reportsService,
  type ExportedReport,
  type ProfessionalReports,
  type ReportExportFormat,
  type ReportSummary,
  type ReportTrend
} from '@application/services/ReportsService'

export type { ProfessionalReports, ReportExportFormat, ReportSummary, ReportTrend }

export const useReportSummary = (fromDate: string, toDate: string, enabled = true) => {
  return useQuery({
    queryKey: ['reports-summary', fromDate, toDate],
    enabled: Boolean(fromDate && toDate && enabled),
    queryFn: (): Promise<ReportSummary> => reportsService.getSummary(fromDate, toDate)
  })
}

export const useProfessionalReports = (fromDate: string, toDate: string, enabled = true) => {
  return useQuery({
    queryKey: ['reports-professionals', fromDate, toDate],
    enabled: Boolean(fromDate && toDate && enabled),
    queryFn: (): Promise<ProfessionalReports> =>
      reportsService.getProfessionalReports(fromDate, toDate)
  })
}

export const useReportTrend = (months = 6, enabled = true) => {
  return useQuery({
    queryKey: ['reports-trend', months],
    enabled: Boolean(enabled) && months > 0,
    queryFn: (): Promise<ReportTrend> => reportsService.getTrend(months)
  })
}

export const useExportReport = () => {
  return useMutation<
    ExportedReport,
    Error,
    { format: ReportExportFormat; fromDate: string; toDate: string }
  >({
    mutationFn: (params) => reportsService.exportReport(params)
  })
}
