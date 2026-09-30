import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { RateLimitError } from '@shared/errors'

import { BookingWizardContainer } from './BookingWizardContainer'
import type { PublicStore } from '../../../hooks/usePublic'

const mockServices = jest.fn()
const mockStaff = jest.fn()
const mockAvailability = jest.fn()
const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()

jest.mock('../../../hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockServices(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicDepositPreview: () => ({ data: undefined, isLoading: false }),
  usePreviewPublicPromotion: () => ({ mutateAsync: jest.fn(), isPending: false }),
  useJoinWaitlist: () => ({ mutateAsync: jest.fn(), isPending: false, isSuccess: false }),
  useCreatePublicBooking: () => ({ mutateAsync: jest.fn(), isPending: false }),
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

const HORARIO = 'Elegi fecha y hora'
const SERVICIO = '¿Qué servicio necesitás?'

describe('BookingWizardContainer', () => {
  beforeEach(() => {
    mockServices.mockReset()
    mockStaff.mockReset()
    mockAvailability.mockReset()
    mockRequestOtp.mockReset()
    mockVerifyOtp.mockReset()
    mockStaff.mockReturnValue({ data: [], isLoading: false })
    mockAvailability.mockReturnValue({ data: [slot], isLoading: false })
    window.sessionStorage.clear()
  })

  it('con un servicio valido en la URL arranca en el horario', () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    render(
      <BookingWizardContainer
        store={tienda(false)}
        preselect={{ serviceId: 'a', staffId: 'st-1', date: null }}
      />
    )
    expect(screen.getByText(HORARIO)).toBeInTheDocument()
    expect(screen.queryByText(SERVICIO)).not.toBeInTheDocument()
  })

  it('con un solo servicio lo elige solo y salta al horario; "atras" no vuelve al servicio', async () => {
    mockServices.mockReturnValue({ data: [servicio('unico')], isLoading: false })
    render(<BookingWizardContainer store={tienda(false)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'unico', expect.any(String), false)

    // El primer boton del paso es el de "atras" (chevron).
    fireEvent.click(screen.getAllByRole('button')[0] as HTMLElement)
    expect(screen.getByText(HORARIO)).toBeInTheDocument()
    expect(screen.queryByText(SERVICIO)).not.toBeInTheDocument()
  })

  it('con varios servicios arranca eligiendo el servicio', () => {
    mockServices.mockReturnValue({ data: [servicio('a'), servicio('b')], isLoading: false })
    render(<BookingWizardContainer store={tienda(false)} />)
    expect(screen.getByText(SERVICIO)).toBeInTheDocument()
  })

  it('el codigo OTP se pide por email, al email que escribe el cliente', async () => {
    mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
    mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '2026-09-25T13:00:00Z' })
    render(<BookingWizardContainer store={tienda(true)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))

    fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
      target: { value: 'lucia@example.com' }
    })
    fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
      target: { value: '+5491155550101' }
    })
    // El email del codigo arranca con el del formulario.
    expect((screen.getByLabelText('Email para el codigo') as HTMLInputElement).value).toBe(
      'lucia@example.com'
    )
    fireEvent.click(screen.getByText('Enviar codigo'))

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
    render(<BookingWizardContainer store={tienda(true)} />)

    await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
    fireEvent.click(screen.getByText('09:00'))
    fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
      target: { value: '+5491155550101' }
    })

    expect(screen.getByText('Telefono validado correctamente')).toBeInTheDocument()
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
      render(<BookingWizardContainer store={tienda(true)} />)

      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '54 9 11 5555-0101' }
      })
      fireEvent.change(screen.getByPlaceholderText('Codigo que te llego por email'), {
        target: { value: '123456' }
      })
      fireEvent.click(screen.getByText('Verificar codigo'))
      await waitFor(() =>
        expect(screen.getByText('Telefono validado correctamente')).toBeInTheDocument()
      )

      fireEvent.change(screen.getByPlaceholderText('Algo que debamos saber?'), {
        target: { value: 'Llego 5 minutos tarde' }
      })

      expect(screen.getByText('Telefono validado correctamente')).toBeInTheDocument()

      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '54 9 11 5555-0102' }
      })
      expect(screen.queryByText('Telefono validado correctamente')).not.toBeInTheDocument()
    } finally {
      getItem.mockRestore()
      setItem.mockRestore()
    }
  })

  describe('pedir el codigo desde el celular (F4-11, J7)', () => {
    // 2026-09-30, F4-11: sin espera para reenviar, cada toque de "Enviar
    // codigo" mientras el mail tardaba gastaba uno de los 5 pedidos por hora
    // (OTP_MAX_REQUESTS_PER_HOUR) y el cliente quedaba bloqueado una hora.
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    const hastaPedirElCodigo = async () => {
      mockServices.mockReturnValue({ data: [servicio('a')], isLoading: false })
      render(<BookingWizardContainer store={tienda(true)} />)
      await waitFor(() => expect(screen.getByText(HORARIO)).toBeInTheDocument())
      fireEvent.click(screen.getByText('09:00'))
      fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
        target: { value: 'lucia@example.com' }
      })
      fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
        target: { value: '+5491155550101' }
      })
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Enviar codigo' }))
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
      expect(screen.getByRole('button', { name: 'Enviar codigo' })).not.toBeDisabled()
      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('un pedido fallido sin Retry-After no arranca la espera', async () => {
      mockRequestOtp.mockRejectedValue(new Error('Demasiados pedidos'))
      await hastaPedirElCodigo()

      expect(screen.getByRole('button', { name: 'Enviar codigo' })).not.toBeDisabled()
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
      expect(screen.getByRole('button', { name: 'Enviar codigo' })).not.toBeDisabled()
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
      expect(screen.getByRole('button', { name: 'Enviar codigo' })).toBeDisabled()
      expect(screen.queryByText(/Reenviar en/)).not.toBeInTheDocument()

      act(() => {
        jest.advanceTimersByTime(10 * 60_000)
      })
      fireEvent.change(screen.getByLabelText('Email para el codigo'), {
        target: { value: 'otra@example.com' }
      })
      expect(screen.getByRole('button', { name: 'Enviar codigo' })).toBeDisabled()
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

      expect(screen.getByRole('button', { name: 'Enviar codigo' })).not.toBeDisabled()
    })

    it('no muestra el debug_code aunque la API lo devuelva', async () => {
      // 2026-09-30, J7: con OTP_DEBUG_EXPOSE_CODE el backend devuelve un
      // senuelo cuando el codigo fue a un buzon distinto del tipeado; la
      // pantalla lo mostraba como "Codigo debug" y no verificaba.
      mockRequestOtp.mockResolvedValue({
        ok: true,
        expires_at: '2026-09-30T13:00:00Z',
        debug_code: '424242'
      })
      await hastaPedirElCodigo()

      expect(mockRequestOtp).toHaveBeenCalledTimes(1)
      expect(screen.queryByText(/424242/)).not.toBeInTheDocument()
      expect(screen.queryByText(/Codigo debug/i)).not.toBeInTheDocument()
    })
  })
})
