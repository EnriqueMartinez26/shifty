import apiClient from '@infrastructure/http/client'

export interface NotificationRecord {
  public_id: string
  type: string
  title: string
  body?: string | null
  appointment_id?: string | null
  read_at?: string | null
  created_at: string
}

export interface NotificationList {
  items: NotificationRecord[]
  unread_count: number
}

export interface NotificationMarkReadResult {
  updated: number
  unread_count: number
}

export class NotificationsService {
  async list(limit = 20, unreadOnly = false): Promise<NotificationList> {
    const { data } = await apiClient.get<NotificationList>('/notifications', {
      params: { limit, unread_only: unreadOnly }
    })
    return data
  }

  async markRead(notificationId: string): Promise<NotificationMarkReadResult> {
    const { data } = await apiClient.post<NotificationMarkReadResult>(
      `/notifications/${notificationId}/read`
    )
    return data
  }

  async markAllRead(): Promise<NotificationMarkReadResult> {
    const { data } = await apiClient.post<NotificationMarkReadResult>('/notifications/read-all')
    return data
  }
}

export const notificationsService = new NotificationsService()
