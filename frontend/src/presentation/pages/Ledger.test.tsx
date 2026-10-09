import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { LedgerClient, LedgerMovement } from '@application/services/LedgerService'

import { ValidationError } from '@shared/errors/ValidationError'

import LedgerPage from './Ledger'

const clientes: LedgerClient[] = [
  { public_id: 'cli-a', name: 'Ana Gomez', email: 'ana@example.com', phone: '1155550001' },
  { public_id: 'cli-b', name: 'Beto Gomez', email: 'beto@example.com', phone: '1155550002' }
]

const movimiento: LedgerMovement = {
  public_id: 'mov-1',
  movement_type: 'charge',
  amount: 1000,
  balance_after: 1000,
  created_at: '2026-09-20T12:00:00Z',
  reverses_id: null,
  reversed: false
}

const mockCustomerLedger = jest.fn()
const mockLedgerClients = jest.fn()
const mockFetchNextPage = jest.fn()
let mockHasNextPage = true
let mockMovements: LedgerMovement[] = [movimiento]

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
      movements: mockMovements,
      hasNextPage: mockHasNextPage,
      fetchNextPage: mockFetchNextPage,
      isFetchingNextPage: false,
      isLoading: false,
      error: null
    }
  },
  useAddLedgerMovement: () => ({ mutateAsync: mockAddMovement, isPending: false }),
  useReverseLedgerMovement: () => ({ mutateAsync: mockReverseMovement, isPending: false })
}))

const mockAddMovement = jest.fn()
const mockReverseMovement = jest.fn()

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

  // 2026-10-02, QA en navegador: el selector y "Cliente seleccionado"
  // mostraban el email tecnico {tel}@store{id}.noreply del alta publica.
  it('no muestra el email tecnico del cliente', () => {
    const tecnico = '5491155550707@store01m3xx3hzqhynqygq38hwdawjp.noreply'
    clientes.unshift({ public_id: 'cli-t', name: tecnico, email: tecnico, phone: '5491155550707' })
    try {
      render(<LedgerPage />)

      expect(screen.queryByText(/\.noreply/)).not.toBeInTheDocument()
      expect(screen.getByRole('option', { name: '5491155550707' })).toBeInTheDocument()
      expect(screen.getByText(/Cliente seleccionado: 5491155550707/)).toBeInTheDocument()
    } finally {
      clientes.shift()
    }
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
    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))
    expect(mockFetchNextPage).toHaveBeenCalledTimes(1)
  })

  it('sin next_cursor no ofrece "Ver mas"', () => {
    mockHasNextPage = false
    render(<LedgerPage />)

    expect(screen.queryByRole('button', { name: 'Ver más' })).not.toBeInTheDocument()
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
    'un monto inválido (%s) no llega al servidor y se dice junto al formulario',
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
  ])('un monto válido (%s) se confirma y viaja como número', async (valor, esperado) => {
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

// Decision de Mateo (2026-10-03): el fiado TIENE que poder revertir un
// movimiento desde la pantalla. El backend ya lo hacia (POST .../reverse),
// pero el panel no lo ofrecia ni sabia cual ya estaba revertido.
describe('LedgerPage: revertir un movimiento', () => {
  const reversa: LedgerMovement = {
    public_id: 'mov-r',
    movement_type: 'adjustment',
    amount: -1000,
    balance_after: 0,
    notes: 'Reversa de movimiento mov-1',
    created_at: '2026-09-21T12:00:00Z',
    reverses_id: 'mov-1',
    reversed: false
  }
  const revertido: LedgerMovement = { ...movimiento, reversed: true }
  // Por el titulo de la fila: "Cargo" tambien es una opcion del formulario.
  const filaDe = (titulo: string | RegExp): HTMLElement => {
    const fila = screen.getAllByTestId('ledger-movement').find((elemento) => {
      const texto = elemento.querySelector('p')?.textContent ?? ''
      return typeof titulo === 'string' ? texto === titulo : titulo.test(texto)
    })
    if (!fila) throw new Error(`No hay una fila "${String(titulo)}"`)
    return fila
  }

  beforeEach(() => {
    mockReverseMovement.mockReset()
    mockReverseMovement.mockResolvedValue(reversa)
  })

  afterEach(() => {
    mockMovements = [movimiento]
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('ofrece "Revertir" solo en un movimiento vigente que no es una reversión', () => {
    const vigente: LedgerMovement = { ...movimiento, public_id: 'mov-2', movement_type: 'payment' }
    mockMovements = [reversa, vigente, revertido]
    render(<LedgerPage />)

    const botones = screen.getAllByRole('button', { name: 'Revertir' })
    expect(botones).toHaveLength(1)
    expect(filaDe('Pago').contains(botones[0] ?? null)).toBe(true)
    // El original queda marcado y la reversion dice que anula.
    expect(filaDe('Cargo')).toHaveTextContent('Revertido')
    expect(filaDe(/^Reversión de Cargo/)).toHaveTextContent('20/09/2026')
    // La nota automatica con el id interno no se muestra.
    expect(screen.queryByText(/Reversa de movimiento/)).not.toBeInTheDocument()
  })

  it('una reversión cuyo original no está en la página igual se marca', () => {
    mockMovements = [reversa]
    render(<LedgerPage />)

    expect(screen.getByText('Reversión de un movimiento anterior')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revertir' })).not.toBeInTheDocument()
  })

  it('con la tienda suspendida "Revertir" se ve deshabilitado con el motivo', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    render(<LedgerPage />)

    const revertir = screen.getByRole('button', { name: 'Revertir' })
    expect(revertir).toBeDisabled()
    expect(revertir).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('confirma nombrando tipo, monto y fecha; "Volver" no revierte', async () => {
    render(<LedgerPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Revertir' }))

    const dialogo = await screen.findByRole('alertdialog')
    expect(dialogo).toHaveTextContent('Cargo')
    expect(dialogo).toHaveTextContent('1.000')
    expect(dialogo).toHaveTextContent('20/09/2026')
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(mockReverseMovement).not.toHaveBeenCalled()
  })

  it('al confirmar revierte ese movimiento del cliente elegido y lo avisa', async () => {
    render(<LedgerPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Revertir' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Sí, revertir' }))

    await waitFor(() =>
      expect(mockReverseMovement).toHaveBeenCalledWith({ clientId: 'cli-a', movementId: 'mov-1' })
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Movimiento revertido')
  })

  it('un 422 (ya revertido) se dice en castellano, sin el texto del servidor', async () => {
    mockReverseMovement.mockRejectedValue(
      new ValidationError('Ese movimiento ya fue revertido.', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422
      })
    )
    render(<LedgerPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Revertir' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Sí, revertir' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(
      'Ese movimiento ya fue revertido o es una reversión. La cuenta se actualizó.'
    )
  })
})
