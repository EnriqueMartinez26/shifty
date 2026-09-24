import React from 'react'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

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
  idempotencyKey: 'idem-1',
  ...patch
})

const otpInicial = (patch: Partial<BookingOtpState> = {}): BookingOtpState => ({
  code: '',
  channel: 'email',
  email: '',
  verified: false,
  verifiedPhone: '',
  debugCode: '',
  expiresAt: '',
  error: '',
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

      expect(screen.getByText('Tus datos y confirmacion')).toBeInTheDocument()
      expect(screen.getByText('2026-09-25')).toBeInTheDocument()
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
      mockPreviewPromotion.mockRejectedValue(new Error('El codigo vencio'))
      const onPromotionCodeChange = jest.fn()
      render(<BookingStepConfirmation {...props({ onPromotionCodeChange })} />)

      fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
        target: { value: 'VIEJO' }
      })
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      await waitFor(() => expect(screen.getByText('El codigo vencio')).toBeInTheDocument())
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith('')
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
        screen.getByText('Completa tu telefono para verificarlo antes de confirmar.')
      ).toBeInTheDocument()
      expect(screen.queryByText('Verificamos tu telefono')).not.toBeInTheDocument()
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

      expect(screen.getByText('Verificamos tu telefono')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Verificar codigo' })).toBeDisabled()
      fireEvent.click(screen.getByRole('button', { name: 'Enviar codigo' }))
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

      expect(screen.getByText('Telefono validado correctamente')).toBeInTheDocument()
      expect(botonReservar()).not.toBeDisabled()
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
      base.onConfirm = jest.fn().mockRejectedValue(new Error('Horario ocupado'))
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText('Horario ocupado')).toBeInTheDocument())
      expect(
        screen.getByText(/El horario podria haberse ocupado mientras completabas el formulario/)
      ).toBeInTheDocument()
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
