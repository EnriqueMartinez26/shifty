// F9-11: los query strings se arman con `params` de axios, no interpolando.
// El path queda literal y exacto (sin `?`) para que
// test_frontend_routes_contract lo siga viendo (regla 23).
const mockGet = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mockGet(...args) }
}))

import { reportsService } from './ReportsService'
import { superAdminService } from './SuperAdminService'

describe('query strings por params (F9-11)', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue({ data: [] })
  })

  it('reportes: el rango de fechas viaja como params', async () => {
    await reportsService.getSummary('2026-09-01', '2026-09-30')
    await reportsService.getProfessionalReports('2026-09-01', '2026-09-30')
    await reportsService.getTrend(6)

    const rango = { params: { from_date: '2026-09-01', to_date: '2026-09-30' } }
    expect(mockGet).toHaveBeenNthCalledWith(1, '/reports/summary', rango)
    expect(mockGet).toHaveBeenNthCalledWith(2, '/reports/professionals', rango)
    expect(mockGet).toHaveBeenNthCalledWith(3, '/reports/trend', { params: { months: 6 } })
  })

  it('superadmin: filtros, limite e inactivos viajan como params', async () => {
    await superAdminService.listStores({ search: 'a&b', is_active: false, has_subscription: null })
    await superAdminService.getStoreAuditLogs('store-1', 20)
    await superAdminService.listPlans(true)
    await superAdminService.listCoupons()

    expect(mockGet).toHaveBeenNthCalledWith(1, '/superadmin/stores', {
      params: { search: 'a&b', is_active: false, has_subscription: null }
    })
    expect(mockGet).toHaveBeenNthCalledWith(2, '/superadmin/stores/store-1/audit-logs', {
      params: { limit: 20 }
    })
    expect(mockGet).toHaveBeenNthCalledWith(3, '/superadmin/plans', {
      params: { include_inactive: true }
    })
    expect(mockGet).toHaveBeenNthCalledWith(4, '/superadmin/coupons', {
      params: { include_inactive: false }
    })
  })

  it('superadmin: una busqueda vacia no viaja', async () => {
    await superAdminService.listStores({ search: '' })

    expect(mockGet).toHaveBeenCalledWith('/superadmin/stores', {
      params: { search: undefined, is_active: undefined, has_subscription: undefined }
    })
  })
})
