import { fireEvent, render, screen } from '@testing-library/react'

import { WaitlistContainer } from './WaitlistContainer'

const mockWaitlist = jest.fn()
const mockRemove = jest.fn()
const mockBook = jest.fn()

jest.mock('../hooks/useWaitlist', () => ({
  useWaitlist: () => mockWaitlist(),
  useRemoveWaitlistEntry: () => ({ mutateAsync: mockRemove, isPending: false }),
  useBookFromWaitlist: () => ({ mutateAsync: mockBook, isPending: false })
}))

jest.mock('../hooks/useStores', () => ({
  useStoreSettings: () => ({ data: { name: 'Peluqueria Sol', slug: 'sol' } })
}))

const mockUser = { role: 'admin', is_global_admin: false }
jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser })
}))

const entrada = {
  public_id: 'wl-1',
  status: 'offered',
  service_id: 'svc-1',
  service_name: 'Corte',
  staff_id: 'st-1',
  staff_name: 'Ana',
  window_starts_at: '2026-09-20T03:00:00+00:00',
  window_ends_at: '2026-09-21T02:59:00+00:00',
  client_name: 'Lucia',
  client_phone: '5491155550101',
  client_email: 'lucia@example.com',
  notes: null,
  notified_at: '2026-09-15T12:00:00+00:00',
  offer_expires_at: '2026-09-15T12:10:00+00:00',
  // 13:00 UTC = 10:00 en Argentina
  offered_starts_at: '2026-09-20T13:00:00+00:00',
  offered_staff_id: 'st-1',
  created_at: '2026-09-10T10:00:00+00:00'
}

describe('WaitlistContainer', () => {
  beforeEach(() => {
    mockWaitlist.mockReset()
    mockRemove.mockReset()
    mockBook.mockReset()
    mockUser.role = 'admin'
  })

  it('muestra la entrada con el cupo ofrecido y el link de WhatsApp con deep-link', () => {
    mockWaitlist.mockReturnValue({ data: [entrada], isLoading: false })

    render(<WaitlistContainer />)

    expect(screen.getByText('Lucia')).toBeInTheDocument()
    expect(screen.getByText('Cupo ofrecido')).toBeInTheDocument()
    expect(screen.getByText(/Se le ofrecio el 20\/09\/2026 a las 10:00 hs/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'WhatsApp' })
    const href = decodeURIComponent(link.getAttribute('href') ?? '')
    expect(href.startsWith('https://wa.me/5491155550101?text=')).toBe(true)
    expect(href).toContain('/b/sol?service=svc-1&staff=st-1')
  })

  it('el administrador reserva a mano en hora argentina', () => {
    mockWaitlist.mockReturnValue({ data: [entrada], isLoading: false })
    mockBook.mockResolvedValue({ public_id: 'appt-1' })

    render(<WaitlistContainer />)
    fireEvent.click(screen.getByRole('button', { name: /Reservar/ }))
    // Se precarga con el cupo ofrecido (10:00 del 20/09 en Argentina).
    expect((screen.getByLabelText('Fecha') as HTMLInputElement).value).toBe('2026-09-20')
    expect((screen.getByLabelText('Hora') as HTMLInputElement).value).toBe('10:00')
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(mockBook).toHaveBeenCalledWith({
      entryId: 'wl-1',
      payload: { starts_at: '2026-09-20T13:00:00.000Z', staff_id: 'st-1' }
    })
  })

  it('el personal sin rol de administrador no ve reservar ni quitar', () => {
    mockUser.role = 'staff'
    mockWaitlist.mockReturnValue({ data: [{ ...entrada, client_phone: null }], isLoading: false })

    render(<WaitlistContainer />)

    expect(screen.queryByRole('button', { name: /Reservar/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Quitar/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'WhatsApp' })).not.toBeInTheDocument()
  })

  it('sin entradas explica de donde salen', () => {
    mockWaitlist.mockReturnValue({ data: [], isLoading: false })

    render(<WaitlistContainer />)

    expect(screen.getByText('Nadie en lista de espera')).toBeInTheDocument()
  })
})

describe('WaitlistContainer con la consulta en error', () => {
  it('un error no se muestra como lista vacia', () => {
    // Regresion 2026-09-11: decia "Nadie en lista de espera" y "0 en espera"
    // cuando la consulta fallaba, y el duenio perdia clientes sin enterarse.
    mockWaitlist.mockReturnValue({ data: undefined, isLoading: false, isError: true })

    render(<WaitlistContainer />)

    expect(screen.queryByText('Nadie en lista de espera')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('No pudimos cargar la lista de espera')
    expect(screen.getByText('Sin datos')).toBeInTheDocument()
  })
})
