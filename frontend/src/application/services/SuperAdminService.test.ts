const mockGet = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mockGet(...args) }
}))

import { superAdminService } from './SuperAdminService'

// 2026-09-30 (FF-24): "Todas" mostraba solo activas, la lista cortaba en 50 y
// cada tecla disparaba hasta 3 requests. El filtro viaja como `all` y el total
// sale del header X-Total-Count que el backend expone.
describe('SuperAdminService.listStores', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('manda is_active=all con la pagina pedida', async () => {
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } })

    await superAdminService.listStores({ is_active: 'all', limit: 50, offset: 100 })

    expect(mockGet).toHaveBeenCalledWith('/superadmin/stores', {
      params: {
        search: undefined,
        is_active: 'all',
        has_subscription: undefined,
        limit: 50,
        offset: 100
      }
    })
  })

  it('lee el total del header X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '120' } })

    await expect(superAdminService.listStores()).resolves.toEqual({ stores: [], total: 120 })
  })

  it('sin header, o con uno que no es numero, el total es null', async () => {
    mockGet.mockResolvedValueOnce({ data: [], headers: {} })
    mockGet.mockResolvedValueOnce({ data: [], headers: { 'x-total-count': 'mucho' } })

    await expect(superAdminService.listStores()).resolves.toEqual({ stores: [], total: null })
    await expect(superAdminService.listStores()).resolves.toEqual({ stores: [], total: null })
  })
})
