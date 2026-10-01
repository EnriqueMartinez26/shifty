// F9-08 (2026-09-30): cobertura de los avisos del panel. Path literal
// (regla 23), verbo y params por metodo.
const mockGet = jest.fn()
const mockPost = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args)
  }
}))

import { notificationsService } from './NotificationsService'

describe('NotificationsService', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockGet.mockResolvedValue({ data: { items: [], unread_count: 0 } })
    mockPost.mockResolvedValue({ data: { updated: 1, unread_count: 0 } })
  })

  it('list sin argumentos pide 20 avisos, leidos y no leidos', async () => {
    await notificationsService.list()

    expect(mockGet).toHaveBeenCalledWith('/notifications', {
      params: { limit: 20, unread_only: false }
    })
  })

  it('list pasa limit y unread_only como params', async () => {
    await notificationsService.list(5, true)

    expect(mockGet).toHaveBeenCalledWith('/notifications', {
      params: { limit: 5, unread_only: true }
    })
  })

  it('markRead marca un aviso por POST', async () => {
    await notificationsService.markRead('not-1')

    expect(mockPost).toHaveBeenCalledWith('/notifications/not-1/read')
  })

  it('markAllRead marca todos por POST', async () => {
    await notificationsService.markAllRead()

    expect(mockPost).toHaveBeenCalledWith('/notifications/read-all')
  })
})
