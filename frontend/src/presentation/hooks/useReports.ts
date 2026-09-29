import { useMutation, useQuery } from '@tanstack/react-query'

import {
  reportsService,
  type ExportedReport,
  type ProfessionalReports,
  type ReportDetailPage,
  type ReportExportFormat,
  type ReportSummary,
  type ReportTrend
} from '@application/services/ReportsService'

export type { ReportExportFormat }

/**
 * Sin `page` el backend usa su default (el Dashboard). La clave lleva SIEMPRE
 * limit y offset: sin eso, la pagina de Reportes y el Dashboard compartirian
 * cache con detalles de distinto largo para el mismo rango.
 */
export const useReportSummary = (
  fromDate: string,
  toDate: string,
  enabled = true,
  page?: ReportDetailPage
) => {
  return useQuery({
    queryKey: ['reports-summary', fromDate, toDate, page?.limit ?? null, page?.offset ?? 0],
    enabled: Boolean(fromDate && toDate && enabled),
    // Solo entre paginas del MISMO rango: con otro rango, los datos viejos
    // pasaban por actuales sin spinner.
    placeholderData: (prev, prevQuery) =>
      prevQuery?.queryKey[1] === fromDate && prevQuery.queryKey[2] === toDate ? prev : undefined,
    queryFn: (): Promise<ReportSummary> => reportsService.getSummary(fromDate, toDate, page)
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
