import type { ComponentProps } from 'react'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router'

import { forgetClientToken, rememberClientToken } from '@application/services/clientToken'

import { NetworkError, RateLimitError } from '@shared/errors'
import { formatCurrency } from '@shared/utils/currency'
import { forgetOtpVerification, rememberOtpVerification } from '@shared/utils/otpSession'

import { BookingWizardContainer } from './BookingWizardContainer'
import { EMPTY_PRESELECT, initialStepFor } from './deepLink'
import { colors2000s } from '../../../../theme/colors'
import { useBookingStepParam } from '../../../hooks/useBookingStepParam'
import type { PublicStore } from '../../../hooks/usePublic'
import { brandCssVariables, resolveBrandTheme } from '../../../lib/brandTheme'

const mockServices = jest.fn()
const mockStaff = jest.fn()
const mockAvailability = jest.fn()
const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()
const mockCreateBooking = jest.fn()
const mockPreviewPromotion = jest.fn()

jest.mock('../../../hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockServices(...args),
  useRefreshPublicServices: () => jest.fn(),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  // El backend confirma el importe (sin seña): con adicionales, reservar
  // espera a que el preview de la seña responda bien.
  usePublicDepositPreview: () => ({
    data: {
      amount: 0,
      base_amount: 0,
      extra_percent: 0,
      reasons: [],
      price: 1000,
      payments_enabled: false,
      online_payment_mandatory: false
    },
    isLoading: false
  }),
  usePreviewPublicPromotion: () => ({ mutateAsync: mockPreviewPromotion, isPending: false }),
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
      <button type="button" onClick={() => void navigate(1)}>
        Adelante del navegador
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
const adelanteDelNavegador = () => fireEvent.click(screen.getByText('Adelante del navegador'))
// El "Volver" de la app, con texto visible (2026-10-16).
const volver = () => screen.getByRole('button', { name: 'Volver' })

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
    // La verificacion recordada vive en memoria (2026-10-14): se olvida entre tests.
    forgetOtpVerification('tienda')
    forgetClientToken()
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
    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'unico', expect.any(String), false, [])

    fireEvent.click(volver())
    expect(screen.getByText(HORARIO)).toBeInTheDocument()
    expect(screen.queryByText(SERVICIO)).not.toBeInTheDocument()
  })

  it('con varios servicios arranca eligiendo el servicio', () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)
    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
  })

  it('no mueve el foco al montar el paso inicial', () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    const focoInicial = document.activeElement

    render(<WizardEnRuta store={tienda(false)} />)

    expect(document.activeElement).toBe(focoInicial)
    expect(screen.getByRole('region', { name: 'Paso 1 de 3: Servicio' })).not.toHaveFocus()
  })

  it('mueve el foco al paso nuevo al avanzar y retroceder', async () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)

    fireEvent.click(screen.getByText('Servicio a'))
    await waitFor(() =>
      expect(
        screen.getByRole('region', { name: 'Paso 2 de 3: Horario y Profesional' })
      ).toHaveFocus()
    )

    fireEvent.click(screen.getByText('09:00'))
    await waitFor(() =>
      expect(
        screen.getByRole('region', { name: 'Paso 3 de 3: Datos y Confirmación' })
      ).toHaveFocus()
    )
    expect(screen.getByPlaceholderText('Ej: Juan Perez')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Ej: Juan Perez')).not.toHaveFocus()

    fireEvent.click(volver())
    await waitFor(() =>
      expect(
        screen.getByRole('region', { name: 'Paso 2 de 3: Horario y Profesional' })
      ).toHaveFocus()
    )
  })

  it('mueve el foco al horario cuando salta el paso de servicio unico', async () => {
    mockServices.mockReturnValue({ data: [servicio('unico')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)

    await waitFor(() =>
      expect(
        screen.getByRole('region', { name: 'Paso 2 de 3: Horario y Profesional' })
      ).toHaveFocus()
    )
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

    it('al elegir un horario enfoca la región sin abrir el teclado del formulario', async () => {
      mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
      render(<WizardEnRuta store={tienda(false)} />)
      fireEvent.click(screen.getByText('Servicio a'))
      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())

      fireEvent.click(screen.getByText('09:00'))

      const nameInput = await screen.findByPlaceholderText('Ej: Juan Perez')
      const stepRegion = screen.getByRole('region', {
        name: 'Paso 3 de 3: Datos y Confirmación'
      })
      await waitFor(() => expect(document.activeElement).toBe(stepRegion))
      expect(nameInput).not.toHaveFocus()
    })

    it('"atras" del navegador vuelve al paso anterior con lo elegido', () => {
      render(<WizardEnRuta store={tienda(false)} />)
      elegirServicioYHorario()

      atrasDelNavegador()
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(mockAvailability).toHaveBeenLastCalledWith(
        'store-1',
        'a',
        expect.any(String),
        false,
        []
      )

      atrasDelNavegador()
      expect(screen.getByText(SERVICIO)).toBeInTheDocument()
      expect(url()).toBe('/booking/tienda')
    })

    it('no restaura una confirmacion vieja si cambia la pagina de fechas antes de avanzar', async () => {
      render(<WizardEnRuta store={tienda(false)} />)
      elegirServicioYHorario()

      expect(screen.getByPlaceholderText(DATOS)).toBeInTheDocument()
      fireEvent.click(volver())
      expect(screen.getByText(HORARIO)).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: /Siguiente: mostrar/ }))
      expect(screen.getByText('Elegí una fecha para ver los horarios.')).toBeInTheDocument()

      adelanteDelNavegador()
      await waitFor(() => expect(url()).toBe('/booking/tienda?step=1'))
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(screen.queryByPlaceholderText(DATOS)).not.toBeInTheDocument()
    })

    it('"atras" de la app retrocede en el historial sin dejar un paso repetido', () => {
      render(<WizardEnRuta store={tienda(false)} historial={['/otra-pagina', '/booking/tienda']} />)
      elegirServicioYHorario()

      // Atras desde los datos y desde el horario: dos pasos para atras.
      fireEvent.click(volver())
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      fireEvent.click(volver())
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

      fireEvent.click(volver())

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

  // 2026-10-16 (pedido de Mateo): la confirmacion mostraba solo fecha y hora.
  it('con "Cualquiera" la confirmacion muestra el servicio y el profesional del horario', async () => {
    mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))

    // La confirmacion compacta resume el turno en una linea (S5).
    const resumen = screen.getByTestId('booking-summary-line')
    expect(resumen).toHaveTextContent('Servicio a')
    expect(resumen).toHaveTextContent('con Pro')
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
    fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
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
    rememberOtpVerification('tienda', '5491155550101', new Date().toISOString())
    rememberClientToken('store-1', 'tok-del-cliente')
    render(<WizardEnRuta store={tienda(true)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))
    fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
      target: { value: '+5491155550101' }
    })

    expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
    expect(mockRequestOtp).not.toHaveBeenCalled()
  })

  it('sin el token del cliente la verificacion recordada no alcanza y pide el codigo (2026-10-14)', async () => {
    // Con otp_booking el backend exige el token de la verificacion: entrar
    // por el atajo sin token terminaba en un 403 al reservar.
    mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
    rememberOtpVerification('tienda', '5491155550101', new Date().toISOString())
    render(<WizardEnRuta store={tienda(true)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))
    fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
      target: { value: '+5491155550101' }
    })

    expect(screen.queryByText('Teléfono validado correctamente')).not.toBeInTheDocument()
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
      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
        target: { value: '54 9 11 5555-0101' }
      })
      fireEvent.change(screen.getByPlaceholderText('Código que te llegó por email'), {
        target: { value: '123456' }
      })
      fireEvent.click(screen.getByText('Verificar código'))
      await waitFor(() =>
        expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
      )

      // Las notas van plegadas detras de un link (S5).
      fireEvent.click(screen.getByText('Agregar una nota para la tienda'))
      fireEvent.change(screen.getByPlaceholderText('Algo que debamos saber?'), {
        target: { value: 'Llego 5 minutos tarde' }
      })

      expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()

      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
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
      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
        target: { value: '+5491155550101' }
      })
      // Obligatorio en el portal (decision de Mateo, 2026-10-14).
      fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
        target: { value: 'lucia@example.com' }
      })
      fireEvent.click(screen.getByRole('checkbox'))
      // La seña se recalcula con el telefono tipeado (400 ms de espera).
      await waitFor(() => expect(screen.getByText('Confirmar reserva')).not.toBeDisabled())
      await enviar()
    }
    // La huella se calcula con crypto.subtle, que es asincronico: se espera al
    // envio en vez de suponer que sale en el mismo tick del click.
    const enviar = async () => {
      const antes = mockCreateBooking.mock.calls.length
      await act(async () => {
        fireEvent.click(screen.getByText('Confirmar reserva'))
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
      expect(crudo).not.toContain('lucia@example.com')
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

    // 2026-10-16 (pedido de Mateo): con un solo profesional no se ofrece
    // "Cualquiera"; la reserva sigue viajando con quien atiende el horario.
    it('con un solo profesional no ofrece "Cualquiera" y la reserva viaja con el', async () => {
      mockStaff.mockReturnValue({
        data: [{ public_id: 'st-1', kind: 'person', display_name: 'Pro', service_ids: ['a'] }],
        isLoading: false
      })
      mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
      render(<WizardEnRuta store={tienda(false)} />)

      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
      expect(screen.queryByRole('button', { name: /Cualquiera/ })).not.toBeInTheDocument()
      await confirmarReserva()

      expect(mockCreateBooking.mock.calls[0]?.[0]).toMatchObject({
        staff_id: 'st-1',
        starts_at: slot.starts_at
      })
    })

    it('manda los adicionales elegidos y otros adicionales son otro pedido', async () => {
      mockServices.mockReturnValue({
        data: [
          {
            ...servicio('a'),
            addons: [
              { id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }
            ]
          }
        ],
        isLoading: false
      })
      mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
      render(<WizardEnRuta store={tienda(false)} />)
      // S4 (2026-10-21): los adicionales se eligen en el paso del servicio.
      fireEvent.click(screen.getByText('Servicio a'))
      fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))
      fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))
      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('Ej: Juan Perez'), {
        target: { value: 'Lucia' }
      })
      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
        target: { value: '+5491155550101' }
      })
      fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
        target: { value: 'lucia@example.com' }
      })
      fireEvent.click(screen.getByRole('checkbox'))
      // La seña se recalcula con los adicionales despues de una espera corta:
      // hasta entonces no se puede reservar.
      await waitFor(() => expect(screen.getByText('Confirmar reserva')).not.toBeDisabled())
      await enviar()

      expect(mockCreateBooking.mock.calls[0]?.[0]).toMatchObject({
        addons: [{ addon_id: 'strass', quantity: 2 }]
      })

      // Del pedido al horario y del horario al servicio, con lo elegido.
      atrasDelNavegador()
      atrasDelNavegador()
      fireEvent.click(screen.getByRole('button', { name: 'Quitar uno de Strass' }))
      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.click(screen.getByRole('checkbox'))
      await waitFor(() => expect(screen.getByText('Confirmar reserva')).not.toBeDisabled())
      await enviar()

      expect(mockCreateBooking.mock.calls[1]?.[0]).toMatchObject({
        addons: [{ addon_id: 'strass', quantity: 1 }]
      })
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
      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
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

      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
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

        fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
          target: { value: '+5491155550202' }
        })

        expect(screen.queryByText(/Código debug/)).not.toBeInTheDocument()
      })
    })
  })

  // Varios servicios en un turno (2026-10-16): solo con el flag de la tienda.
  describe('varios servicios en un turno', () => {
    const tiendaMulti = (multi: boolean): PublicStore => {
      const base = tienda(false)
      return { ...base, feature_flags: { ...base.feature_flags, multi_service_booking: multi } }
    }
    const profesional = {
      public_id: 'st-1',
      kind: 'person',
      first_name: 'Pro',
      last_name: '',
      display_name: 'Pro',
      service_ids: ['a', 'b']
    }

    const completarYConfirmar = async () => {
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('Ej: Juan Perez'), {
        target: { value: 'Lucia' }
      })
      fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
        target: { value: '+5491155550101' }
      })
      fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
        target: { value: 'lucia@example.com' }
      })
      fireEvent.click(screen.getByRole('checkbox'))
      await waitFor(() => expect(screen.getByText('Confirmar reserva')).not.toBeDisabled())
      await act(async () => {
        fireEvent.click(screen.getByText('Confirmar reserva'))
      })
      await waitFor(() => expect(mockCreateBooking).toHaveBeenCalledTimes(1))
      return mockCreateBooking.mock.calls[0]?.[0] as Record<string, unknown>
    }

    beforeEach(() => {
      mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
      mockStaff.mockReturnValue({ data: [profesional], isLoading: false })
      mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
    })

    it('con el flag, tocar suma servicios y la barra lleva al horario con todos', async () => {
      render(<WizardEnRuta store={tiendaMulti(true)} />)

      fireEvent.click(screen.getByText('Servicio a'))
      fireEvent.click(screen.getByText('Servicio b'))
      expect(screen.getByText(SERVICIO)).toBeInTheDocument()
      expect(screen.getByTestId('booking-services-bar')).toHaveTextContent('2 servicios · 60 min')

      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(mockAvailability).toHaveBeenLastCalledWith('store-1', 'a', expect.any(String), false, [
        'b'
      ])

      const pedido = await completarYConfirmar()
      expect(pedido).toMatchObject({ service_id: 'a', extra_service_ids: ['b'] })
    })

    it('con el flag y un solo servicio elegido el pedido es el de siempre', async () => {
      render(<WizardEnRuta store={tiendaMulti(true)} />)

      fireEvent.click(screen.getByText('Servicio b'))
      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))

      const pedido = await completarYConfirmar()
      expect(pedido.service_id).toBe('b')
      expect(pedido).not.toHaveProperty('extra_service_ids')
    })

    it('sin el flag, tocar un servicio lo elige y avanza, sin barra', () => {
      render(<WizardEnRuta store={tiendaMulti(false)} />)

      fireEvent.click(screen.getByText('Servicio a'))

      expect(screen.getByText(HORARIO)).toBeInTheDocument()
      expect(screen.queryByTestId('booking-services-bar')).not.toBeInTheDocument()
    })

    it('volver al servicio conserva lo elegido y quitar el principal asciende al siguiente', async () => {
      render(<WizardEnRuta store={tiendaMulti(true)} />)

      fireEvent.click(screen.getByText('Servicio a'))
      fireEvent.click(screen.getByText('Servicio b'))
      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
      fireEvent.click(volver())

      expect(screen.getByRole('button', { name: /Servicio a/ })).toHaveAttribute(
        'aria-pressed',
        'true'
      )
      fireEvent.click(screen.getByText('Servicio a'))
      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))

      const pedido = await completarYConfirmar()
      expect(pedido.service_id).toBe('b')
      expect(pedido).not.toHaveProperty('extra_service_ids')
    })

    // Revision de #194 (L4): quien hace que lo pide el contenedor y el paso
    // del servicio solo pinta.
    it('el contenedor pide los profesionales y apaga lo que nadie hace junto', () => {
      mockServices.mockReturnValue({
        data: [servicio('a'), servicio('b'), servicio('c')],
        isLoading: false
      })
      render(<WizardEnRuta store={tiendaMulti(true)} />)

      fireEvent.click(screen.getByText('Servicio a'))

      expect(mockStaff).toHaveBeenCalledWith('store-1', undefined, true)
      expect(screen.getByRole('button', { name: /Servicio c/ })).toBeDisabled()
      expect(screen.getByRole('button', { name: /Servicio b/ })).not.toBeDisabled()
    })

    it('sin el flag no pide la lista de profesionales de la tienda', () => {
      render(<WizardEnRuta store={tiendaMulti(false)} />)

      expect(mockStaff).toHaveBeenCalledWith('store-1', undefined, false)
    })

    // Revision de #194 (L6): sumar un servicio no pierde al profesional del
    // deep-link si hace todos; si no, vuelve a "Cualquiera".
    describe('profesional pedido por deep-link', () => {
      const pro = (public_id: string, service_ids: string[]) => ({
        ...profesional,
        public_id,
        display_name: `Pro ${public_id}`,
        service_ids
      })
      const slotDe = (staff_id: string, starts_at: string) => ({
        ...slot,
        staff_id,
        staff_name: `Pro ${staff_id}`,
        starts_at
      })

      beforeEach(() => {
        mockStaff.mockReturnValue({
          data: [pro('st-1', ['a']), pro('st-2', ['a', 'b']), pro('st-3', ['a', 'b'])],
          isLoading: false
        })
        mockAvailability.mockReturnValue({
          data: [
            slotDe('st-2', '2026-09-25T12:00:00+00:00'),
            slotDe('st-3', '2026-09-25T13:00:00+00:00')
          ],
          isLoading: false
        })
      })

      const sumarB = () => {
        fireEvent.click(volver())
        fireEvent.click(screen.getByText('Servicio b'))
        fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
        expect(screen.getByText(HORARIO)).toBeInTheDocument()
      }

      it('lo conserva si hace todos los servicios elegidos', () => {
        render(
          <WizardEnRuta
            store={tiendaMulti(true)}
            preselect={{ serviceId: 'a', staffId: 'st-2', date: '2026-09-25' }}
          />
        )
        sumarB()

        expect(screen.getByText('09:00')).toBeInTheDocument()
        expect(screen.queryByText('10:00')).not.toBeInTheDocument()
      })

      it('lo suelta si no hace alguno', () => {
        render(
          <WizardEnRuta
            store={tiendaMulti(true)}
            preselect={{ serviceId: 'a', staffId: 'st-1', date: '2026-09-25' }}
          />
        )
        sumarB()

        expect(screen.getByText('09:00')).toBeInTheDocument()
        expect(screen.getByText('10:00')).toBeInTheDocument()
      })
    })
  })
})

