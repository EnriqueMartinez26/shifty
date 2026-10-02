import { fireEvent, render, screen } from '@testing-library/react'

import type { LedgerClient } from '@application/services/LedgerService'

import LedgerPage from './Ledger'

const clientes: LedgerClient[] = [
  { public_id: 'cli-a', name: 'Ana Gomez', email: 'ana@example.com', phone: '1155550001' },
  { public_id: 'cli-b', name: 'Beto Gomez', email: 'beto@example.com', phone: '1155550002' }
]

const movimiento = {
  public_id: 'mov-1',
  movement_type: 'charge' as const,
  amount: 1000,
  balance_after: 1000,
  created_at: '2026-09-20T12:00:00Z'
}

const mockCustomerLedger = jest.fn()
const mockLedgerClients = jest.fn()
const mockFetchNextPage = jest.fn()
let mockHasNextPage = true

// El selector sale de /ledger/clients (useLedgerClients), no de /users/: si la
// pagina volviera a useStoreClients, este test no tendria QueryClient y fallaria.
jest.mock('../hooks/useLedger', () => ({
  useLedgerSummary: () => ({ data: undefined, isLoading: false, error: null }),
  useLedgerClients: (search: string) => {
    mockLedgerClients(search)
    const data = search ? clientes.filter((c) => c.name.includes(search)) : clientes
    return { data, isLoading: false, error: null }
  },
  useCustomerLedger: (clientId: string | null) => {
    mockCustomerLedger(clientId)
    return {
      balance: 1000,
      total: 3,
      movements: [movimiento],
      hasNextPage: mockHasNextPage,
      fetchNextPage: mockFetchNextPage,
      isFetchingNextPage: false,
      isLoading: false,
      error: null
    }
  },
  useAddLedgerMovement: () => ({ mutateAsync: jest.fn(), isPending: false })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

describe('LedgerPage', () => {
  beforeEach(() => {
    mockHasNextPage = true
    mockFetchNextPage.mockClear()
  })

  it('sin eleccion toma el primer cliente del buscador del fiado y muestra su email', () => {
    render(<LedgerPage />)

    expect((screen.getAllByRole('combobox')[0] as HTMLSelectElement).value).toBe('cli-a')
    expect(mockCustomerLedger).toHaveBeenCalledWith('cli-a')
    expect(mockCustomerLedger).not.toHaveBeenCalledWith(null)
    expect(screen.getByText(/ana@example\.com/)).toBeInTheDocument()
  })

  it('la busqueda viaja al hook de /ledger/clients al enviarla, no por tecla', () => {
    render(<LedgerPage />)

    fireEvent.change(screen.getByLabelText('Buscar cliente'), { target: { value: 'Beto' } })
    expect(mockLedgerClients).toHaveBeenLastCalledWith('')
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))

    expect(mockLedgerClients).toHaveBeenLastCalledWith('Beto')
  })

  it('el cliente elegido se sostiene aunque la busqueda ya no lo traiga', () => {
    render(<LedgerPage />)
    const selector = screen.getAllByRole('combobox')[0] as HTMLSelectElement
    const monto = () => (screen.getByPlaceholderText('Monto') as HTMLInputElement).value
    fireEvent.change(selector, { target: { value: 'cli-b' } })
    fireEvent.change(screen.getByPlaceholderText('Monto'), { target: { value: '500' } })

    fireEvent.change(screen.getByLabelText('Buscar cliente'), { target: { value: 'Ana' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))

    expect(selector.value).toBe('cli-b')
    expect(mockCustomerLedger).toHaveBeenLastCalledWith('cli-b')
    expect(monto()).toBe('500')

    fireEvent.change(selector, { target: { value: 'cli-a' } })
    expect(monto()).toBe('')
  })

  it('"Ver mas" pide la pagina siguiente y dice cuantos se ven del total (FF-20)', () => {
    render(<LedgerPage />)

    expect(screen.getByText('Mostrando 1 de 3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver mas' }))
    expect(mockFetchNextPage).toHaveBeenCalledTimes(1)
  })

  it('sin next_cursor no ofrece "Ver mas"', () => {
    mockHasNextPage = false
    render(<LedgerPage />)

    expect(screen.queryByRole('button', { name: 'Ver mas' })).not.toBeInTheDocument()
  })
})

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15). POST /ledger/customers/{id}/movements no esta
// en SUSPENSION_ALLOWED_WRITES.
describe('LedgerPage: tienda suspendida', () => {
  afterEach(() => {
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('con la tienda suspendida "Guardar movimiento" queda deshabilitado; buscar sigue', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    render(<LedgerPage />)

    const guardar = screen.getByRole('button', { name: 'Guardar movimiento' })
    expect(guardar).toBeDisabled()
    expect(guardar).toHaveAttribute('title', 'Tienda suspendida')
    expect(screen.getByRole('button', { name: 'Buscar' })).not.toBeDisabled()
  })

  it('sin suspension "Guardar movimiento" sigue habilitado', () => {
    render(<LedgerPage />)

    expect(screen.getByRole('button', { name: 'Guardar movimiento' })).not.toBeDisabled()
  })
})
