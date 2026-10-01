// F9-08 (2026-09-30): cobertura del resumen del panel. Path literal (regla 23).
const mockGet = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mockGet(...args) }
}))

import { dashboardService } from './DashboardService'

describe('DashboardService', () => {
  it('getSummary pide el resumen por GET y devuelve el cuerpo', async () => {
    const summary = { stats: { appointments_today: 3 }, upcoming_appointments: [] }
    mockGet.mockResolvedValue({ data: summary })

    await expect(dashboardService.getSummary()).resolves.toBe(summary)
    expect(mockGet).toHaveBeenCalledWith('/dashboard/summary')
  })
})
