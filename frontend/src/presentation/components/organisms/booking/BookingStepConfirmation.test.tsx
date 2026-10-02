import React from 'react'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { ConflictError, ValidationError } from '@shared/errors'

import { BookingStepConfirmation } from './BookingStepConfirmation'
import type { BookingClientData, BookingOtpState, BookingWizardState } from './types'

const mockDepositPreview = jest.fn()
const mockPreviewPromotion = jest.fn()
const mockServices = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicDepositPreview: (...args: unknown[]) => mockDepositPreview(...args),
  usePreviewPublicPromotion: () => ({ mutateAsync: mockPreviewPromotion, isPending: false }),
  usePublicServices: (...args: unknown[]) => mockServices(...args)
}))

const cliente = (patch: Partial<BookingClientData> = {}): BookingClientData => ({
  name: '',
  email: '',
  phone: '',
  notes: '',
  customFields: {},
  ...patch
})

const estado = (patch: Partial<BookingWizardState> = {}): BookingWizardState => ({
  serviceId: 'svc-1',
  requestedStaffId: null,
  assignedStaffId: 'st-1',
  date: '2026-09-25',
  startTime: '09:00',
  startsAt: '2026-09-25T12:00:00+00:00',
  client: cliente(),
  promotionCode: '',
  ...patch
})

const otpInicial = (patch: Partial<BookingOtpState> = {}): BookingOtpState => ({
  code: '',
  channel: 'email',
  email: '',
  verified: false,
  verifiedPhone: '',
  expiresAt: '',
  error: '',
  rateLimited: false,
  debugCode: '',
  ...patch
})

const confirmacion = (patch: Partial<BookingConfirmation> = {}): BookingConfirmation => ({
  public_id: 'apt-1',
  service_id: 'svc-1',
  service_name: 'Corte',
  staff_id: 'st-1',
  staff_name: 'Pro',
  starts_at: '2026-09-25T12:00:00+00:00',
  ends_at: '2026-09-25T12:30:00+00:00',
  status: 'confirmed',
  client_name: 'Lucia',
  client_phone: '1155550101',
  payment_required: false,
  ...patch
})

type Props = React.ComponentProps<typeof BookingStepConfirmation>

const props = (patch: Partial<Props> = {}): Props => ({
  storePublicId: 'store-1',
  serviceId: 'svc-1',
  paymentsEnabled: false,
  storeName: 'Tienda',
  storeSlug: 'tienda',
  whatsappNumber: null,
  depositPolicy: null,
  allowManualCoordination: true,
  bookingState: estado(),
  customFields: [],
  requiresOtp: false,
  otpState: otpInicial(),
  isRequestingOtp: false,
  otpResendSeconds: 0,
  isVerifyingOtp: false,
  onRequestOtp: jest.fn(),
  onVerifyOtp: jest.fn(),
  onOtpEmailChange: jest.fn(),
  onOtpCodeChange: jest.fn(),
  onBack: jest.fn(),
  onClientChange: jest.fn(),
  onPromotionCodeChange: jest.fn(),
  onConfirm: jest.fn().mockResolvedValue(confirmacion()),
  ...patch
})

/** Duenio del estado como el wizard: lo que el paso cambia vuelve como prop. */
const ConEstado: React.FC<{ base: Props }> = ({ base }) => {
  const [bookingState, setBookingState] = React.useState(base.bookingState)
  return (
    <BookingStepConfirmation
      {...base}
      bookingState={bookingState}
      onClientChange={(client) => setBookingState((prev) => ({ ...prev, client }))}
      onPromotionCodeChange={(promotionCode) =>
        setBookingState((prev) => ({ ...prev, promotionCode }))
      }
    />
  )
}

const RESERVAR = 'Reservar y pagar por WhatsApp'
const PAGAR_MP = 'Pagar seña con Mercado Pago'
const aceptarTerminos = () => fireEvent.click(screen.getByRole('checkbox'))
const botonReservar = () => screen.getByRole('button', { name: RESERVAR })

