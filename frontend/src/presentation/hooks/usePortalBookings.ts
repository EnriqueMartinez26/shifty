import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  portalBookingsService,
  type BulkCancelResult,
  type PortalBookingsWindowHours,
  type RecentPortalBooking
} from '@application/services/PortalBookingsService'

const PORTAL_BOOKINGS_KEY = 'portal-bookings'

/**
 * Reservas del portal de las ultimas `hours` horas. `enabled` queda en false
 * para quien no gestiona la tienda: el backend le responderia 403.
 */
export const useRecentPortalBookings = (hours: PortalBookingsWindowHours, enabled: boolean) =>
  useQuery<RecentPortalBooking[]>({
    queryKey: [PORTAL_BOOKINGS_KEY, hours],
    queryFn: () => portalBookingsService.listRecent(hours),
    enabled
  })

export const useBulkCancelPortalBookings = () => {
  const queryClient = useQueryClient()
  return useMutation<BulkCancelResult, Error, { ids: string[]; reason?: string }>({
    mutationFn: ({ ids, reason }) => portalBookingsService.bulkCancel(ids, reason),
    onSuccess: () => {
      // Cancelar libera cupos: cambian la lista, la agenda y el resumen.
      void queryClient.invalidateQueries({ queryKey: [PORTAL_BOOKINGS_KEY] })
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] })
    }
  })
}
