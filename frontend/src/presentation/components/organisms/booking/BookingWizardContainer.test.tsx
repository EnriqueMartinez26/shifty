import type { ComponentProps } from 'react'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router'

import { NetworkError, RateLimitError } from '@shared/errors'

import { BookingWizardContainer } from './BookingWizardContainer'
import { EMPTY_PRESELECT, initialStepFor } from './deepLink'
import { useBookingStepParam } from '../../../hooks/useBookingStepParam'
import type { PublicStore } from '../../../hooks/usePublic'

const mockServices = jest.fn()
const mockStaff = jest.fn()
const mockAvailability = jest.fn()
const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()
const mockCreateBooking = jest.fn()

jest.mock('../../../hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockServices(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicDepositPreview: () => ({ data: undefined, isLoading: false }),
  usePreviewPublicPromotion: () => ({ mutateAsync: jest.fn(), isPending: false }),
  useJoinWaitlist: () => ({ mutateAsync: jest.fn(), isPending: false, isSuccess: false }),
  useCreatePublicBooking: () => ({ mutateAsync: mockCreateBooking, isPending: false }),
  useRequestPublicOtp: () => ({ mutateAsync: mockRequestOtp, isPending: false }),
  useVerifyPublicOtp: () => ({ mutateAsync: mockVerifyOtp, isPending: false })
}))

const servicio = (public_id: string) => ({
  public_id,
  name: `Servicio ${public_id}`,
  description: null,
  duration_minutes: 30,
  price: 1000,
  deposit_mode: 'none',
  deposit_type: 'fixed',
  deposit_amount: null,
  color: null
})

const tienda = (otp: boolean): PublicStore => ({
  public_id: 'store-1',
  name: 'Tienda',
  slug: 'tienda',
  business_type: 'generic',
  logo_url: null,
  primary_color: '#000',
  cancellation_hours: 24,
  custom_client_fields: [],
  feature_flags: {
    payments: false,
    ledger: false,
    advanced_reports: false,
    new_calendar: false,
    otp_booking: otp
  }
})

const slot = {
  staff_id: 'st-1',
  staff_name: 'Pro',
  starts_at: '2026-09-25T12:00:00+00:00',
  ends_at: '2026-09-25T12:30:00+00:00',
  status: 'available',
  reason: null
}

const HORARIO = 'Elegí fecha y hora'
const SERVICIO = '¿Qué servicio necesitás?'
const DATOS = 'juan@email.com'

type WizardProps = Omit<ComponentProps<typeof BookingWizardContainer>, 'step' | 'onStepChange'>

// El paso vive en la URL (F4-15): el wizard se monta como lo hace
// PublicBooking, con el hook que lee y escribe ?step=.
const ConPasoEnUrl = (props: WizardProps) => {
  const { step, changeStep } = useBookingStepParam(
    initialStepFor(props.preselect ?? EMPTY_PRESELECT)
  )
  return <BookingWizardContainer {...props} step={step} onStepChange={changeStep} />
}

const Navegador = () => {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <p data-testid="url">{`${location.pathname}${location.search}`}</p>
      <button type="button" onClick={() => void navigate(-1)}>
        Atras del navegador
      </button>
    </>
  )
}

const WizardEnRuta = ({
  historial = ['/booking/tienda'],
  ...props
}: WizardProps & { historial?: string[] }) => (
  <MemoryRouter initialEntries={historial} initialIndex={historial.length - 1}>
    <Routes>
      <Route path="/booking/:slug" element={<ConPasoEnUrl {...props} />} />
      <Route path="*" element={null} />
    </Routes>
    <Navegador />
  </MemoryRouter>
)

const url = () => screen.getByTestId('url').textContent
const atrasDelNavegador = () => fireEvent.click(screen.getByText('Atras del navegador'))

