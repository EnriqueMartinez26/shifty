const mockGet = jest.fn()
const mockPost = jest.fn()
const mockPatch = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    patch: (...args: unknown[]) => mockPatch(...args)
  }
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

  // F9-08 (2026-09-30): una busqueda vacia no viaja como search=''.
  it('omite search cuando llega vacio', async () => {
    mockGet.mockResolvedValue({ data: [], headers: {} })

    await superAdminService.listStores({ search: '' })

    expect(mockGet).toHaveBeenCalledWith('/superadmin/stores', {
      params: expect.objectContaining({ search: undefined })
    })
  })
})

// F9-08 (2026-09-30): cobertura del resto del servicio. Paths literales
// (regla 23) y verbo de cada recurso.
const admin = {
  email: 'dueno@example.com',
  password: 'clave-segura-12',
  first_name: 'Ana',
  last_name: 'Diaz'
}

describe('SuperAdminService por recurso', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockPatch.mockReset()
    mockGet.mockResolvedValue({ data: [] })
    mockPost.mockResolvedValue({ data: {} })
    mockPatch.mockResolvedValue({ data: {} })
  })

  it('getStoreAuditLogs usa limit 15 por defecto', async () => {
    await superAdminService.getStoreAuditLogs('st-1')

    expect(mockGet).toHaveBeenCalledWith('/superadmin/stores/st-1/audit-logs', {
      params: { limit: 15 }
    })
  })

  it.each([
    [
      'createStore',
      () => superAdminService.createStore({ name: 'Barberia', slug: 'barberia' }),
      '/superadmin/stores',
      { name: 'Barberia', slug: 'barberia' }
    ],
    [
      'createStoreAdmin',
      () => superAdminService.createStoreAdmin('st-1', admin),
      '/superadmin/stores/st-1/admins',
      admin
    ],
    [
      'createPlan',
      () => superAdminService.createPlan({ name: 'Base', price: 10000 }),
      '/superadmin/plans',
      { name: 'Base', price: 10000 }
    ],
    [
      'assignSubscription',
      () => superAdminService.assignSubscription('st-1', { plan_id: 'plan-1' }),
      '/superadmin/stores/st-1/subscription',
      { plan_id: 'plan-1' }
    ],
    [
      'createCoupon',
      () => superAdminService.createCoupon({ code: 'OFF10', coupon_type: 'percent', value: 10 }),
      '/superadmin/coupons',
      { code: 'OFF10', coupon_type: 'percent', value: 10 }
    ],
    [
      'redeemCoupon',
      () => superAdminService.redeemCoupon('st-1', 'OFF10'),
      '/superadmin/stores/st-1/coupons/redeem',
      { coupon_code: 'OFF10' }
    ]
  ])('%s manda el cuerpo por POST', async (_nombre, llamar, path, body) => {
    await llamar()

    expect(mockPost).toHaveBeenCalledWith(path, body)
  })

  it.each([
    [
      'updateStore',
      () => superAdminService.updateStore('st-1', { is_active: false }),
      '/superadmin/stores/st-1',
      { is_active: false }
    ],
    [
      'updateUser',
      () => superAdminService.updateUser('usr-1', { role: 'staff' }),
      '/superadmin/users/usr-1',
      { role: 'staff' }
    ],
    [
      'setGlobalAdmin',
      () => superAdminService.setGlobalAdmin('usr-1', true),
      '/superadmin/users/usr-1/global-admin',
      { is_global_admin: true }
    ],
    [
      'updatePlan',
      () => superAdminService.updatePlan('plan-1', { is_active: false }),
      '/superadmin/plans/plan-1',
      { is_active: false }
    ],
    [
      'updateCoupon',
      () => superAdminService.updateCoupon('cup-1', { max_uses: 5 }),
      '/superadmin/coupons/cup-1',
      { max_uses: 5 }
    ]
  ])('%s manda el cambio por PATCH', async (_nombre, llamar, path, body) => {
    await llamar()

    expect(mockPatch).toHaveBeenCalledWith(path, body)
  })
})
