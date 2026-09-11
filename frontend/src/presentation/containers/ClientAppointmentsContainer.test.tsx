import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { PublicStore } from '@application/services/PublicBookingService'

import { ClientAppointmentsContainer } from './ClientAppointmentsContainer'

const mockAppointments = jest.fn()
const mockCancel = jest.fn()
const mockReschedule = jest.fn()
const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()

jest.mock('../hooks/usePublic', () => ({
  usePublicClientAppointments: (...args: unknown[]) => mockAppointments(...args),
  useCancelClientAppointment: () => ({ mutateAsync: mockCancel, isPending: false }),
  useRescheduleClientAppointment: () => ({ mutateAsync: mockReschedule, isPending: false }),
  useRequestPublicOtp: () => ({ mutateAsync: mockRequestOtp, isPending: false }),
  useVerifyPublicOtp: () => ({ mutateAsync: mockVerifyOtp, isPending: false })
}))

const store = {
  public_id: 'store-1',
  name: 'Peluqueria Sol',
  slug: 'sol'
} as unknown as PublicStore

const turno = {
  public_id: 'appt-1',
  service_name: 'Corte',
  staff_name: 'Ana',
  // 13:00 UTC = 10:00 en Argentina
  starts_at: '2026-09-15T13:00:00+00:00',
  ends_at: '2026-09-15T13:30:00+00:00',
  status: 'confirmed',
  notes: null,
  custom_fields: {},
  can_cancel: true,
  can_reschedule: true
}

const entrar = async () => {
  fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: '1155550101' } })
  fireEvent.change(screen.getByLabelText('Email para recibir el código'), {
    target: { value: 'yo@example.com' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))
  await screen.findByLabelText('Código')
  fireEvent.change(screen.getByLabelText('Código'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ver mis turnos' }))
  await screen.findByRole('heading', { name: 'Mis turnos' })
}

describe('ClientAppointmentsContainer', () => {
  beforeEach(() => {
    mockAppointments.mockReset()
    mockCancel.mockReset()
    mockReschedule.mockReset()
    mockRequestOtp.mockReset().mockResolvedValue({ expires_at: '', debug_code: '' })
    mockVerifyOtp
      .mockReset()
      .mockResolvedValue({ ok: true, phone: '1155550101', verified_at: new Date().toISOString() })
    mockAppointments.mockReturnValue({ data: undefined, isLoading: false, isError: false })
    try {
      window.sessionStorage.clear()
    } catch {
      // sin storage: el gate igual funciona
    }
  })

  it('pide el codigo por email antes de mostrar nada', () => {
    render(<ClientAppointmentsContainer store={store} />)

    expect(screen.getByLabelText('Teléfono')).toBeInTheDocument()
    expect(screen.queryByText('Corte')).not.toBeInTheDocument()
    expect(mockAppointments).toHaveBeenCalledWith('store-1', '', false)
  })

  it('con el codigo verificado lista los turnos en hora argentina', async () => {
    mockAppointments.mockReturnValue({
      data: { client_name: 'Yo', client_phone: '1155550101', appointments: [turno] },
      isLoading: false,
      isError: false
    })

    render(<ClientAppointmentsContainer store={store} />)
    await entrar()

    expect(screen.getByText('Corte')).toBeInTheDocument()
    expect(screen.getByText(/15\/09\/2026 a las 10:00 hs/)).toBeInTheDocument()
    expect(screen.getByText('Confirmado')).toBeInTheDocument()
  })

  it('cancela y avisa que la tienda se entero', async () => {
    mockAppointments.mockReturnValue({
      data: { client_name: 'Yo', client_phone: '1155550101', appointments: [turno] },
      isLoading: false,
      isError: false
    })
    mockCancel.mockResolvedValue(undefined)

    render(<ClientAppointmentsContainer store={store} />)
    await entrar()
    fireEvent.click(screen.getByRole('button', { name: /Cancelar/ }))

    await waitFor(() =>
      expect(mockCancel).toHaveBeenCalledWith({ publicId: 'appt-1', phone: '1155550101' })
    )
    expect(await screen.findByText(/le avisamos a la tienda/)).toBeInTheDocument()
  })

  it('reprograma mandando el instante UTC del dia y hora argentinos', async () => {
    mockAppointments.mockReturnValue({
      data: { client_name: 'Yo', client_phone: '1155550101', appointments: [turno] },
      isLoading: false,
      isError: false
    })
    mockReschedule.mockResolvedValue(undefined)

    render(<ClientAppointmentsContainer store={store} />)
    await entrar()
    fireEvent.click(screen.getByRole('button', { name: /Cambiar/ }))

    // Se precarga con el dia LOCAL del turno, no con el dia UTC.
    expect((screen.getByLabelText('Nueva fecha') as HTMLInputElement).value).toBe('2026-09-15')
    expect((screen.getByLabelText('Hora') as HTMLInputElement).value).toBe('10:00')
    fireEvent.change(screen.getByLabelText('Hora'), { target: { value: '16:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Mover' }))

    await waitFor(() => expect(mockReschedule).toHaveBeenCalledTimes(1))
    expect(mockReschedule.mock.calls[0]?.[0]).toMatchObject({
      publicId: 'appt-1',
      phone: '1155550101',
      newStartsAt: '2026-09-15T19:00:00.000Z'
    })
  })

  it('sin turnos lo dice sin romperse', async () => {
    mockAppointments.mockReturnValue({
      data: { client_name: 'Yo', client_phone: '1155550101', appointments: [] },
      isLoading: false,
      isError: false
    })

    render(<ClientAppointmentsContainer store={store} />)
    await entrar()

    expect(screen.getByText('Todavía no tenés turnos acá.')).toBeInTheDocument()
  })
})
