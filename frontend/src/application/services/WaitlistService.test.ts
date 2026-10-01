// F9-08 (2026-09-30): cobertura de la lista de espera del panel. Path literal
// (regla 23; el listado lleva la barra final, redirect_slashes=False).
const mockGet = jest.fn()
const mockPost = jest.fn()
const mockDelete = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args)
  }
}))

import { waitlistService } from './WaitlistService'

describe('WaitlistService', () => {
  beforeEach(() => {
    for (const mock of [mockGet, mockPost, mockDelete]) {
      mock.mockReset()
      mock.mockResolvedValue({ data: [] })
    }
  })

  it('list pide las entradas por GET', async () => {
    await waitlistService.list()

    expect(mockGet).toHaveBeenCalledWith('/waitlist/')
  })

  it('remove borra la entrada por DELETE', async () => {
    await waitlistService.remove('wl-1')

    expect(mockDelete).toHaveBeenCalledWith('/waitlist/wl-1')
  })

  it('book reserva la entrada por POST con inicio y profesional', async () => {
    const payload = { starts_at: '2026-10-01T13:00:00Z', staff_id: 'st-1' }

    await waitlistService.book('wl-1', payload)

    expect(mockPost).toHaveBeenCalledWith('/waitlist/wl-1/book', payload)
  })
})