// S4 (2026-10-21): los adicionales se eligen en el paso del servicio, debajo
// de cada servicio elegido, y la barra suma el total al momento.
describe('BookingWizardContainer con adicionales en el paso del servicio', () => {
  const adicional = (id: string, name: string, unit_price: number) => ({
    id,
    name,
    unit_price,
    max_quantity: 5,
    position: 0
  })
  const conAdicionales = (public_id: string, addons: ReturnType<typeof adicional>[]) => ({
    ...servicio(public_id),
    addons
  })
  const corteConStrass = conAdicionales('a', [adicional('strass', 'Strass', 500)])
  const barbaConBrillo = conAdicionales('b', [adicional('brillo', 'Brillo', 300)])
  const tiendaMulti = (): PublicStore => {
    const base = tienda(false)
    return { ...base, feature_flags: { ...base.feature_flags, multi_service_booking: true } }
  }
  const agregar = (name: string) =>
    fireEvent.click(screen.getByRole('button', { name: `Agregar uno de ${name}` }))
  const continuar = () => fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))

  const reservar = async () => {
    fireEvent.click(screen.getByText('09:00'))
    fireEvent.change(screen.getByPlaceholderText('Ej: Juan Perez'), {
      target: { value: 'Lucia' }
    })
    fireEvent.change(screen.getByPlaceholderText('Ej: 351 1234567'), {
      target: { value: '+5491155550101' }
    })
    fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
      target: { value: 'lucia@example.com' }
    })
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(screen.getByText('Confirmar reserva')).not.toBeDisabled())
    await act(async () => {
      fireEvent.click(screen.getByText('Confirmar reserva'))
    })
    await waitFor(() => expect(mockCreateBooking).toHaveBeenCalledTimes(1))
    return mockCreateBooking.mock.calls[0]?.[0] as Record<string, unknown>
  }

  beforeEach(() => {
    mockServices.mockReset()
    mockAvailability.mockReset()
    mockCreateBooking.mockReset()
    mockPreviewPromotion.mockReset()
    mockStaff.mockReturnValue({
      data: [
        { public_id: 'st-1', kind: 'person', display_name: 'Pro', service_ids: ['a', 'b', 'c'] }
      ],
      isLoading: false
    })
    mockAvailability.mockReturnValue({ data: [slot], isLoading: false })
    mockCreateBooking.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
    forgetOtpVerification('tienda')
    forgetClientToken()
    window.sessionStorage.clear()
  })

  it('un solo servicio con adicionales muestra el paso; tocarlo abre el contador sin avanzar', async () => {
    mockServices.mockReturnValue({ data: [corteConStrass], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)

    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Adicionales de Servicio a' })).toBeNull()

    fireEvent.click(screen.getByText('Servicio a'))

    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Adicionales de Servicio a' })).toBeInTheDocument()
    expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
      `1 servicio · 30 min · ${formatCurrency(1000)}`
    )
    agregar('Strass')
    agregar('Strass')
    expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
      `1 servicio · 30 min · ${formatCurrency(2000)}`
    )

    continuar()
    expect(screen.getByText(HORARIO)).toBeInTheDocument()
    const pedido = await reservar()
    expect(pedido).toMatchObject({ service_id: 'a', addons: [{ addon_id: 'strass', quantity: 2 }] })
  })

  it('sin el flag, un servicio sin adicionales sigue eligiendo y avanzando', () => {
    mockServices.mockReturnValue({ data: [corteConStrass, servicio('c')], isLoading: false })
    render(<WizardEnRuta store={tienda(false)} />)

    fireEvent.click(screen.getByText('Servicio a'))
    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Servicio c'))

    expect(screen.getByText(HORARIO)).toBeInTheDocument()
  })

  it('con varios servicios cada uno lleva sus adicionales al pedido', async () => {
    mockServices.mockReturnValue({ data: [corteConStrass, barbaConBrillo], isLoading: false })
    render(<WizardEnRuta store={tiendaMulti()} />)

    fireEvent.click(screen.getByText('Servicio a'))
    fireEvent.click(screen.getByText('Servicio b'))
    agregar('Strass')
    agregar('Brillo')
    agregar('Brillo')
    // 1000 + 1000 + 500 + 2 x 300
    expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
      `2 servicios · 60 min · ${formatCurrency(3100)}`
    )
    continuar()

    const pedido = await reservar()
    expect(pedido).toMatchObject({
      service_id: 'a',
      extra_service_ids: ['b'],
      addons: [
        { addon_id: 'strass', quantity: 1 },
        { addon_id: 'brillo', quantity: 2 }
      ]
    })
  })

  it('quitar un servicio se lleva sus adicionales', async () => {
    mockServices.mockReturnValue({ data: [corteConStrass, barbaConBrillo], isLoading: false })
    render(<WizardEnRuta store={tiendaMulti()} />)

    fireEvent.click(screen.getByText('Servicio a'))
    fireEvent.click(screen.getByText('Servicio b'))
    agregar('Strass')
    agregar('Brillo')
    fireEvent.click(screen.getByText('Servicio b'))

    expect(screen.queryByRole('region', { name: 'Adicionales de Servicio b' })).toBeNull()
    expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
      `1 servicio · 30 min · ${formatCurrency(1500)}`
    )
    continuar()
    const pedido = await reservar()
    expect(pedido).not.toHaveProperty('extra_service_ids')
    expect(pedido.addons).toEqual([{ addon_id: 'strass', quantity: 1 }])
  })

  it('un deep-link a un servicio con adicionales arranca en el horario y "Volver" los ofrece', () => {
    mockServices.mockReturnValue({ data: [corteConStrass], isLoading: false })
    render(
      <WizardEnRuta
        store={tienda(false)}
        preselect={{ serviceId: 'a', staffId: null, date: null }}
      />
    )
    expect(screen.getByText(HORARIO)).toBeInTheDocument()

    fireEvent.click(volver())

    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Adicionales de Servicio a' })).toBeInTheDocument()
  })

  // La promo se mide contra el total: con otros adicionales el codigo aplicado
  // se conserva y se vuelve a validar contra la seleccion nueva al llegar a la
  // confirmacion (antes se borraba en silencio).
  it('cambiar los adicionales en el servicio conserva el codigo y lo revalida con los nuevos', async () => {
    mockServices.mockReturnValue({ data: [corteConStrass], isLoading: false })
    mockPreviewPromotion.mockResolvedValue({
      code: 'BIENVENIDA10',
      title: 'Bienvenida',
      promotion_type: 'percent',
      base_amount: 1000,
      discount_amount: 100,
      final_amount: 900
    })
    render(<WizardEnRuta store={tienda(false)} />)
    fireEvent.click(screen.getByText('Servicio a'))
    continuar()
    fireEvent.click(screen.getByText('09:00'))
    fireEvent.click(screen.getByText('¿Tenés un código de descuento?'))
    fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
      target: { value: 'bienvenida10' }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))
    })
    await waitFor(() => expect(mockPreviewPromotion).toHaveBeenCalled())

    atrasDelNavegador()
    atrasDelNavegador()
    agregar('Strass')
    continuar()
    mockPreviewPromotion.mockClear()
    const pedido = await reservar()

    expect(mockPreviewPromotion).toHaveBeenCalledTimes(1)
    expect(mockPreviewPromotion.mock.calls[0][0]).toEqual(
      expect.objectContaining({ code: 'BIENVENIDA10', addons: ['strass:1'] })
    )
    expect(pedido.promotion_code).toBe('BIENVENIDA10')
    expect(pedido.addons).toEqual([{ addon_id: 'strass', quantity: 1 }])
  })
})

