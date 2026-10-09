// F4-07 / FF-12: la agenda pide solo los bloqueos activos del rango visible.
// El path queda literal (regla 23) y el rango viaja como params de axios.
const mockGet = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mockGet(...args) }
}))

import { appointmentBlocksService } from './AppointmentBlocksService'

describe('AppointmentBlocksService.list', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue({ data: [] })
  })

  it('manda el rango y include_inactive como params', async () => {
    await appointmentBlocksService.list({
      from_date: '2026-09-01',
      to_date: '2026-09-30',
      include_inactive: false
    })

    expect(mockGet).toHaveBeenCalledWith('/appointment-blocks/', {
      params: { from_date: '2026-09-01', to_date: '2026-09-30', include_inactive: false }
    })
  })
})
