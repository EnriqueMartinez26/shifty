import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { PublicStore } from '@application/services/PublicBookingService'

import { ForbiddenError } from '@shared/errors/ForbiddenError'
import { InternalServerError } from '@shared/errors/InternalServerError'
import { NotFoundError } from '@shared/errors/NotFoundError'
import { RateLimitError } from '@shared/errors/RateLimitError'
import { isOtpStillValid, rememberOtpVerification } from '@shared/utils/otpSession'

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
  fireEvent.change(screen.getByLabelText('Tu email'), {
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

  describe('verificacion rechazada y errores al buscar (FF-05)', () => {
    // FF-05 (2026-09-29): con el telefono "verificado" desde el wizard
    // (sessionStorage, 30 min), "Mis turnos" entraba sin pedir codigo, el GET
    // respondia 403 OTP_VERIFICATION_REQUIRED y la pantalla decia "No
    // encontramos turnos". "Salir" y volver entraba por el mismo atajo: el
    // cliente quedaba 30 minutos en un bucle. Lo mismo con una ficha sin email
    // entregable. Y 404, 429 y 503 mostraban el mismo texto.
    const aviso = /Necesitamos verificar tu teléfono de nuevo/
    const rechazo = new ForbiddenError('Se requiere validar OTP antes de autogestionar turnos', {
      errorCode: 'OTP_VERIFICATION_REQUIRED',
      statusCode: 403
    })
    const mockRefetch = jest.fn()

    // El GET solo falla cuando la consulta esta habilitada (hay telefono).
    const fallaCon = (error: unknown) => (_storeId: unknown, _phone: unknown, enabled: unknown) =>
      enabled
        ? { data: undefined, isLoading: false, isError: true, error, refetch: mockRefetch }
        : { data: undefined, isLoading: false, isError: false, error: null, refetch: mockRefetch }

    // El wizard dejo el telefono verificado; "Mis turnos" entra sin codigo.
    const entrarPorElAtajo = () => {
      rememberOtpVerification('sol', '1155550101', new Date().toISOString())
      fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: '1155550101' } })
      fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))
    }

    beforeEach(() => {
      mockRefetch.mockReset()
    })

    it('un 403 OTP_VERIFICATION_REQUIRED olvida la verificacion y vuelve a pedir el codigo', async () => {
      mockAppointments.mockImplementation(fallaCon(rechazo))

      render(<ClientAppointmentsContainer store={store} />)
      entrarPorElAtajo()

      expect(await screen.findByText(aviso)).toBeInTheDocument()
      expect(screen.queryByText(/No encontramos turnos/)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Salir' })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Enviarme el código' })).toBeInTheDocument()
      expect(isOtpStillValid('sol', '1155550101')).toBe(false)
    })

    it('salir y volver no entra de nuevo por el atajo', async () => {
      mockAppointments.mockImplementation(fallaCon(rechazo))

      const { unmount } = render(<ClientAppointmentsContainer store={store} />)
      entrarPorElAtajo()
      expect(mockAppointments).toHaveBeenCalledWith('store-1', '1155550101', true)
      unmount()
      mockAppointments.mockClear()

      render(<ClientAppointmentsContainer store={store} />)
      fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: '1155550101' } })
      fireEvent.change(screen.getByLabelText('Tu email'), { target: { value: 'yo@example.com' } })
      fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))

      expect(await screen.findByLabelText('Código')).toBeInTheDocument()
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
      expect(mockAppointments).not.toHaveBeenCalledWith('store-1', '1155550101', true)
    })

    it('verificar de nuevo el mismo telefono vuelve a pedir los turnos', async () => {
      mockAppointments.mockImplementation(fallaCon(rechazo))

      render(<ClientAppointmentsContainer store={store} />)
      entrarPorElAtajo()
      await screen.findByText(aviso)
      await entrar()

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1))
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
    })

    it.each([
      [
        '404',
        new NotFoundError('No se encontraron turnos para ese número de teléfono', {
          errorCode: 'CLIENT_APPOINTMENTS_NOT_FOUND',
          statusCode: 404
        }),
        'No encontramos turnos para ese teléfono en Peluqueria Sol.'
      ],
      [
        '429',
        new RateLimitError('Too many requests', { errorCode: 'RATE_LIMITED', statusCode: 429 }),
        'Hiciste demasiados intentos seguidos. Esperá un momento y volvé a intentar.'
      ],
      [
        '500',
        new InternalServerError('Internal Server Error', { statusCode: 500 }),
        'No pudimos cargar tus turnos. Probá de nuevo en unos minutos.'
      ]
    ])('un %s muestra su propio mensaje', async (_status, error, mensaje) => {
      mockAppointments.mockImplementation(fallaCon(error))

      render(<ClientAppointmentsContainer store={store} />)
      await entrar()

      expect(screen.getByRole('alert')).toHaveTextContent(mensaje)
    })
  })
})
