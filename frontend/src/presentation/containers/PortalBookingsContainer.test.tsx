import { act, fireEvent, render, screen } from '@testing-library/react'

import { NetworkError } from '@shared/errors'

import { PortalBookingsContainer } from './PortalBookingsContainer'

const mockRecent = jest.fn()
const mockBulkCancel = jest.fn()
let mockPending = false

jest.mock('../hooks/usePortalBookings', () => ({
  useRecentPortalBookings: (...args: unknown[]) => mockRecent(...args),
  useBulkCancelPortalBookings: () => ({ mutateAsync: mockBulkCancel, isPending: mockPending })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

// useAuth() ya expone el rol canonico (AuthContext aplica canonicalRole).
const mockUser = { role: 'store_admin', is_global_admin: false }
jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser })
}))

const reserva = (id: string, nombre: string) => ({
  public_id: id,
  client_name: nombre,
  client_phone: '5491155550101',
  service_name: 'Corte',
  staff_name: 'Ana',
  starts_at: '2026-10-25T13:00:00Z',
  created_at: '2026-10-22T09:00:00Z',
  status: 'pending'
})

const LUCIA = reserva('apt-1', 'Lucia')
const JUAN = reserva('apt-2', 'Juan')
const MARTA = reserva('apt-3', 'Marta')

const conLista = (data: unknown[]) =>
  mockRecent.mockReturnValue({ data, isLoading: false, error: null })

const tildar = (nombre: string) =>
  fireEvent.click(screen.getByRole('checkbox', { name: new RegExp(`Seleccionar a ${nombre}`) }))

const marcado = (name: string | RegExp): boolean =>
  (screen.getByRole('checkbox', { name }) as HTMLInputElement).checked

describe('PortalBookingsContainer', () => {
  beforeEach(() => {
    mockRecent.mockReset()
    mockBulkCancel.mockReset()
    mockPending = false
    mockUser.role = 'store_admin'
    mockUser.is_global_admin = false
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
    conLista([LUCIA, JUAN, MARTA])
  })

  it('arranca con las ultimas 72 horas y pide la lista para el administrador', () => {
    render(<PortalBookingsContainer />)

    expect(
      screen.getByRole('heading', { name: 'Reservas recientes del portal' })
    ).toBeInTheDocument()
    expect(mockRecent).toHaveBeenLastCalledWith(72, true)
    expect(screen.getByText('Lucia')).toBeInTheDocument()
  })

  it.each(['professional', 'receptionist'])(
    'el rol %s no ve la herramienta ni pide la lista',
    (role) => {
      mockUser.role = role

      render(<PortalBookingsContainer />)

      expect(mockRecent).toHaveBeenLastCalledWith(72, false)
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Cancelar seleccionadas/ })).toBeNull()
      expect(screen.getByText(/Solo el dueño o un administrador/)).toBeInTheDocument()
    }
  )

  it('el superadmin la ve aunque su rol de tienda sea otro', () => {
    mockUser.role = 'receptionist'
    mockUser.is_global_admin = true

    render(<PortalBookingsContainer />)

    expect(mockRecent).toHaveBeenLastCalledWith(72, true)
  })

  it('cambiar la ventana pide otra lista y limpia la seleccion', () => {
    render(<PortalBookingsContainer />)
    tildar('Lucia')
    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Últimos 7 días' }))

    expect(mockRecent).toHaveBeenLastCalledWith(168, true)
    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (0)' })).toBeDisabled()
  })

  it('"Seleccionar todas" elige todas y un segundo toque las suelta', () => {
    render(<PortalBookingsContainer />)

    fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todas' }))
    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (3)' })).not.toBeDisabled()
    expect(marcado(/Seleccionar a Juan/)).toBe(true)

    fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todas' }))
    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (0)' })).toBeDisabled()
  })

  it('cancelar pasa por un paso de confirmacion en la pantalla y "Volver" no cancela nada', () => {
    const confirmSpy = jest.spyOn(window, 'confirm')
    render(<PortalBookingsContainer />)
    tildar('Lucia')
    tildar('Juan')

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (2)' }))

    expect(screen.getByRole('region', { name: 'Confirmar cancelación' })).toHaveTextContent(
      'Vas a cancelar 2 reservas.'
    )
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    expect(screen.queryByRole('region', { name: 'Confirmar cancelación' })).toBeNull()
    expect(mockBulkCancel).not.toHaveBeenCalled()
    expect(confirmSpy).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('confirma con los ids y el motivo, muestra el resultado con cada salteada y limpia la seleccion', async () => {
    mockBulkCancel.mockResolvedValue({
      cancelled: ['apt-1'],
      skipped: [
        { id: 'apt-2', code: 'APPOINTMENT_ALREADY_CANCELLED' },
        { id: 'apt-3', code: 'APPOINTMENT_ALREADY_STARTED' }
      ]
    })
    render(<PortalBookingsContainer />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todas' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (3)' }))
    fireEvent.change(screen.getByLabelText('Motivo (opcional)'), {
      target: { value: 'Reservas falsas' }
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar 3 reservas' }))
    })

    expect(mockBulkCancel).toHaveBeenCalledWith({
      ids: ['apt-1', 'apt-2', 'apt-3'],
      reason: 'Reservas falsas'
    })
    const resultado = screen.getByRole('status')
    expect(resultado).toHaveTextContent('Cancelamos 1 reserva.')
    expect(resultado).toHaveTextContent('Juan: Ya estaba cancelada.')
    expect(resultado).toHaveTextContent('Marta: El turno ya empezó.')
    expect(screen.queryByRole('region', { name: 'Confirmar cancelación' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (0)' })).toBeDisabled()
  })

  it('la lista refrescada sin las canceladas no deja seleccion fantasma', async () => {
    mockBulkCancel.mockResolvedValue({ cancelled: ['apt-1'], skipped: [] })
    const { rerender } = render(<PortalBookingsContainer />)
    tildar('Lucia')
    tildar('Juan')
    // La lista se refresco (otra pestana cancelo a Juan) antes de confirmar.
    conLista([LUCIA, MARTA])
    rerender(<PortalBookingsContainer />)

    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar 1 reserva' }))
    })

    expect(mockBulkCancel).toHaveBeenCalledWith({ ids: ['apt-1'], reason: '' })
  })

  it('si la cancelacion falla lo dice y conserva la seleccion', async () => {
    mockBulkCancel.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
    render(<PortalBookingsContainer />)
    tildar('Lucia')
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' }))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar 1 reserva' }))
    })

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo conectar con el servidor.')
    expect(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' })).not.toBeDisabled()
  })

  it('con la tienda suspendida no deja cancelar y muestra el motivo', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    render(<PortalBookingsContainer />)
    tildar('Lucia')

    const boton = screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' })
    expect(boton).toBeDisabled()
    expect(boton).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('un nuevo intento borra el resultado anterior', async () => {
    mockBulkCancel.mockResolvedValue({ cancelled: ['apt-1'], skipped: [] })
    render(<PortalBookingsContainer />)
    tildar('Lucia')
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar 1 reserva' }))
    })
    expect(screen.getByRole('status')).toHaveTextContent('Cancelamos 1 reserva.')

    tildar('Juan')
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (1)' }))

    expect(screen.queryByText('Cancelamos 1 reserva.')).toBeNull()
  })
})
