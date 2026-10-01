import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import type { PublicStore } from '@application/services/PublicBookingService'

import { ConflictError } from '@shared/errors'
import { ForbiddenError } from '@shared/errors/ForbiddenError'
import { InternalServerError } from '@shared/errors/InternalServerError'
import { NotFoundError } from '@shared/errors/NotFoundError'
import { RateLimitError } from '@shared/errors/RateLimitError'
import { ServiceUnavailableError } from '@shared/errors/ServiceUnavailableError'
import { isOtpStillValid, rememberOtpVerification } from '@shared/utils/otpSession'

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

const pedirYVerificarCodigo = async () => {
  fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: '1155550101' } })
  fireEvent.change(screen.getByLabelText('Tu email'), {
    target: { value: 'yo@example.com' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))
  await screen.findByLabelText('Código')
  fireEvent.change(screen.getByLabelText('Código'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ver mis turnos' }))
}

const entrar = async () => {
  await pedirYVerificarCodigo()
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
    mockAppointments.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: mockRefetch
    })
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

  describe('verificacion rechazada y errores al buscar (FF-05)', () => {
    // FF-05 (2026-09-29): con el telefono "verificado" desde el wizard
    // (sessionStorage, 30 min), "Mis turnos" entraba sin pedir codigo, el GET
    // respondia 403 OTP_VERIFICATION_REQUIRED y la pantalla decia "No
    // encontramos turnos". "Salir" y volver entraba por el mismo atajo: el
    // cliente quedaba 30 minutos en un bucle. Lo mismo con una ficha sin email
    // entregable. Y 404, 429 y 503 mostraban el mismo texto.
    // 2026-09-30: sin efecto; el 403 muestra la puerta con skipRemembered y
    // "Enviarme el código" siempre pide un codigo nuevo.
    const aviso =
      'Para ver tus turnos verificá el email que tenés registrado en Peluqueria Sol. Pedí un código nuevo.'
    const rechazo = new ForbiddenError('Se requiere validar OTP antes de autogestionar turnos', {
      errorCode: 'OTP_VERIFICATION_REQUIRED',
      statusCode: 403
    })

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

    it('un 403 OTP_VERIFICATION_REQUIRED muestra la puerta con el aviso y no entra por el atajo', async () => {
      mockAppointments.mockImplementation(fallaCon(rechazo))

      render(<ClientAppointmentsContainer store={store} />)
      entrarPorElAtajo()

      expect(await screen.findByText(aviso)).toBeInTheDocument()
      expect(screen.queryByText(/No encontramos turnos/)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Salir' })).not.toBeInTheDocument()
      expect((screen.getByLabelText('Teléfono') as HTMLInputElement).value).toBe('1155550101')

      // Aunque la marca del dispositivo siga vigente, pedir el codigo no entra
      // por el atajo: la olvida y manda uno nuevo.
      rememberOtpVerification('sol', '1155550101', new Date().toISOString())
      fireEvent.change(screen.getByLabelText('Tu email'), { target: { value: 'yo@example.com' } })
      fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))

      expect(await screen.findByLabelText('Código')).toBeInTheDocument()
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
      expect(isOtpStillValid('sol', '1155550101')).toBe(false)
      expect(mockRefetch).not.toHaveBeenCalled()
    })

    it('verificar de nuevo el mismo telefono vuelve a pedir los turnos', async () => {
      mockAppointments.mockImplementation(fallaCon(rechazo))

      render(<ClientAppointmentsContainer store={store} />)
      entrarPorElAtajo()
      await screen.findByText(aviso)
      // Con el 403 vigente la puerta sigue en pantalla y "Salir" no aparece.
      await pedirYVerificarCodigo()

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1))
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('si el 403 se repite tras un codigo nuevo, pedir el codigo manda otro de verdad', async () => {
      // FF-05 (2026-09-29): con la ficha sin email entregable, el codigo nuevo
      // se guardaba, el reintento volvia a dar 403 y "Enviarme el código"
      // entraba por el atajo al mismo 403 sin mandar ningun codigo.
      // F4-11 (2026-09-30): el segundo pedido espera los 60 s del primero.
      jest.useFakeTimers()
      try {
        mockAppointments.mockImplementation(fallaCon(rechazo))

        render(<ClientAppointmentsContainer store={store} />)
        entrarPorElAtajo()
        await screen.findByText(aviso)
        // Con el 403 vigente la puerta sigue en pantalla y "Salir" no aparece.
        await pedirYVerificarCodigo()
        await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1))
        // El codigo nuevo quedo guardado y el reintento sigue en 403.
        expect(isOtpStillValid('sol', '1155550101')).toBe(true)
        expect(screen.getByText(aviso)).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Cambiar teléfono o email' }))
        expect(screen.getByRole('button', { name: /^Reenviar en \d+ s$/ })).toBeDisabled()
        act(() => {
          jest.advanceTimersByTime(60_000)
        })
        fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))

        await waitFor(() => expect(mockRequestOtp).toHaveBeenCalledTimes(2))
        expect(isOtpStillValid('sol', '1155550101')).toBe(false)
        expect(mockRefetch).toHaveBeenCalledTimes(1)
      } finally {
        jest.useRealTimers()
      }
    })

    it('un 404 dice que no hay turnos para ese telefono, sin reintentar', async () => {
      mockAppointments.mockImplementation(
        fallaCon(
          new NotFoundError('No se encontraron turnos para ese número de teléfono', {
            errorCode: 'CLIENT_APPOINTMENTS_NOT_FOUND',
            statusCode: 404
          })
        )
      )

      render(<ClientAppointmentsContainer store={store} />)
      await entrar()

      expect(screen.getByRole('alert')).toHaveTextContent(
        'No encontramos turnos para ese teléfono en Peluqueria Sol.'
      )
      expect(screen.queryByRole('button', { name: 'Reintentar' })).not.toBeInTheDocument()
    })

    it.each([
      [
        '429',
        new RateLimitError('Too many requests', { errorCode: 'RATE_LIMITED', statusCode: 429 }),
        'Hiciste demasiados intentos seguidos. Esperá un momento y volvé a intentar.'
      ],
      [
        '503',
        new ServiceUnavailableError('Service Unavailable', { statusCode: 503 }),
        'No pudimos cargar tus turnos. Probá de nuevo en unos minutos.'
      ],
      [
        '503 del rate limit',
        new ServiceUnavailableError('Service Unavailable', {
          errorCode: 'RATE_LIMIT_UNAVAILABLE',
          statusCode: 503
        }),
        'El servicio no está disponible en este momento. Probá de nuevo en unos minutos.'
      ],
      [
        '500',
        new InternalServerError('Internal Server Error', { statusCode: 500 }),
        'No pudimos cargar tus turnos. Probá de nuevo en unos minutos.'
      ]
    ])('un %s muestra su mensaje y deja reintentar', async (_status, error, mensaje) => {
      mockAppointments.mockImplementation(fallaCon(error))

      render(<ClientAppointmentsContainer store={store} />)
      await entrar()

      expect(screen.getByRole('alert')).toHaveTextContent(mensaje)
      fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
      expect(mockRefetch).toHaveBeenCalledTimes(1)
    })
  })
})
