// F9-08 (2026-09-30): cobertura del fiado. El cursor `after` y la busqueda `q`
// ya los fija QueryParams.test.ts (F9-11); aca van los metodos que faltaban.
const mockGet = jest.fn()
const mockPost = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args)
  }
}))

import { ledgerService } from './LedgerService'

describe('LedgerService', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockGet.mockResolvedValue({ data: {} })
    mockPost.mockResolvedValue({ data: {} })
  })

  it('getCustomerLedger sin cursor pide la primera pagina con after undefined', async () => {
    await ledgerService.getCustomerLedger('cli-a')

    expect(mockGet).toHaveBeenCalledWith('/ledger/customers/cli-a', {
      params: { after: undefined }
    })
  })

  it('getSummary pide el resumen por GET', async () => {
    await ledgerService.getSummary()

    expect(mockGet).toHaveBeenCalledWith('/ledger/summary')
  })

  it('addMovement manda el movimiento por POST al cliente', async () => {
    const payload = { movement_type: 'charge' as const, amount: 1500, notes: 'corte' }

    await ledgerService.addMovement('cli-a', payload)

    expect(mockPost).toHaveBeenCalledWith('/ledger/customers/cli-a/movements', payload)
  })
})