// S3 (2026-10-21, Mateo): "recorda que esto era personalizable por tienda y se
// elegia en produccion". El color de la tienda se fija una vez en la raiz del
// wizard y los pasos leen var(--brand-*).
describe('BookingWizardContainer con el color de la tienda', () => {
  const raiz = () =>
    screen.getByRole('region', { name: 'Paso 1 de 3: Servicio' }).parentElement as HTMLElement
  const variables = (element: HTMLElement) =>
    Object.fromEntries(
      ['--brand-fill', '--brand-fill-bottom', '--brand-on-fill', '--brand-ink'].map((name) => [
        name,
        element.style.getPropertyValue(name)
      ])
    )

  beforeEach(() => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    mockStaff.mockReturnValue({ data: [], isLoading: false })
    mockAvailability.mockReturnValue({ data: [slot], isLoading: false })
  })

  it('expone el color elegido por la tienda como variables en la raiz', () => {
    render(<WizardEnRuta store={{ ...tienda(false), primary_color: '#3B82F6' }} />)

    expect(variables(raiz())).toEqual(brandCssVariables(resolveBrandTheme('#3b82f6')))
    expect(raiz().style.getPropertyValue('--brand-fill')).toBe('#3b82f6')
  })

  it.each(['#000000', '#000', '', undefined])(
    'sin color elegido (%s) queda el naranja de Shifty',
    (primary_color) => {
      render(<WizardEnRuta store={{ ...tienda(false), primary_color: primary_color as string }} />)

      expect(variables(raiz())).toEqual({
        '--brand-fill': colors2000s.orange.cta,
        '--brand-fill-bottom': colors2000s.orange.dark,
        '--brand-on-fill': colors2000s.text.onOrangeSelection,
        '--brand-ink': colors2000s.orange.accent
      })
    }
  )

  it('el paso actual del indicador usa el color de marca', () => {
    render(<WizardEnRuta store={{ ...tienda(false), primary_color: '#3b82f6' }} />)

    const actual = screen.getByRole('listitem', { current: 'step' })
    const circulo = actual.querySelector('div') as HTMLElement
    expect(circulo.getAttribute('style')).toContain('var(--brand-fill,')
    expect(circulo.getAttribute('style')).toContain('var(--brand-on-fill,')
    expect(actual.querySelector('span')?.getAttribute('style')).toContain('var(--brand-ink,')
  })
})