describe('BookingStepConfirmation', () => {
  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockPreviewPromotion.mockReset()
    mockServices.mockReset()
    mockDepositPreview.mockReturnValue({ data: undefined, isLoading: false })
    mockServices.mockReturnValue({ data: [], isLoading: false })
  })

  describe('formulario', () => {
    it('muestra fecha y hora del turno elegido y los campos del cliente', () => {
      render(<BookingStepConfirmation {...props()} />)

      expect(screen.getByText('Tus datos y confirmación')).toBeInTheDocument()
      // 2026-10-02, QA en navegador: el resumen mostraba la fecha ISO.
      expect(screen.getByText('25/09/2026')).toBeInTheDocument()
      expect(screen.queryByText('2026-09-25')).not.toBeInTheDocument()
      expect(screen.getByText('09:00 hs')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Ej: Juan Perez')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('PREFIJO + NUM')).toBeInTheDocument()
    })

    it('reservar queda deshabilitado hasta tener nombre, telefono y terminos', () => {
      const { rerender } = render(<BookingStepConfirmation {...props()} />)
      aceptarTerminos()
      expect(botonReservar()).toBeDisabled()

      rerender(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({ client: cliente({ name: 'Lucia', phone: '1155550101' }) })
          })}
        />
      )
      expect(botonReservar()).not.toBeDisabled()
    })

    // 2026-10-02, QA en navegador (S\05): con el telefono "123" el boton
    // quedaba habilitado, el backend respondia 422 en client_phone y la
    // pantalla decia "El horario podria estar ocupado".
    it('un telefono con menos de 6 digitos bloquea la reserva y lo dice junto al campo', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({ client: cliente({ name: 'Lucia', phone: '123' }) })
          })}
        />
      )
      aceptarTerminos()

      expect(botonReservar()).toBeDisabled()
      expect(screen.getByText(/al menos 6 dígitos/)).toBeInTheDocument()
    })

    it('un 422 en client_phone dice que revise el telefono, no que el horario esta ocupado', async () => {
      const onConfirm = jest.fn().mockRejectedValue(
        new ValidationError(
          'client_phone: Value error, El teléfono debe tener al menos 6 digitos',
          {
            errorCode: 'VALIDATION_ERROR',
            statusCode: 422,
            detail: ['client_phone: Value error, El teléfono debe tener al menos 6 digitos']
          }
        )
      )
      render(
        <BookingStepConfirmation
          {...props({
            onConfirm,
            bookingState: estado({ client: cliente({ name: 'Lucia', phone: '1155550101' }) })
          })}
        />
      )
      aceptarTerminos()
      fireEvent.click(botonReservar())

      const aviso = (await screen.findByText(/Revisá el teléfono/)).closest('[role="alert"]')
      expect(aviso).toHaveTextContent(/al menos 6 dígitos/)
      expect(aviso).not.toHaveTextContent(/ocupado/)
    })

    it('un campo personalizado obligatorio vacio bloquea la reserva', () => {
      render(
        <BookingStepConfirmation
          {...props({
            customFields: [{ key: 'dni', label: 'DNI', type: 'text', required: true, options: [] }],
            bookingState: estado({
              client: cliente({ name: 'Lucia', phone: '1155550101', customFields: { dni: '' } })
            })
          })}
        />
      )
      aceptarTerminos()
      expect(screen.getByText('DNI *')).toBeInTheDocument()
      expect(botonReservar()).toBeDisabled()
    })

    it('cada campo edita el cliente del wizard', () => {
      const onClientChange = jest.fn()
      render(<BookingStepConfirmation {...props({ onClientChange })} />)

      fireEvent.change(screen.getByPlaceholderText('Ej: Juan Perez'), {
        target: { value: 'Lucia' }
      })
      expect(onClientChange).toHaveBeenLastCalledWith(expect.objectContaining({ name: 'Lucia' }))
    })
  })

  describe('vista previa de la seña', () => {
    it('muestra la seña que calcula el backend y ofrece pagarla online', () => {
      mockDepositPreview.mockReturnValue({
        isLoading: false,
        data: {
          amount: 1500,
          base_amount: 1500,
          extra_percent: 0,
          reasons: [],
          price: 5000,
          payments_enabled: true,
          online_payment_mandatory: false
        }
      })
      render(<BookingStepConfirmation {...props({ paymentsEnabled: true })} />)

      expect(screen.getByTestId('deposit-preview')).toHaveTextContent(/1\.500/)
      expect(screen.getByRole('button', { name: PAGAR_MP })).toBeInTheDocument()
      expect(botonReservar()).toBeInTheDocument()
    })

    it('con pago online obligatorio no ofrece coordinar por WhatsApp', () => {
      mockDepositPreview.mockReturnValue({
        isLoading: false,
        data: {
          amount: 1500,
          base_amount: 1500,
          extra_percent: 0,
          reasons: [],
          price: 5000,
          payments_enabled: true,
          online_payment_mandatory: true
        }
      })
      render(<BookingStepConfirmation {...props({ paymentsEnabled: true })} />)

      expect(screen.getByRole('button', { name: PAGAR_MP })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: RESERVAR })).not.toBeInTheDocument()
    })

    it('sin seña no muestra el recuadro ni el pago online', () => {
      render(<BookingStepConfirmation {...props({ paymentsEnabled: true })} />)

      expect(screen.queryByTestId('deposit-preview')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: PAGAR_MP })).not.toBeInTheDocument()
    })

    it('consulta la seña con el turno, el telefono y el codigo aplicado', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({
              client: cliente({ phone: '1155550101' }),
              promotionCode: 'BIENVENIDA10'
            })
          })}
        />
      )

      expect(mockDepositPreview).toHaveBeenLastCalledWith({
        storePublicId: 'store-1',
        serviceId: 'svc-1',
        startsAt: '2026-09-25T12:00:00+00:00',
        clientPhone: '1155550101',
        promotionCode: 'BIENVENIDA10'
      })
    })

    describe('con un telefono a medio tipear', () => {
      // F11a-05 (2026-09-24): cada tecla cambiaba la queryKey y con menos de 6
      // caracteres el backend responde 422 (client_phone min_length=6), con
      // reintento y paso por el manejador global de errores.
      // F4-06 (2026-09-30): aun dentro del rango habia una request por tecla
      // desde el sexto caracter; el telefono viaja con 8 digitos o mas y
      // despues de 400 ms sin tipear.
      beforeEach(() => jest.useFakeTimers())
      afterEach(() => jest.useRealTimers())

      const conTelefono = (phone: string) => (
        <BookingStepConfirmation
          {...props({ bookingState: estado({ client: cliente({ phone }) }) })}
        />
      )
      const ultimoTelefono = () => mockDepositPreview.mock.lastCall?.[0]?.clientPhone

      it('con menos de 8 digitos o mas de 30 caracteres consulta la seña sin telefono', () => {
        const { rerender } = render(conTelefono('11555'))
        expect(ultimoTelefono()).toBeUndefined()

        // 6 digitos: antes viajaba, ahora no.
        rerender(conTelefono(' 115555 '))
        act(() => {
          jest.advanceTimersByTime(400)
        })
        expect(ultimoTelefono()).toBeUndefined()

        rerender(conTelefono('1155555'))
        act(() => {
          jest.advanceTimersByTime(400)
        })
        expect(ultimoTelefono()).toBeUndefined()

        rerender(conTelefono('1'.repeat(31)))
        act(() => {
          jest.advanceTimersByTime(400)
        })
        expect(ultimoTelefono()).toBeUndefined()
      })

      it('con 8 digitos o mas manda el telefono despues de 400 ms sin tipear', () => {
        const { rerender } = render(conTelefono('115'))

        rerender(conTelefono(' 11555501 '))
        expect(ultimoTelefono()).toBeUndefined()
        act(() => {
          jest.advanceTimersByTime(399)
        })
        expect(ultimoTelefono()).toBeUndefined()
        act(() => {
          jest.advanceTimersByTime(1)
        })
        expect(ultimoTelefono()).toBe('11555501')

        // Una tecla mas reinicia la espera: sigue el telefono anterior.
        rerender(conTelefono('115555010'))
        expect(ultimoTelefono()).toBe('11555501')
        act(() => {
          jest.advanceTimersByTime(400)
        })
        expect(ultimoTelefono()).toBe('115555010')
      })
    })
  })

  describe('codigo promocional', () => {
    it('aplicar valida el codigo en mayusculas, muestra el descuento y lo guarda en el wizard', async () => {
      mockPreviewPromotion.mockResolvedValue({
        code: 'BIENVENIDA10',
        title: 'Bienvenida',
        promotion_type: 'percent',
        base_amount: 5000,
        discount_amount: 500,
        final_amount: 4500
      })
      const onPromotionCodeChange = jest.fn()
      render(<BookingStepConfirmation {...props({ onPromotionCodeChange })} />)

      fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
        target: { value: ' bienvenida10 ' }
      })
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      await waitFor(() => expect(screen.getByText('Bienvenida')).toBeInTheDocument())
      expect(mockPreviewPromotion).toHaveBeenCalledWith({
        storePublicId: 'store-1',
        serviceId: 'svc-1',
        code: 'BIENVENIDA10'
      })
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith('BIENVENIDA10')
    })

    it('un codigo rechazado muestra el motivo y no queda aplicado', async () => {
      mockPreviewPromotion.mockRejectedValue(
        new ValidationError('El código vencio', { statusCode: 400 })
      )
      const onPromotionCodeChange = jest.fn()
      render(<BookingStepConfirmation {...props({ onPromotionCodeChange })} />)

      fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
        target: { value: 'VIEJO' }
      })
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      await waitFor(() => expect(screen.getByText('El código vencio')).toBeInTheDocument())
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith('')
    })

    it('editar un codigo ya aplicado conserva lo que se tipea', async () => {
      // F11a-04 (2026-09-24): un efecto copiaba el codigo del wizard al input;
      // al tipear despues de aplicar, el wizard lo limpiaba y el efecto pisaba
      // el campo con '' a la primera tecla.
      mockPreviewPromotion.mockResolvedValue({
        code: 'BIENVENIDA10',
        title: 'Bienvenida',
        promotion_type: 'percent',
        base_amount: 5000,
        discount_amount: 500,
        final_amount: 4500
      })
      render(<ConEstado base={props()} />)
      const campo = screen.getByPlaceholderText('Ej: BIENVENIDA10') as HTMLInputElement

      fireEvent.change(campo, { target: { value: 'bienvenida10' } })
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))
      await waitFor(() => expect(screen.getByText('Bienvenida')).toBeInTheDocument())
      expect(campo.value).toBe('BIENVENIDA10')

      fireEvent.change(campo, { target: { value: 'BIENVENIDA1' } })

      expect(campo.value).toBe('BIENVENIDA1')
      expect(screen.queryByText('Bienvenida')).not.toBeInTheDocument()
    })

    it('aplicar con el campo vacio no consulta y limpia el codigo', () => {
      const onPromotionCodeChange = jest.fn()
      render(<BookingStepConfirmation {...props({ onPromotionCodeChange })} />)

      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      expect(mockPreviewPromotion).not.toHaveBeenCalled()
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith('')
    })
  })

  describe('verificacion por OTP', () => {
    it('sin telefono completo pide completarlo antes de verificar', () => {
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            bookingState: estado({ client: cliente({ phone: '11' }) })
          })}
        />
      )

      expect(
        screen.getByText('Completá tu teléfono para verificarlo antes de confirmar.')
      ).toBeInTheDocument()
      expect(screen.queryByText('Verificamos tu teléfono')).not.toBeInTheDocument()
    })

    it('con telefono completo muestra el pedido del codigo por email', () => {
      const onRequestOtp = jest.fn()
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            onRequestOtp,
            otpState: otpInicial({ email: 'lucia@example.com' }),
            bookingState: estado({ client: cliente({ phone: '1155550101' }) })
          })}
        />
      )

      expect(screen.getByText('Verificamos tu teléfono')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Verificar código' })).toBeDisabled()
      fireEvent.click(screen.getByRole('button', { name: 'Enviar código' }))
      expect(onRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('sin verificar, reservar queda cerrado aunque el resto este completo', () => {
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            bookingState: estado({ client: cliente({ name: 'Lucia', phone: '1155550101' }) })
          })}
        />
      )
      aceptarTerminos()

      expect(botonReservar()).toBeDisabled()
    })

    it('verificado, muestra el telefono validado y habilita la reserva', () => {
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            otpState: otpInicial({ verified: true, verifiedPhone: '+1155550101' }),
            bookingState: estado({ client: cliente({ name: 'Lucia', phone: '1155550101' }) })
          })}
        />
      )
      aceptarTerminos()

      expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
      expect(botonReservar()).not.toBeDisabled()
    })
  })

  describe('en el celular (F4-11)', () => {
    // 2026-09-30, F4-11: en el celular el codigo abria el teclado de letras,
    // no se ofrecia desde el mail y aceptaba cualquier largo; nombre, email y
    // telefono no se autocompletaban.
    it('nombre, email y telefono se autocompletan', () => {
      render(<BookingStepConfirmation {...props()} />)

      expect(screen.getByPlaceholderText('Ej: Juan Perez')).toHaveAttribute('autocomplete', 'name')
      expect(screen.getByPlaceholderText('juan@email.com')).toHaveAttribute('autocomplete', 'email')
      expect(screen.getByPlaceholderText('PREFIJO + NUM')).toHaveAttribute('autocomplete', 'tel')
    })

    it('el codigo usa teclado numerico, autocompletado de codigo y 6 digitos', () => {
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            bookingState: estado({ client: cliente({ phone: '1155550101' }) })
          })}
        />
      )

      const codigo = screen.getByPlaceholderText('Código que te llegó por email')
      expect(codigo).toHaveAttribute('inputmode', 'numeric')
      expect(codigo).toHaveAttribute('autocomplete', 'one-time-code')
      expect(codigo).toHaveAttribute('maxlength', '6')
      expect(screen.getByLabelText('Email para el código')).toHaveAttribute('autocomplete', 'email')
    })

    it('el codigo descarta lo que no es un digito', () => {
      // 2026-09-30, F4-11: inputMode numeric no impide tipear letras o guiones
      // en un teclado fisico y el backend rechazaba el codigo como invalido.
      const onOtpCodeChange = jest.fn()
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            onOtpCodeChange,
            bookingState: estado({ client: cliente({ phone: '1155550101' }) })
          })}
        />
      )

      fireEvent.change(screen.getByPlaceholderText('Código que te llegó por email'), {
        target: { value: '12a-3 4' }
      })

      expect(onOtpCodeChange).toHaveBeenLastCalledWith('1234')
    })

    it('durante la espera el boton muestra los segundos y no pide', () => {
      const onRequestOtp = jest.fn()
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            onRequestOtp,
            otpResendSeconds: 42,
            otpState: otpInicial({ email: 'lucia@example.com' }),
            bookingState: estado({ client: cliente({ phone: '1155550101' }) })
          })}
        />
      )

      const boton = screen.getByRole('button', { name: 'Reenviar en 42 s' })
      expect(boton).toBeDisabled()
      fireEvent.click(boton)
      expect(onRequestOtp).not.toHaveBeenCalled()
    })

    it('con OTP_RATE_LIMITED no deja pedir otro codigo y muestra el aviso', () => {
      // 2026-09-30, F4-11: agotados los codigos del telefono, el boton seguia
      // habilitado y cada toque volvia a chocar contra el limite.
      const aviso =
        'Pediste demasiados códigos para este teléfono. Esperá un rato antes de pedir otro.'
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            otpState: otpInicial({ email: 'lucia@example.com', rateLimited: true, error: aviso }),
            bookingState: estado({ client: cliente({ phone: '1155550101' }) })
          })}
        />
      )

      expect(screen.getByRole('button', { name: 'Enviar código' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(aviso)
    })
  })

  describe('confirmar', () => {
    const completo = () =>
      props({
        bookingState: estado({
          client: cliente({ name: 'Lucia', phone: '1155550101', email: 'lucia@example.com' })
        })
      })

    it('reserva por WhatsApp y muestra la pantalla de reserva confirmada', async () => {
      const base = completo()
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText('Reserva Confirmada')).toBeInTheDocument())
      expect(base.onConfirm).toHaveBeenCalledWith('manual', true)
      expect(screen.getByText('Te enviamos los detalles a lucia@example.com')).toBeInTheDocument()
    })

    it('una reserva pendiente de revision se anuncia como registrada', async () => {
      const base = completo()
      base.onConfirm = jest.fn().mockResolvedValue(confirmacion({ status: 'pending' }))
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText('Reserva Registrada')).toBeInTheDocument())
    })

    it('una reserva con pago pendiente se anuncia como pendiente de pago', async () => {
      const base = completo()
      base.onConfirm = jest
        .fn()
        .mockResolvedValue(confirmacion({ status: 'pending_payment', payment_required: true }))
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText('Reserva Pendiente de Pago')).toBeInTheDocument())
      expect(
        screen.getByText('Tu turno se confirma cuando el cobro quede aprobado.')
      ).toBeInTheDocument()
    })

    it('si la reserva falla vuelve al formulario con el aviso de horario ocupado', async () => {
      const base = completo()
      base.onConfirm = jest
        .fn()
        .mockRejectedValue(new ConflictError('Horario ocupado', { statusCode: 409 }))
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText('Horario ocupado')).toBeInTheDocument())
      expect(
        screen.getByText(/El horario podria haberse ocupado mientras completabas el formulario/)
      ).toBeInTheDocument()
    })

    it('un 400 BOOKING_NOTICE_REQUIRED muestra el texto del servidor con las horas de anticipacion', async () => {
      // FF-06 (2026-10-01): un texto neutro global para BOOKING_NOTICE_REQUIRED
      // pisaba el del servidor y el cliente dejaba de ver cuantas horas de
      // anticipacion pide la tienda.
      const aviso = 'Este local requiere 24h de anticipación para agendar/reprogramar.'
      const base = completo()
      base.onConfirm = jest
        .fn()
        .mockRejectedValue(
          new ValidationError(aviso, { errorCode: 'BOOKING_NOTICE_REQUIRED', statusCode: 400 })
        )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText(aviso)).toBeInTheDocument())
    })

    it('un doble click envia la reserva una sola vez', async () => {
      const base = completo()
      let resolver: (value: BookingConfirmation) => void = () => undefined
      base.onConfirm = jest.fn(
        () =>
          new Promise<BookingConfirmation>((resolve) => {
            resolver = resolve
          })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      const boton = botonReservar()
      fireEvent.click(boton)
      fireEvent.click(boton)

      expect(base.onConfirm).toHaveBeenCalledTimes(1)
      resolver(confirmacion())
      await waitFor(() => expect(screen.getByText('Reserva Confirmada')).toBeInTheDocument())
    })
  })
})
