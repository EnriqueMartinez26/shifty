import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useService } from './useService'

export interface Notification {
  id: string
  message: string
  read: boolean
  createdAt: string
}

export interface SendNotificationDTO {
  userId: string
  message: string
}

export interface NotificationService {
  getNotifications(): Promise<Notification[]>
  sendNotification(data: SendNotificationDTO): Promise<Notification>
  markAsRead(id: string): Promise<void>
}

/**
 * Hook para gestionar notificaciones a nivel de UI.
 */
export function useNotifications() {
  const queryClient = useQueryClient()
  const notificationService = useService<NotificationService>('notificationService')

  const getNotificationsQuery = useQuery<Notification[]>({
    queryKey: ['notifications'],
    queryFn: () => notificationService.getNotifications(),
    staleTime: 1 * 60 * 1000 // 1 minuto para notificaciones activas
  })

  const sendNotificationMutation = useMutation<Notification, Error, SendNotificationDTO>({
    mutationFn: (data) => notificationService.sendNotification(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })

  const markAsReadMutation = useMutation<void, Error, string>({
    mutationFn: (id) => notificationService.markAsRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })

  return {
    getNotificationsQuery,
    sendNotificationMutation,
    markAsReadMutation
  }
}
export default useNotifications
