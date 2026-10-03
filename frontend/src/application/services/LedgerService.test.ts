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

  it('searchClients pasa el AbortSignal al GET (F4-04)', async () => {
    // F4-04 a (2026-10-01): la busqueda no se podia cancelar al tipear otra.
    const controller = new AbortController()

    await ledgerService.searchClients('ana', controller.signal)

    expect(mockGet).toHaveBeenCalledWith('/ledger/clients', {
      params: { q: 'ana' },
      signal: controller.signal
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

  // Decision de Mateo (2026-10-03): el fiado revierte movimientos desde el panel.
  it('reverseMovement pide la reversa por POST, sin cuerpo, a la ruta exacta', async () => {
    mockPost.mockResolvedValue({ data: { public_id: 'mov-r', reverses_id: 'mov-1' } })

    const reversa = await ledgerService.reverseMovement('cli-a', 'mov-1')

    expect(mockPost).toHaveBeenCalledWith('/ledger/customers/cli-a/movements/mov-1/reverse')
    expect(reversa).toEqual({ public_id: 'mov-r', reverses_id: 'mov-1' })
  })
})
