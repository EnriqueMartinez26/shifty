import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { LedgerClient } from '@application/services/LedgerService'

import { ValidationError } from '@shared/errors/ValidationError'

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
  useAddLedgerMovement: () => ({ mutateAsync: mockAddMovement, isPending: false })
}))

const mockAddMovement = jest.fn()

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

// 2026-10-02, QA en navegador: despues de guardar, el tipo volvia solo a
// "Cargo" sin aviso y un sobrepago de 99.999 quedo cargado como Cargo
// (S\37-ledger-overpay.png). Un 422 (Ajuste negativo) decia "No se pudo
// registrar el movimiento" arriba de todo, fuera de la vista y sin motivo.
describe('LedgerPage: cargar un movimiento', () => {
  const tipo = () => screen.getByLabelText('Tipo de movimiento') as HTMLSelectElement
  const monto = () => screen.getByLabelText('Monto') as HTMLInputElement
  const guardar = () => fireEvent.click(screen.getByRole('button', { name: 'Guardar movimiento' }))

  beforeEach(() => {
    mockAddMovement.mockReset()
    mockAddMovement.mockResolvedValue({})
  })

  it('el tipo arranca sin elegir y sin tipo no se guarda ni se pregunta', () => {
    render(<LedgerPage />)

    expect(tipo().value).toBe('')
    fireEvent.change(monto(), { target: { value: '500' } })
    guardar()

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(mockAddMovement).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Elegí el tipo de movimiento.')
  })

  it('confirma tipo, monto y cliente antes de guardar; "Volver" no guarda', async () => {
    render(<LedgerPage />)
    fireEvent.change(tipo(), { target: { value: 'payment' } })
    fireEvent.change(monto(), { target: { value: '99999' } })
    guardar()

    const dialogo = await screen.findByRole('alertdialog')
    expect(dialogo).toHaveTextContent('Pago')
    expect(dialogo).toHaveTextContent('99.999')
    expect(dialogo).toHaveTextContent('Ana Gomez')
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(mockAddMovement).not.toHaveBeenCalled()
    expect(tipo().value).toBe('payment')
  })

  it('al guardar manda el tipo elegido y despues el tipo vuelve a "sin elegir", no a Cargo', async () => {
    render(<LedgerPage />)
    fireEvent.change(tipo(), { target: { value: 'payment' } })
    fireEvent.change(monto(), { target: { value: '500' } })
    guardar()
    fireEvent.click(await screen.findByRole('button', { name: 'Registrar' }))

    await waitFor(() =>
      expect(mockAddMovement).toHaveBeenCalledWith({
        clientId: 'cli-a',
        payload: {
          movement_type: 'payment',
          amount: 500,
          appointment_id: undefined,
          notes: undefined
        }
      })
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Movimiento registrado')
    expect(tipo().value).toBe('')
    expect(monto().value).toBe('')
  })

  it.each([['-100'], ['0'], ['abc'], ['10000001'], ['10.555']])(
    'un monto invalido (%s) no llega al servidor y se dice junto al formulario',
    (valor) => {
      render(<LedgerPage />)
      fireEvent.change(tipo(), { target: { value: 'adjustment' } })
      fireEvent.change(monto(), { target: { value: valor } })
      guardar()

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
      expect(mockAddMovement).not.toHaveBeenCalled()
      expect(screen.getByRole('alert')).toHaveTextContent(/monto/i)
    }
  )

  it.each([
    ['10000000', 10_000_000],
    ['1234,56', 1234.56],
    ['0.5', 0.5]
  ])('un monto valido (%s) se confirma y viaja como numero', async (valor, esperado) => {
    render(<LedgerPage />)
    fireEvent.change(tipo(), { target: { value: 'charge' } })
    fireEvent.change(monto(), { target: { value: valor } })
    guardar()
    fireEvent.click(await screen.findByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockAddMovement).toHaveBeenCalledTimes(1))
    expect(mockAddMovement.mock.calls[0]?.[0]).toMatchObject({
      payload: { movement_type: 'charge', amount: esperado }
    })
  })

  it('un 422 del servidor muestra el motivo mapeado junto al formulario, nunca el texto crudo', async () => {
    mockAddMovement.mockRejectedValue(
      new ValidationError('amount: Input should be greater than or equal to 0', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422,
        detail: ['amount: Input should be greater than or equal to 0']
      })
    )
    render(<LedgerPage />)
    fireEvent.change(tipo(), { target: { value: 'adjustment' } })
    fireEvent.change(monto(), { target: { value: '100' } })
    guardar()
    fireEvent.click(await screen.findByRole('button', { name: 'Registrar' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(/monto/i)
    expect(alerta).not.toHaveTextContent('Input should')
    // Junto al boton de guardar, dentro del formulario: no arriba de la pagina.
    expect(alerta.closest('form')).toBe(
      screen.getByRole('button', { name: 'Guardar movimiento' }).closest('form')
    )
    // El tipo elegido no se pierde: el dueno corrige y reintenta.
    expect(tipo().value).toBe('adjustment')
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
