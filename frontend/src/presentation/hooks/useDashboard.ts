import { useQuery } from '@tanstack/react-query'

import { dashboardService, type DashboardSummary } from '@application/services/DashboardService'

export const useDashboardSummary = (enabled = true) => {
  return useQuery({
    queryKey: ['dashboard-summary'],
    enabled,
    queryFn: (): Promise<DashboardSummary> => dashboardService.getSummary()
  })
}
