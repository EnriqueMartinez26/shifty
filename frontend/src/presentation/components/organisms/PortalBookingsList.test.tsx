import type { ComponentProps } from 'react'

import { fireEvent, render, screen, within } from '@testing-library/react'

import type { RecentPortalBooking } from '@application/services/PortalBookingsService'

import { PortalBookingsList } from './PortalBookingsList'

const reserva = (overrides: Partial<RecentPortalBooking> = {}): RecentPortalBooking => ({
  public_id: 'apt-1',
  client_name: 'Lucia Perez',
  client_phone: '5491155550101',
  service_name: 'Corte',
  staff_name: 'Ana',
  // 13:00 UTC = 10:00 en Argentina
  starts_at: '2026-10-25T13:00:00Z',
  created_at: '2026-10-22T09:00:00Z',
  status: 'pending',
  ...overrides
})

const marcado = (name: string | RegExp): boolean =>
  (screen.getByRole('checkbox', { name }) as HTMLInputElement).checked

const renderList = (props: Partial<ComponentProps<typeof PortalBookingsList>> = {}) => {
  const onToggle = jest.fn()
  const onToggleAll = jest.fn()
  render(
    <PortalBookingsList
      bookings={[reserva()]}
      isLoading={false}
      error={null}
      selectedIds={new Set()}
      onToggle={onToggle}
      onToggleAll={onToggleAll}
      {...props}
    />
  )
  return { onToggle, onToggleAll }
}

describe('PortalBookingsList', () => {
  beforeEach(() => {
    jest.spyOn(Date, 'now').mockReturnValue(new Date('2026-10-22T12:00:00Z').getTime())
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it('muestra cada reserva con cliente, telefono, servicio, profesional, inicio en hora argentina y antiguedad', () => {
    renderList()

    const fila = screen.getByRole('listitem')
    expect(within(fila).getByText('Lucia Perez')).toBeInTheDocument()
    expect(within(fila).getByText('5491155550101')).toBeInTheDocument()
    expect(within(fila).getByText('Corte')).toBeInTheDocument()
    expect(within(fila).getByText('Ana')).toBeInTheDocument()
    expect(within(fila).getByText('25/10/2026 · 10:00 hs')).toBeInTheDocument()
    expect(within(fila).getByText('hace 3 h')).toBeInTheDocument()
    expect(within(fila).getByText('Pendiente')).toBeInTheDocument()
  })

  it('un cliente sin telefono lo dice', () => {
    renderList({ bookings: [reserva({ client_phone: null })] })

    expect(within(screen.getByRole('listitem')).getByText('Sin teléfono')).toBeInTheDocument()
  })

  it('tildar una reserva y "Seleccionar todas" avisan al contenedor', () => {
    const { onToggle, onToggleAll } = renderList()

    fireEvent.click(screen.getByRole('checkbox', { name: /Seleccionar a Lucia Perez/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todas' }))

    expect(onToggle).toHaveBeenCalledWith('apt-1')
    expect(onToggleAll).toHaveBeenCalledTimes(1)
  })

  it('"Seleccionar todas" queda tildado solo si todas estan elegidas', () => {
    const dos = [reserva(), reserva({ public_id: 'apt-2', client_name: 'Juan' })]
    const { rerender } = render(
      <PortalBookingsList
        bookings={dos}
        isLoading={false}
        error={null}
        selectedIds={new Set(['apt-1'])}
        onToggle={jest.fn()}
        onToggleAll={jest.fn()}
      />
    )
    expect(marcado('Seleccionar todas')).toBe(false)
    expect(marcado(/Seleccionar a Lucia Perez/)).toBe(true)

    rerender(
      <PortalBookingsList
        bookings={dos}
        isLoading={false}
        error={null}
        selectedIds={new Set(['apt-1', 'apt-2'])}
        onToggle={jest.fn()}
        onToggleAll={jest.fn()}
      />
    )
    expect(marcado('Seleccionar todas')).toBe(true)
  })

  it('sin reservas muestra el estado vacio y ningun casillero', () => {
    renderList({ bookings: [] })

    expect(
      screen.getByText('No hubo reservas desde el portal en este período.')
    ).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('mientras carga lo dice y no muestra el vacio', () => {
    renderList({ bookings: [], isLoading: true })

    expect(screen.getByRole('status')).toHaveTextContent('Cargando reservas')
    expect(screen.queryByText(/No hubo reservas/)).not.toBeInTheDocument()
  })

  it('si la consulta falla avisa con un texto neutro en vez de decir que no hay reservas', () => {
    renderList({ bookings: [], error: new Error('boom') })

    expect(screen.getByRole('alert')).toHaveTextContent(
      'No se pudieron cargar las reservas del portal.'
    )
    expect(screen.queryByText(/No hubo reservas/)).not.toBeInTheDocument()
  })

  it('los casilleros tienen un area tactil de 44 px', () => {
    renderList()

    const casillero = screen.getByRole('checkbox', { name: /Seleccionar a Lucia Perez/ })
    expect(casillero.closest('label')).toHaveClass('min-h-11', 'min-w-11')
  })
})
