import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { dayWindow, WaitlistJoinForm } from './WaitlistJoinForm'

const mockJoin = jest.fn()
const mockState = { isPending: false, isSuccess: false }

jest.mock('../../../hooks/usePublic', () => ({
  useJoinWaitlist: () => ({ mutateAsync: mockJoin, ...mockState })
}))

describe('WaitlistJoinForm', () => {
  beforeEach(() => {
    mockJoin.mockReset()
    mockState.isSuccess = false
  })

  it('la ventana es el dia entero en hora argentina', () => {
    // 00:00 del 20/09 en Buenos Aires = 03:00 UTC.
    expect(dayWindow('2026-09-20')).toEqual({
      starts: '2026-09-20T03:00:00.000Z',
      ends: '2026-09-21T02:59:00.000Z'
    })
  })

  it('anota al cliente para ese dia con el servicio y profesional elegidos', async () => {
    mockJoin.mockResolvedValue({ public_id: 'wl-1' })
    render(
      <WaitlistJoinForm
        storePublicId="store-1"
        serviceId="svc-1"
        staffId="st-1"
        date="2026-09-20"
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Avisame si se libera/ }))
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'Lucia' } })
    fireEvent.change(screen.getByLabelText('Telefono'), { target: { value: '11 5555 0101' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'lucia@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Anotarme' }))

    await waitFor(() => expect(mockJoin).toHaveBeenCalledTimes(1))
    expect(mockJoin).toHaveBeenCalledWith({
      store_public_id: 'store-1',
      service_id: 'svc-1',
      staff_id: 'st-1',
      window_starts_at: '2026-09-20T03:00:00.000Z',
      window_ends_at: '2026-09-21T02:59:00.000Z',
      client_name: 'Lucia',
      client_phone: '11 5555 0101',
      client_email: 'lucia@example.com'
    })
  })

  it('muestra el error del backend (por ejemplo, ya anotado)', async () => {
    mockJoin.mockRejectedValue(new Error('Ya estas anotado en la lista de espera'))
    render(
      <WaitlistJoinForm
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        date="2026-09-20"
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Avisame si se libera/ }))
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'Lucia' } })
    fireEvent.change(screen.getByLabelText('Telefono'), { target: { value: '1155550101' } })
    fireEvent.click(screen.getByRole('button', { name: 'Anotarme' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Ya estas anotado')
  })
})

describe('cambio de dia', () => {
  beforeEach(() => {
    mockJoin.mockReset()
    mockState.isSuccess = false
  })

  it('el cartel de exito no se arrastra a otro dia', async () => {
    // Regresion 2026-09-11: tras anotarse para el dia A, al mirar el dia B
    // seguia el cartel y decia el dia B (falso), sin boton para anotarse.
    mockJoin.mockResolvedValue({ public_id: 'wl-1' })
    const { rerender } = render(
      <WaitlistJoinForm
        key="2026-09-20"
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        date="2026-09-20"
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Avisame si se libera/ }))
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'Lucia' } })
    fireEvent.change(screen.getByLabelText('Telefono'), { target: { value: '1155550101' } })
    fireEvent.click(screen.getByRole('button', { name: 'Anotarme' }))
    await waitFor(() => expect(mockJoin).toHaveBeenCalledTimes(1))

    // El padre remonta el formulario al cambiar de dia (key={dateStr}).
    rerender(
      <WaitlistJoinForm
        key="2026-09-25"
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        date="2026-09-25"
      />
    )

    expect(screen.getByRole('button', { name: /Avisame si se libera/ })).toBeInTheDocument()
    expect(screen.queryByText(/Quedaste en lista de espera/)).not.toBeInTheDocument()
  })
})