describe('BookingWizardContainer', () => {
  beforeEach(() => {
    mockServices.mockReset()
    mockStaff.mockReset()
    mockAvailability.mockReset()
    mockRequestOtp.mockReset()
    mockVerifyOtp.mockReset()
    mockCreateBooking.mockReset()
    mockStaff.mockReturnValue({ data: [], isLoading: false })
    mockAvailability.mockReturnValue({ data: [slot], isLoading: false })
    window.sessionStorage.clear()
  })

  it('con un servicio valido en la URL arranca en el horario', () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    render(
      <WizardEnRuta
        store={tienda(false)}
        preselect={{ serviceId: 'a', staffId: 'st-1', date: null }}
      />
    )
    expect(screen.getByText(HORARIO)).toBeInTheDocument()
    expect(screen.queryByText(SERVICIO)).not.toBeInTheDocument()
  })

  it('con un solo servicio lo elige solo y salta al horario; "atras" no vuelve al servicio', async () => {
    mockServices.mockReturnValue({ data: [servicio('unico')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'unico', expect.any(String), false)

    // El primer boton del paso es el de "atras" (chevron).
    fireEvent.click(screen.getAllByRole('button')[0] as HTMLElement)
    expect(screen.getByText(HORARIO)).toBeInTheDocument()
    expect(screen.queryByText(SERVICIO)).not.toBeInTheDocument()
  })

  it('con varios servicios arranca eligiendo el servicio', () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)
    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
  })

  // 2026-10-02 (F4-15): el paso vivia solo en memoria. "Atras" del navegador
  // sacaba de la reserva y un link no podia volver al paso en que estaba.
  describe('paso en la URL', () => {
    const elegirServicioYHorario = () => {
      fireEvent.click(screen.getByText('Servicio a'))
      fireEvent.click(screen.getByText('09:00'))
    }

    beforeEach(() => {
      mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    })

    it('avanzar escribe ?step= sin pisar los otros parametros', () => {
      render(<WizardEnRuta store={tienda(false)} historial={['/booking/tienda?ref=ig']} />)

      fireEvent.click(screen.getByText('Servicio a'))
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda?ref=ig&step=1')

      fireEvent.click(screen.getByText('09:00'))
      expect(screen.getByPlaceholderText(DATOS)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda?ref=ig&step=2')
    })

    it('"atras" del navegador vuelve al paso anterior con lo elegido', () => {
      render(<WizardEnRuta store={tienda(false)} />)
      elegirServicioYHorario()

      atrasDelNavegador()
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(mockAvailability).toHaveBeenLastCalledWith('store-1', 'a', expect.any(String), false)

      atrasDelNavegador()
      expect(screen.getByText(SERVICIO)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda')
    })

    it('"atras" de la app retrocede en el historial sin dejar un paso repetido', () => {
      render(<WizardEnRuta store={tienda(false)} historial={['/otra-pagina', '/booking/tienda']} />)
      elegirServicioYHorario()

      // Atras desde los datos y desde el horario: dos pasos para atras.
      fireEvent.click(screen.getAllByRole('button')[0] as HTMLElement)
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      fireEvent.click(screen.getAllByRole('button')[0] as HTMLElement)
      expect(screen.getByText(SERVICIO)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda')

      // Un "atras" mas del navegador sale de la reserva: no rebota a un paso.
      atrasDelNavegador()
      expect(url()).toBe('/otra-pagina')
    })

    it('el salto automatico con un solo servicio no deja un paso al que rebotar', async () => {
      mockServices.mockReturnValue({ data: [servicio('unico')], isLoading: false })
      render(<WizardEnRuta store={tienda(false)} historial={['/otra-pagina', '/booking/tienda']} />)
      await waitFor(() => expect(url()).toBe('/booking/tienda?step=1'))
      expect(screen.getByText(HORARIO)).toBeInTheDocument()

      atrasDelNavegador()
      expect(url()).toBe('/otra-pagina')
    })

    it('el deep-link arranca en el horario y "atras" del navegador sale sin rebotar', () => {
      render(
        <WizardEnRuta
          store={tienda(false)}
          preselect={{ serviceId: 'a', staffId: null, date: null }}
          historial={['/otra-pagina', '/booking/tienda?service=a']}
        />
      )
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda?service=a')

      atrasDelNavegador()
      expect(url()).toBe('/otra-pagina')
    })

    it('volver al servicio desde un deep-link lo deja explicito en la URL', () => {
      render(
        <WizardEnRuta
          store={tienda(false)}
          preselect={{ serviceId: 'a', staffId: null, date: null }}
          historial={['/booking/tienda?service=a']}
        />
      )

      fireEvent.click(screen.getAllByRole('button')[0] as HTMLElement)

      expect(screen.getByText(SERVICIO)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda?service=a&step=0')
    })

    it('un ?step= sin lo elegido (recarga) se degrada y corrige la URL', async () => {
      render(<WizardEnRuta store={tienda(false)} historial={['/booking/tienda?step=2']} />)

      expect(screen.getByText(SERVICIO)).toBeInTheDocument()
      await waitFor(() => expect(url()).toBe('/booking/tienda'))
    })

    it('un deep-link con ?step=2 sin horario elegido queda en el horario', async () => {
      render(
        <WizardEnRuta
          store={tienda(false)}
          preselect={{ serviceId: 'a', staffId: null, date: null }}
          historial={['/booking/tienda?service=a&step=2']}
        />
      )

      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      await waitFor(() => expect(url()).toBe('/booking/tienda?service=a'))
    })
  })

  it('el codigo OTP se pide por email, al email que escribe el cliente', async () => {
    mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
    mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '2026-09-25T13:00:00Z' })
    render(<WizardEnRuta store={tienda(true)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))

    fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
      target: { value: 'lucia@example.com' }
    })
    fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
      target: { value: '+5491155550101' }
    })
    // El email del codigo arranca con el del formulario.
    expect((screen.getByLabelText('Email para el código') as HTMLInputElement).value).toBe(
      'lucia@example.com'
    )
    fireEvent.click(screen.getByText('Enviar código'))

    await waitFor(() => expect(mockRequestOtp).toHaveBeenCalledTimes(1))
    expect(mockRequestOtp).toHaveBeenCalledWith({
      store_public_id: 'store-1',
      phone: '+5491155550101',
      channel: 'email',
      email: 'lucia@example.com'
    })
    expect(screen.queryByText('WhatsApp')).not.toBeInTheDocument()
    expect(screen.queryByText('SMS')).not.toBeInTheDocument()
  })

  it('un telefono verificado hace menos de 30 minutos en este dispositivo no pide otro codigo', async () => {
    mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
    window.sessionStorage.setItem(
      'shifty:otp:tienda',
      JSON.stringify({ phone: '5491155550101', verifiedAt: new Date().toISOString() })
    )
    render(<WizardEnRuta store={tienda(true)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))
    fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
      target: { value: '+5491155550101' }
    })

    expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
    expect(mockRequestOtp).not.toHaveBeenCalled()
  })

  it('sin sessionStorage, editar otro dato no des-verifica el telefono', async () => {
    // F11a-08 (2026-09-24): se comparaba el telefono tipeado contra el
    // normalizado que devuelve el backend (+54...): nunca coincidian y solo
    // sessionStorage salvaba la verificacion. Sin storage, escribir en
    // "Notas" borraba "Telefono validado" y obligaba a pedir otro codigo.
    const getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage bloqueado')
    })
    const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage bloqueado')
    })
    try {
      mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
      mockVerifyOtp.mockResolvedValue({
        phone: '+5491155550101',
        verified_at: new Date().toISOString()
      })
      render(<WizardEnRuta store={tienda(true)} />)

      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '54 9 11 5555-0101' }
      })
      fireEvent.change(screen.getByPlaceholderText('Código que te llegó por email'), {
        target: { value: '123456' }
      })
      fireEvent.click(screen.getByText('Verificar código'))
      await waitFor(() =>
        expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
      )

      fireEvent.change(screen.getByPlaceholderText('Algo que debamos saber?'), {
        target: { value: 'Llego 5 minutos tarde' }
      })

      expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()

      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '54 9 11 5555-0102' }
      })
      expect(screen.queryByText('Teléfono validado correctamente')).not.toBeInTheDocument()
    } finally {
      getItem.mockRestore()
      setItem.mockRestore()
    }
  })

  describe('clave de idempotencia estable tras recargar (F4-04)', () => {
    // F4-04 a (2026-10-01): la clave salia de createUuid() en un useState: al
    // recargar despues de una respuesta perdida, el mismo pedido viajaba con
    // otra clave y el backend no podia devolver la reserva ya hecha.
    const confirmarReserva = async (nombre = 'Lucia') => {
      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('Ej: Juan Perez'), {
        target: { value: nombre }
      })
      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '+5491155550101' }
      })
      fireEvent.click(screen.getByRole('checkbox'))
      await enviar()
    }
    // La huella se calcula con crypto.subtle, que es asincronico: se espera al
    // envio en vez de suponer que sale en el mismo tick del click.
    const enviar = async () => {
      const antes = mockCreateBooking.mock.calls.length
      await act(async () => {
        fireEvent.click(screen.getByText('Reservar y pagar por WhatsApp'))
      })
      await waitFor(() => expect(mockCreateBooking).toHaveBeenCalledTimes(antes + 1))
    }
    const claveDelIntento = (n: number) =>
      (mockCreateBooking.mock.calls[n]?.[0] as { idempotency_key?: string }).idempotency_key

    beforeEach(() => {
      mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
    })

    it('recargar y reenviar el mismo pedido conserva la clave', async () => {
      mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
      const primera = render(<WizardEnRuta store={tienda(false)} />)
      await confirmarReserva()
      primera.unmount()

      render(<WizardEnRuta store={tienda(false)} />)
      await confirmarReserva()

      expect(mockCreateBooking).toHaveBeenCalledTimes(2)
      expect(claveDelIntento(0)).toEqual(expect.any(String))
      expect(claveDelIntento(1)).toBe(claveDelIntento(0))
    })

    it('lo que queda en sessionStorage no tiene datos del cliente', async () => {
      // 2026-10-01 (review de #83): la huella era el pedido en claro y dejaba
      // nombre y telefono del cliente en sessionStorage.
      mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
      render(<WizardEnRuta store={tienda(false)} />)
      await confirmarReserva('Lucia')

      const crudo = window.sessionStorage.getItem('shifty:booking-idem:tienda') ?? ''
      expect(crudo).not.toBe('')
      expect(crudo).not.toContain('Lucia')
      expect(crudo).not.toContain('5491155550101')
      expect(crudo).not.toContain('1155550101')
      expect(JSON.parse(crudo)).toEqual({
        fpHash: expect.stringMatching(/^[0-9a-f]{64}$/),
        key: claveDelIntento(0)
      })
    })

    it('recargar y reenviar otros datos manda otra clave', async () => {
      mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
      const primera = render(<WizardEnRuta store={tienda(false)} />)
      await confirmarReserva('Lucia')
      primera.unmount()

      render(<WizardEnRuta store={tienda(false)} />)
      await confirmarReserva('Lucia Perez')

      expect(claveDelIntento(1)).not.toBe(claveDelIntento(0))
    })

    it('una reserva confirmada borra la clave guardada', async () => {
      mockCreateBooking.mockRejectedValueOnce(new NetworkError('sin red')).mockResolvedValueOnce({
        public_id: 'appt-1',
        service_id: 'a',
        service_name: 'Servicio a',
        staff_id: 'st-1',
        staff_name: 'Pro',
        starts_at: slot.starts_at,
        ends_at: slot.ends_at,
        status: 'pending',
        client_name: 'Lucia',
        client_phone: '+5491155550101',
        payment_required: false
      })
      render(<WizardEnRuta store={tienda(false)} />)
      await confirmarReserva()
      // El intento fallido deja la clave guardada para el reintento.
      expect(window.sessionStorage.getItem('shifty:booking-idem:tienda')).not.toBeNull()

      await enviar()

      expect(claveDelIntento(1)).toBe(claveDelIntento(0))
      await waitFor(() =>
        expect(window.sessionStorage.getItem('shifty:booking-idem:tienda')).toBeNull()
      )
    })
  })

  describe('pedir el codigo desde el celular (F4-11, J7)', () => {
    // 2026-09-30, F4-11: sin espera para reenviar, cada toque de "Enviar
    // codigo" mientras el mail tardaba gastaba uno de los 5 pedidos por hora
    // (OTP_MAX_REQUESTS_PER_HOUR) y el cliente quedaba bloqueado una hora.
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    const hastaPedirElCodigo = async () => {
      mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
      render(<WizardEnRuta store={tienda(true)} />)
      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
        target: { value: 'lucia@example.com' }
      })
      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '+5491155550101' }
      })
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Enviar código' }))
      })
    }

    it('despues de un pedido exitoso espera 60 s para reenviar y muestra los segundos', async () => {
      mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '2026-09-30T13:00:00Z' })
      await hastaPedirElCodigo()

      expect(screen.getByRole('button', { name: 'Reenviar en 60 s' })).toBeDisabled()
      act(() => {
        jest.advanceTimersByTime(30_000)
      })
      expect(screen.getByRole('button', { name: 'Reenviar en 30 s' })).toBeDisabled()
      act(() => {
        jest.advanceTimersByTime(30_000)
      })
      expect(screen.getByRole('button', { name: 'Enviar código' })).not.toBeDisabled()
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('un pedido fallido sin Retry-After no arranca la espera', async () => {
      mockRequestOtp.mockRejectedValue(new Error('Demasiados pedidos'))
      await hastaPedirElCodigo()

      expect(screen.getByRole('button', { name: 'Enviar código' })).not.toBeDisabled()
      expect(screen.queryByText(/Reenviar en/)).not.toBeInTheDocument()
    })

    it('un error con Retry-After espera lo que pide el servidor', async () => {
      // 2026-09-30, F4-11: el 429 del rate limit traia Retry-After y el boton
      // quedaba habilitado para volver a chocar contra el limite.
      mockRequestOtp.mockRejectedValue(
        new RateLimitError('Espera', { errorCode: 'RATE_LIMITED', statusCode: 429, retryAfter: 20 })
      )
      await hastaPedirElCodigo()

      expect(screen.getByRole('button', { name: 'Reenviar en 20 s' })).toBeDisabled()
      act(() => {
        jest.advanceTimersByTime(20_000)
      })
      expect(screen.getByRole('button', { name: 'Enviar código' })).not.toBeDisabled()
    })

    it('OTP_RATE_LIMITED bloquea el pedido sin cuenta regresiva y lo explica', async () => {
      // 2026-09-30, F4-11: agotados los codigos del telefono, el boton seguia
      // habilitado; la ventana del backend es deslizante, asi que no hay un
      // numero honesto de segundos para mostrar.
      mockRequestOtp.mockRejectedValue(
        new RateLimitError('Demasiados intentos.', {
          errorCode: 'OTP_RATE_LIMITED',
          statusCode: 429,
          detail: { retry_after_seconds: 60 }
        })
      )
      await hastaPedirElCodigo()

      const aviso =
        'Pediste demasiados códigos para este teléfono. Esperá un rato antes de pedir otro.'
      expect(screen.getByRole('alert')).toHaveTextContent(aviso)
      expect(screen.getByRole('button', { name: 'Enviar código' })).toBeDisabled()
      expect(screen.queryByText(/Reenviar en/)).not.toBeInTheDocument()

      act(() => {
        jest.advanceTimersByTime(10 * 60_000)
      })
      fireEvent.change(screen.getByLabelText('Email para el código'), {
        target: { value: 'otra@example.com' }
      })
      expect(screen.getByRole('button', { name: 'Enviar código' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(aviso)
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('cambiar el telefono libera la espera', async () => {
      // 2026-09-30, F4-11: la espera es del telefono pedido; corregir un
      // numero mal tipeado no tiene por que esperar el minuto del anterior.
      mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '2026-09-30T13:00:00Z' })
      await hastaPedirElCodigo()
      expect(screen.getByRole('button', { name: 'Reenviar en 60 s' })).toBeDisabled()

      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '+5491155550202' }
      })

      expect(screen.getByRole('button', { name: 'Enviar código' })).not.toBeDisabled()
    })

    describe('codigo debug (J7)', () => {
      // 2026-09-30, J7: mostrar el codigo debug con aviso de que puede no
      // servir. Con OTP_DEBUG_EXPOSE_CODE el backend devuelve un senuelo si el
      // codigo fue al email de la ficha y no al tipeado (AUD2-SYNC-01); el
      // front muestra debug_code tal cual llega y avisa que puede no servir.
      const AVISO =
        'Código debug (solo desarrollo): 424242. Si el teléfono ya tiene ficha con email, el código real fue a ese buzón y este puede no servir.'

      it('un pedido exitoso con debug_code muestra el codigo con el aviso', async () => {
        mockRequestOtp.mockResolvedValue({
          ok: true,
          expires_at: '2026-09-30T13:00:00Z',
          debug_code: '424242'
        })
        await hastaPedirElCodigo()

        expect(mockRequestOtp).toHaveBeenCalledTimes(1)
        expect(screen.getByRole('status')).toHaveTextContent(AVISO)
      })

      it('un pedido exitoso sin debug_code no muestra nada', async () => {
        mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '2026-09-30T13:00:00Z' })
        await hastaPedirElCodigo()

        expect(mockRequestOtp).toHaveBeenCalledTimes(1)
        expect(screen.queryByText(/Código debug/)).not.toBeInTheDocument()
      })

      it('cambiar el telefono verificado borra el codigo debug con el codigo tipeado', async () => {
        mockRequestOtp.mockResolvedValue({
          ok: true,
          expires_at: '2026-09-30T13:00:00Z',
          debug_code: '424242'
        })
        mockVerifyOtp.mockResolvedValue({
          phone: '+5491155550101',
          verified_at: '2026-09-30T12:00:00Z'
        })
        await hastaPedirElCodigo()
        fireEvent.change(screen.getByPlaceholderText('Código que te llegó por email'), {
          target: { value: '424242' }
        })
        await act(async () => {
          fireEvent.click(screen.getByRole('button', { name: 'Verificar código' }))
        })
        expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
        // 2026-10-02: sin esta precondicion el test pasaba aunque el aviso
        // nunca se hubiera mostrado; el borrado tiene que partir de verlo.
        expect(screen.getByText(AVISO)).toBeInTheDocument()

        fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
          target: { value: '+5491155550202' }
        })

        expect(screen.queryByText(/Código debug/)).not.toBeInTheDocument()
      })
    })
  })
})
