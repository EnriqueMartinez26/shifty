import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import type { PublicStore } from '@application/services/PublicBookingService'

import { ConflictError } from '@shared/errors'

import { ClientAppointmentsContainer } from './ClientAppointmentsContainer'

const mockAppointments = jest.fn()
const mockRefetch = jest.fn()
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
  fireEvent.change(screen.getByLabelText('Tu email'), {
    target: { value: 'yo@example.com' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))
  await screen.findByLabelText('Código')
  fireEvent.change(screen.getByLabelText('Código'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ver mis turnos' }))
  // El gate tambien titula "Mis turnos": se espera "Salir", que solo aparece
  // con el telefono verificado (2026-09-30: con la maquina cargada el test
  // seguia antes de verificar y no encontraba los turnos).
  await screen.findByRole('button', { name: 'Salir' })
}

describe('ClientAppointmentsContainer', () => {
  beforeEach(() => {
    mockAppointments.mockReset()
    mockRefetch.mockReset()
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

  describe('cancelar pide confirmacion (FF-07)', () => {
    // FF-07 (2026-09-29): un toque en "Cancelar" cancelaba el turno sin
    // preguntar; un dedo que rozaba el boton perdia el turno.
    const pregunta =
      '¿Cancelar tu turno de Corte del 15/09/2026 a las 10:00 hs? No se puede deshacer.'

    const pedirCancelar = async () => {
      mockAppointments.mockReturnValue({
        data: { client_name: 'Yo', client_phone: '1155550101', appointments: [turno] },
        isLoading: false,
        isError: false,
        refetch: mockRefetch
      })
      mockCancel.mockResolvedValue(undefined)
      render(<ClientAppointmentsContainer store={store} />)
      await entrar()
      fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
      return screen.findByRole('alertdialog', { name: pregunta })
    }

    it('cancela recien al confirmar y avisa que la tienda se entero', async () => {
      const dialogo = await pedirCancelar()
      expect(mockCancel).not.toHaveBeenCalled()

      fireEvent.click(within(dialogo).getByRole('button', { name: 'Sí, cancelar turno' }))

      await waitFor(() =>
        expect(mockCancel).toHaveBeenCalledWith({ publicId: 'appt-1', phone: '1155550101' })
      )
      expect(await screen.findByText(/le avisamos a la tienda/)).toBeInTheDocument()
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    })

    it('descartar el dialogo no cancela el turno', async () => {
      const dialogo = await pedirCancelar()
      // Los botones dicen lo que hacen: ninguno se llama "Cancelar", que en
      // este dialogo se leeria como cancelar el turno.
      expect(within(dialogo).queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()

      fireEvent.click(within(dialogo).getByRole('button', { name: 'Conservar turno' }))

      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
      expect(mockCancel).not.toHaveBeenCalled()
      expect(screen.queryByText(/le avisamos a la tienda/)).not.toBeInTheDocument()
    })

    it('Escape cierra el dialogo sin cancelar', async () => {
      const dialogo = await pedirCancelar()

      fireEvent.keyDown(dialogo, { key: 'Escape' })

      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
      expect(mockCancel).not.toHaveBeenCalled()
    })

    it('un 409 de estado recarga la lista ademas de explicarlo', async () => {
      // FF-07 (2026-09-30): si la tienda ya habia cancelado el turno, el 409
      // mostraba el aviso pero la lista seguia ofreciendo "Cancelar" sobre un
      // turno que ya no estaba vivo.
      const dialogo = await pedirCancelar()
      mockCancel.mockRejectedValue(
        new ConflictError('El turno ya esta cancelado.', {
          errorCode: 'APPOINTMENT_ALREADY_CANCELLED',
          statusCode: 409
        })
      )

      fireEvent.click(within(dialogo).getByRole('button', { name: 'Sí, cancelar turno' }))

      expect(await screen.findByText(/ya estaba cancelado/)).toBeInTheDocument()
      expect(mockRefetch).toHaveBeenCalledTimes(1)
    })

    it('un error que no es de estado no recarga la lista', async () => {
      const dialogo = await pedirCancelar()
      mockCancel.mockRejectedValue(
        new ConflictError('Otro conflicto.', { errorCode: 'SLOT_TAKEN', statusCode: 409 })
      )

      fireEvent.click(within(dialogo).getByRole('button', { name: 'Sí, cancelar turno' }))

      await waitFor(() => expect(mockCancel).toHaveBeenCalledTimes(1))
      await screen.findByRole('status')
      expect(mockRefetch).not.toHaveBeenCalled()
    })
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
