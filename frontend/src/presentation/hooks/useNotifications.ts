import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  notificationsService,
  type NotificationList,
  type NotificationMarkReadResult
} from '@application/services/NotificationsService'

const NOTIFICATIONS_QUERY_KEY = ['notifications']

export const useNotifications = (limit = 20) =>
  useQuery<NotificationList>({
    queryKey: [...NOTIFICATIONS_QUERY_KEY, limit],
    queryFn: () => notificationsService.list(limit),
    // El dueño necesita enterarse de una seña acreditada sin recargar la página.
    refetchInterval: 60_000
  })

export const useMarkNotificationRead = () => {
  const queryClient = useQueryClient()
  return useMutation<NotificationMarkReadResult, Error, string>({
    mutationFn: (notificationId) => notificationsService.markRead(notificationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_QUERY_KEY })
    }
  })
}

export const useMarkAllNotificationsRead = () => {
  const queryClient = useQueryClient()
  return useMutation<NotificationMarkReadResult, Error>({
    mutationFn: () => notificationsService.markAllRead(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_QUERY_KEY })
    }
  })
}
