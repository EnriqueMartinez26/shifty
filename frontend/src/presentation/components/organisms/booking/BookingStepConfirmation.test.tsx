import React from 'react'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import type {
  BookingConfirmation,
  PromotionPreview
} from '@application/services/PublicBookingService'

import { ConflictError, ServiceUnavailableError, ValidationError } from '@shared/errors'

import { BookingStepConfirmation } from './BookingStepConfirmation'
import type { BookingClientData, BookingOtpState, BookingWizardState } from './types'

const mockDepositPreview = jest.fn()
const mockPreviewPromotion = jest.fn()
const mockServices = jest.fn()
const mockRefreshServices = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicDepositPreview: (...args: unknown[]) => mockDepositPreview(...args),
  usePreviewPublicPromotion: () => ({ mutateAsync: mockPreviewPromotion, isPending: false }),
  usePublicServices: (...args: unknown[]) => mockServices(...args),
  useRefreshPublicServices: () => mockRefreshServices
}))

// El cliente de los tests trae email, salvo los que prueban su falta (opcional
// sin OTP, obligatorio con OTP; propuesta por Mateo, 2026-10-16).
const cliente = (patch: Partial<BookingClientData> = {}): BookingClientData => ({
  name: '',
  email: 'lucia@example.com',
  phone: '',
  notes: '',
  customFields: {},
  ...patch
})

const estado = (patch: Partial<BookingWizardState> = {}): BookingWizardState => ({
  serviceId: 'svc-1',
  extraServiceIds: [],
  requestedStaffId: null,
  assignedStaffId: 'st-1',
  assignedStaff: { name: 'Ana', isResource: false },
  date: '2026-09-25',
  startTime: '09:00',
  startsAt: '2026-09-25T12:00:00+00:00',
  client: cliente(),
  promotionCode: '',
  promotionPreview: null,
  addons: [],
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
  onAddonsChange: jest.fn(),
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
      onPromotionCodeChange={(promotionCode, promotionPreview) =>
        setBookingState((prev) => ({ ...prev, promotionCode, promotionPreview }))
      }
      onAddonsChange={(addons) => setBookingState((prev) => ({ ...prev, addons }))}
    />
  )
}

// Sin seña la reserva se confirma; con seña y coordinacion manual se paga por
// WhatsApp (QA movil 2026-10-08: decia "pagar por WhatsApp" sin seña).
const RESERVAR = 'Confirmar reserva'
const RESERVAR_CON_SENA = 'Reservar y pagar la seña por WhatsApp'
const PAGAR_MP = 'Pagar seña con Mercado Pago'
const aceptarTerminos = () => fireEvent.click(screen.getByRole('checkbox'))
const botonReservar = () => screen.getByRole('button', { name: RESERVAR })
// El codigo promocional va plegado detras de un link (2026-10-16).
const abrirCodigo = () =>
  fireEvent.click(screen.getByRole('button', { name: '¿Tenés un código de descuento?' }))

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
      expect(screen.getByPlaceholderText('Ej: 351 1234567')).toBeInTheDocument()
    })

    // 2026-10-16 (pedido de Mateo): "Tus datos y confirmación" y adentro otra
    // vez "Tus datos / Los necesitamos para registrar tu reserva." en el celular.
    it('el paso tiene un solo titulo y el bloque de datos sigue nombrado', () => {
      render(<BookingStepConfirmation {...props()} />)

      expect(screen.getAllByRole('heading')).toHaveLength(1)
      expect(screen.getByRole('heading', { name: 'Tus datos y confirmación' })).toBeInTheDocument()
      expect(
        screen.queryByText('Los necesitamos para registrar tu reserva.')
      ).not.toBeInTheDocument()
      const datos = screen.getByRole('region', { name: 'Tus datos' })
      expect(datos.contains(screen.getByLabelText('Nombre Completo'))).toBe(true)
      expect(datos.contains(screen.getByLabelText('Email (opcional)'))).toBe(true)
      expect(datos.contains(screen.getByLabelText('Teléfono'))).toBe(true)
    })

    // 2026-10-16 (pedido de Mateo): "atras" era un circulo con un chevron, sin
    // texto ni nombre accesible, y los clientes no lo encontraban.
    it('"Volver" es un boton con texto visible que vuelve al paso anterior', () => {
      const onBack = jest.fn()
      render(<BookingStepConfirmation {...props({ onBack })} />)

      const volver = screen.getByRole('button', { name: 'Volver' })
      expect(volver).toHaveTextContent('Volver')
      expect(volver).toHaveAttribute('type', 'button')
      fireEvent.click(volver)
      expect(onBack).toHaveBeenCalledTimes(1)
    })

    it('el telefono muestra un ejemplo y las notas dicen para quien son', () => {
      render(<BookingStepConfirmation {...props()} />)

      expect(screen.getByLabelText('Teléfono')).toHaveAttribute('placeholder', 'Ej: 351 1234567')
      expect(screen.getByLabelText('Notas para la tienda (opcional)')).toBeInTheDocument()
      expect(screen.queryByText(/PREFIJO/)).not.toBeInTheDocument()
      expect(screen.queryByText(/Notas Adicionales/)).not.toBeInTheDocument()
    })

    it('el ejemplo del telefono pasa la validacion de siempre', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({ client: cliente({ name: 'Lucia', phone: '351 1234567' }) })
          })}
        />
      )
      aceptarTerminos()

      expect(screen.getByLabelText('Teléfono')).toHaveAttribute('aria-invalid', 'false')
      expect(botonReservar()).not.toBeDisabled()
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
      // Sin seña, promo ni adicionales el importe no depende del backend: el
      // telefono nuevo no frena la reserva.
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
      expect(screen.queryByText(/El horario podria haberse ocupado/)).not.toBeInTheDocument()
    })

    // Propuesta por Mateo (2026-10-16): el email vuelve a ser opcional, salvo
    // con OTP (el codigo sale solo por email). El #181 lo habia hecho
    // obligatorio porque sin email no hay "Mis turnos"; ahora el campo lo dice.
    it('sin OTP el email es opcional, dice que se pierde y se puede reservar sin el', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({
              client: cliente({ name: 'Lucia', phone: '1155550101', email: '' })
            })
          })}
        />
      )
      aceptarTerminos()

      expect(botonReservar()).not.toBeDisabled()
      expect(screen.getByText('Email (opcional)')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('juan@email.com')).not.toHaveAttribute('required')
      expect(
        screen.getByText(
          'Opcional. Si no lo dejás, no vas a poder gestionar tu turno desde acá ni recibir avisos; para cambiarlo o cancelarlo escribile a la tienda por WhatsApp.'
        )
      ).toBeInTheDocument()
    })

    it('con OTP el email sigue obligatorio aunque el telefono este verificado', () => {
      render(
        <BookingStepConfirmation
          {...props({
            requiresOtp: true,
            otpState: otpInicial({ verified: true, verifiedPhone: '+1155550101' }),
            bookingState: estado({
              client: cliente({ name: 'Lucia', phone: '1155550101', email: '' })
            })
          })}
        />
      )
      aceptarTerminos()

      expect(botonReservar()).toBeDisabled()
      expect(screen.queryByText('Email (opcional)')).not.toBeInTheDocument()
      expect(screen.getByPlaceholderText('juan@email.com')).toHaveAttribute('required')
      expect(
        screen.getByText('Te enviamos la confirmación y el acceso a tus turnos.')
      ).toBeInTheDocument()
    })

    it('un email mal escrito bloquea la reserva y lo dice junto al campo', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({
              client: cliente({ name: 'Lucia', phone: '1155550101', email: 'lucia@' })
            })
          })}
        />
      )
      aceptarTerminos()

      expect(botonReservar()).toBeDisabled()
      expect(screen.getByPlaceholderText('juan@email.com')).toHaveAttribute('aria-invalid', 'true')
      expect(screen.getByText('Revisá el email: no parece válido.')).toBeInTheDocument()
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

  describe('resumen del turno', () => {
    const dato = (etiqueta: string) =>
      screen.getByText(etiqueta, { selector: 'dt' }).nextElementSibling?.textContent

    it('muestra servicio y profesional junto a la fecha y la hora', () => {
      mockServices.mockReturnValue({
        data: [{ public_id: 'svc-1', name: 'Kapping', price: 27000, deposit_mode: 'none' }],
        isLoading: false
      })
      render(<BookingStepConfirmation {...props()} />)

      expect(dato('Fecha')).toBe('25/09/2026')
      expect(dato('Hora')).toBe('09:00 hs')
      expect(dato('Servicio')).toBe('Kapping')
      expect(dato('Profesional')).toBe('Ana')
    })

    it('con "Cualquiera" muestra el profesional que asigno el horario', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({
              requestedStaffId: null,
              assignedStaff: { name: 'Bruno', isResource: false }
            })
          })}
        />
      )

      expect(dato('Profesional')).toBe('Bruno')
    })

    it('sin el profesional del horario no lo inventa', () => {
      render(
        <BookingStepConfirmation {...props({ bookingState: estado({ assignedStaff: null }) })} />
      )

      expect(screen.queryByText('Profesional', { selector: 'dt' })).not.toBeInTheDocument()
      expect(dato('Fecha')).toBe('25/09/2026')
    })

    it('una cancha o sala no se presenta como profesional', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({ assignedStaff: { name: 'Cancha 1', isResource: true } })
          })}
        />
      )

      expect(dato('Cancha / sala')).toBe('Cancha 1')
      expect(screen.queryByText('Profesional', { selector: 'dt' })).not.toBeInTheDocument()
    })
  })

  describe('politica de seña', () => {
    it('una politica corta se ve entera, una sola vez', () => {
      render(<BookingStepConfirmation {...props({ depositPolicy: 'La seña no se devuelve.' })} />)

      expect(screen.getAllByText('La seña no se devuelve.')).toHaveLength(1)
      expect(screen.getByText('La seña no se devuelve.').closest('details')).toBeNull()
      expect(screen.getByText('Política de seña de Tienda')).toBeInTheDocument()
    })

    it('una politica larga va plegada detras de "Ver política de seña"', () => {
      const larga = `Se cobra el 50% al reservar. ${'Con menos de 24 horas de aviso no se devuelve. '.repeat(8)}`
      render(<BookingStepConfirmation {...props({ depositPolicy: larga })} />)

      const resumen = screen.getByText('Ver política de seña de Tienda')
      const plegable = resumen.closest('details')
      expect(plegable).not.toHaveAttribute('open')
      expect(plegable).toHaveTextContent('Se cobra el 50% al reservar.')

      fireEvent.click(resumen)

      expect(plegable).toHaveAttribute('open')
    })
  })

  describe('vista previa de la seña', () => {
    const servicioConSena = (deposit_mode: 'optional' | 'required') =>
      mockServices.mockReturnValue({
        data: [{ public_id: 'svc-1', deposit_mode, deposit_type: 'percent', deposit_amount: 30 }],
        isLoading: false
      })
    const previewConSena = () =>
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

    // Revision de la PR #129: una seña OPCIONAL reservada sin Mercado Pago no
    // genera cobro (deposit_channels.resolve_deposit_channel devuelve None),
    // y el boton igual decia "pagar la seña por WhatsApp".
    it('con seña opcional el boton manual confirma la reserva, no pide pagar por WhatsApp', () => {
      servicioConSena('optional')
      previewConSena()
      render(<BookingStepConfirmation {...props({ paymentsEnabled: true })} />)

      expect(screen.getByRole('button', { name: RESERVAR })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: RESERVAR_CON_SENA })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: PAGAR_MP })).toBeInTheDocument()
    })

    it('con seña opcional inferida del servicio tampoco pide pagar por WhatsApp', () => {
      servicioConSena('optional')
      render(<BookingStepConfirmation {...props({ paymentsEnabled: false })} />)

      expect(screen.getByRole('button', { name: RESERVAR })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: RESERVAR_CON_SENA })).not.toBeInTheDocument()
    })

    it('muestra la seña que calcula el backend y ofrece pagarla online', () => {
      servicioConSena('required')
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
      expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).toBeInTheDocument()
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
      expect(screen.queryByRole('button', { name: RESERVAR_CON_SENA })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: RESERVAR })).not.toBeInTheDocument()
    })

    it('sin seña no muestra el recuadro ni el pago online', () => {
      render(<BookingStepConfirmation {...props({ paymentsEnabled: true })} />)

      expect(screen.queryByTestId('deposit-preview')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: PAGAR_MP })).not.toBeInTheDocument()
    })

    it('sin seña el boton confirma la reserva, no habla de pagar', () => {
      mockDepositPreview.mockReturnValue({
        isLoading: false,
        data: {
          amount: 0,
          base_amount: 0,
          extra_percent: 0,
          reasons: [],
          price: 5000,
          payments_enabled: false,
          online_payment_mandatory: false
        }
      })
      render(<BookingStepConfirmation {...props()} />)

      expect(screen.getByRole('button', { name: RESERVAR })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /pagar/i })).not.toBeInTheDocument()
    })

    it('con seña del servicio y cobros apagados, se paga por WhatsApp', () => {
      // Sin vista previa todavia: se infiere del servicio.
      mockServices.mockReturnValue({
        data: [
          {
            public_id: 'svc-1',
            deposit_mode: 'required',
            deposit_type: 'percent',
            deposit_amount: 30
          }
        ],
        isLoading: false
      })
      render(<BookingStepConfirmation {...props({ paymentsEnabled: false })} />)

      expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).toBeInTheDocument()
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
        promotionCode: 'BIENVENIDA10',
        addons: [],
        extraServiceIds: []
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
      abrirCodigo()

      fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
        target: { value: ' bienvenida10 ' }
      })
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      await waitFor(() => expect(screen.getByText('Bienvenida')).toBeInTheDocument())
      expect(mockPreviewPromotion).toHaveBeenCalledWith({
        storePublicId: 'store-1',
        serviceId: 'svc-1',
        code: 'BIENVENIDA10',
        addons: [],
        extraServiceIds: []
      })
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith(
        'BIENVENIDA10',
        expect.objectContaining({ final_amount: 4500 })
      )
    })

    it('un codigo rechazado muestra el motivo y no queda aplicado', async () => {
      mockPreviewPromotion.mockRejectedValue(
        new ValidationError('El código vencio', { statusCode: 400 })
      )
      const onPromotionCodeChange = jest.fn()
      render(<BookingStepConfirmation {...props({ onPromotionCodeChange })} />)
      abrirCodigo()

      fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
        target: { value: 'VIEJO' }
      })
      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      await waitFor(() => expect(screen.getByText('El código vencio')).toBeInTheDocument())
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith('', null)
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
      abrirCodigo()
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
      abrirCodigo()

      fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

      expect(mockPreviewPromotion).not.toHaveBeenCalled()
      expect(onPromotionCodeChange).toHaveBeenLastCalledWith('', null)
    })

    // 2026-10-16 (pedido de Mateo): el campo del codigo era ruido en el
    // celular para quien no tiene uno.
    it('arranca plegado detras de un link y al abrirlo muestra el campo con el foco', () => {
      render(<BookingStepConfirmation {...props()} />)

      expect(screen.queryByPlaceholderText('Ej: BIENVENIDA10')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Aplicar' })).not.toBeInTheDocument()
      const link = screen.getByRole('button', { name: '¿Tenés un código de descuento?' })
      expect(link).toHaveAttribute('aria-expanded', 'false')

      abrirCodigo()

      const campo = screen.getByLabelText('Código promocional')
      expect(campo).toHaveAttribute('placeholder', 'Ej: BIENVENIDA10')
      expect(campo).toHaveFocus()
      expect(screen.getByRole('button', { name: 'Aplicar' })).toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: '¿Tenés un código de descuento?' })
      ).not.toBeInTheDocument()
    })

    it('con un codigo ya aplicado (volver al paso) arranca abierto con el descuento', () => {
      render(
        <BookingStepConfirmation
          {...props({
            bookingState: estado({
              promotionCode: 'BIENVENIDA10',
              promotionPreview: {
                code: 'BIENVENIDA10',
                title: 'Bienvenida',
                promotion_type: 'percent',
                base_amount: 5000,
                discount_amount: 500,
                final_amount: 4500
              }
            })
          })}
        />
      )

      expect((screen.getByPlaceholderText('Ej: BIENVENIDA10') as HTMLInputElement).value).toBe(
        'BIENVENIDA10'
      )
      expect(screen.getByText('Bienvenida')).toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: '¿Tenés un código de descuento?' })
      ).not.toBeInTheDocument()
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
      expect(screen.getByPlaceholderText('Ej: 351 1234567')).toHaveAttribute('autocomplete', 'tel')
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
      expect(base.onConfirm).toHaveBeenCalledWith('manual', true, [])
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

    // Reservar por WhatsApp una seña obligatoria deja el pago pendiente y sin
    // link de Mercado Pago: se paga por WhatsApp (decision de Mateo, 2026-10-03).
    it('una reserva con pago pendiente se anuncia como pendiente de pago', async () => {
      const base = completo()
      base.onConfirm = jest.fn().mockResolvedValue(
        confirmacion({
          status: 'pending_payment',
          payment_required: true,
          deposit_channel: 'whatsapp'
        })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText('Reserva Pendiente de Pago')).toBeInTheDocument())
      expect(
        screen.getByText(
          'Pagá la seña por WhatsApp: tu turno se confirma cuando Tienda reciba el pago.'
        )
      ).toBeInTheDocument()
    })

    it('si la reserva falla vuelve al formulario con el aviso de horario ocupado', async () => {
      const base = completo()
      base.onConfirm = jest.fn().mockRejectedValue(
        new ConflictError('Horario ocupado', {
          errorCode: 'APPOINTMENT_CONFLICT',
          statusCode: 409
        })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() =>
        expect(
          screen.getByText('Ese horario ya no está disponible. Elegí otro.')
        ).toBeInTheDocument()
      )
      expect(
        screen.getByText(/El horario podria haberse ocupado mientras completabas el formulario/)
      ).toBeInTheDocument()
    })

    it('un 409 DEPOSIT_CHANNEL_UNAVAILABLE muestra el aviso neutro y no culpa al horario', async () => {
      // Revision 4R de la PR #108: la seña es obligatoria y el negocio no
      // tiene con que cobrarla. Sugerir "elegí otro horario" mandaba al
      // cliente a probar horarios que iban a rebotar igual.
      const aviso =
        'Este negocio no puede cobrar la seña de este servicio en este momento. Comunicate con el negocio para reservar.'
      const base = completo()
      base.onConfirm = jest.fn().mockRejectedValue(
        new ConflictError(aviso, {
          errorCode: 'DEPOSIT_CHANNEL_UNAVAILABLE',
          statusCode: 409
        })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      await waitFor(() => expect(screen.getByText(aviso)).toBeInTheDocument())
      expect(screen.queryByText(/El horario podria haberse ocupado/)).not.toBeInTheDocument()
    })

    it('un 409 IDEMPOTENCY_IN_PROGRESS pide esperar sin culpar al horario', async () => {
      const base = completo()
      base.onConfirm = jest.fn().mockRejectedValue(
        new ConflictError('La operación ya se está procesando.', {
          errorCode: 'IDEMPOTENCY_IN_PROGRESS',
          statusCode: 409
        })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      expect(
        await screen.findByText(
          'La operación ya se está procesando. Esperá unos segundos y revisá antes de reintentar.'
        )
      ).toBeInTheDocument()
      expect(screen.queryByText(/horario.*ocupad/i)).not.toBeInTheDocument()
    })

    it('un 409 de otra causa no se presenta como horario ocupado', async () => {
      const base = completo()
      base.onConfirm = jest.fn().mockRejectedValue(
        new ConflictError('El proveedor de pago no está disponible.', {
          errorCode: 'PAYMENT_GATEWAY_NOT_CONNECTED',
          statusCode: 409
        })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      expect(
        await screen.findByText('El proveedor de pago no está disponible.')
      ).toBeInTheDocument()
      expect(screen.queryByText(/El horario podria haberse ocupado/)).not.toBeInTheDocument()
    })

    it('un código 409 desconocido no atribuye el error al horario', async () => {
      const base = completo()
      base.onConfirm = jest.fn().mockRejectedValue(
        new ConflictError('No se pudo confirmar la operación.', {
          errorCode: 'FUTURE_CONFLICT_REASON',
          statusCode: 409
        })
      )
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      expect(await screen.findByText('No se pudo confirmar la operación.')).toBeInTheDocument()
      expect(screen.queryByText(/El horario podria haberse ocupado/)).not.toBeInTheDocument()
    })

    it('un 503 transitorio no culpa al horario y permite reintentar con los datos intactos', async () => {
      const base = completo()
      base.onConfirm = jest
        .fn()
        .mockRejectedValueOnce(
          new ServiceUnavailableError('Servicio temporalmente no disponible', {
            errorCode: 'SERVICE_UNAVAILABLE',
            statusCode: 503
          })
        )
        .mockResolvedValue(confirmacion())
      render(<BookingStepConfirmation {...base} />)
      aceptarTerminos()
      fireEvent.click(botonReservar())

      expect(
        await screen.findByText('No pudimos procesar tu reserva. Probá de nuevo.')
      ).toBeInTheDocument()
      expect(screen.queryByText(/horario.*ocupad/i)).not.toBeInTheDocument()
      expect((screen.getByPlaceholderText('Ej: Juan Perez') as HTMLInputElement).value).toBe(
        'Lucia'
      )
      expect((screen.getByPlaceholderText('Ej: 351 1234567') as HTMLInputElement).value).toBe(
        '1155550101'
      )

      fireEvent.click(botonReservar())
      await waitFor(() => expect(screen.getByText('Reserva Confirmada')).toBeInTheDocument())

      expect(base.onConfirm).toHaveBeenNthCalledWith(1, 'manual', true, [])
      expect(base.onConfirm).toHaveBeenNthCalledWith(2, 'manual', true, [])
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
describe('BookingStepConfirmation: adicionales', () => {
  const servicioConAdicionales = {
    public_id: 'svc-1',
    price: 27000,
    deposit_mode: 'required',
    deposit_type: 'percent',
    deposit_amount: 30,
    addons: [
      { id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 },
      { id: 'diseno', name: 'Diseño', unit_price: 1500, max_quantity: 2, position: 1 }
    ]
  }
  const elegido = (addonId: string, name: string, unitPrice: number, quantity: number) => ({
    addonId,
    name,
    unitPrice,
    quantity
  })
  const strassX6 = [elegido('strass', 'Strass', 500, 6)]
  const completo = (patch: Partial<BookingWizardState> = {}) =>
    props({
      bookingState: estado({
        client: cliente({ name: 'Lucia', phone: '1155550101' }),
        ...patch
      })
    })
  const ultimoPreview = () =>
    mockDepositPreview.mock.calls[mockDepositPreview.mock.calls.length - 1]?.[0] as {
      addons?: string[]
    }
  const conSena = (patch: Record<string, unknown> = {}) => ({
    isLoading: false,
    data: {
      amount: 9000,
      base_amount: 9000,
      extra_percent: 0,
      reasons: [],
      price: 30000,
      addons_amount: 3000,
      payments_enabled: true,
      online_payment_mandatory: false
    },
    ...patch
  })
  const error422 = () =>
    new ValidationError('Adicional no disponible', {
      errorCode: 'ADDON_UNAVAILABLE',
      statusCode: 422
    })

  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockServices.mockReset()
    mockRefreshServices.mockReset()
    mockRefreshServices.mockResolvedValue(undefined)
    // Por defecto el backend confirma el importe; los casos de error lo pisan.
    mockDepositPreview.mockReturnValue(conSena())
    mockServices.mockReturnValue({ data: [servicioConAdicionales], isLoading: false })
  })

  it('un servicio sin adicionales no muestra el selector ni el total', () => {
    mockServices.mockReturnValue({
      data: [{ ...servicioConAdicionales, addons: [] }],
      isLoading: false
    })
    render(<BookingStepConfirmation {...completo()} />)

    expect(screen.queryByRole('heading', { name: 'Adicionales' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('booking-price-summary')).not.toBeInTheDocument()
  })

  it('sumar adicionales actualiza el total y la seña se pide con ellos tras la espera', async () => {
    mockDepositPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(<ConEstado base={completo()} />)

    expect(screen.getByTestId('booking-price-summary')).toHaveTextContent(/Total\s*\$\s*27\.000/)
    // Sin adicionales ni descuento solo el total: "Servicio" lo repetia
    // (2026-10-16, pedido de Mateo).
    expect(screen.getByTestId('booking-price-summary')).not.toHaveTextContent('Servicio')
    expect(ultimoPreview().addons).toEqual([])

    for (let i = 0; i < 6; i += 1) {
      fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))
    }

    const resumen = screen.getByTestId('booking-price-summary')
    expect(resumen).toHaveTextContent(/Servicio\s*\$\s*27\.000/)
    expect(resumen).toHaveTextContent('Strass x6')
    expect(resumen).toHaveTextContent(/3\.000/)
    expect(resumen).toHaveTextContent(/Total\s*\$\s*30\.000/)
    // Debounce: los toques del contador no piden la seña uno por uno.
    expect(ultimoPreview().addons).toEqual([])
    await waitFor(() => expect(ultimoPreview().addons).toEqual(['strass:6']))
    const conAdicionales = mockDepositPreview.mock.calls
      .map(([params]) => ((params as { addons?: string[] }).addons ?? []).join(','))
      .filter(Boolean)
    expect(new Set(conAdicionales)).toEqual(new Set(['strass:6']))
  })

  it('mientras la seña se recalcula no deja reservar y muestra "Calculando…"', async () => {
    mockDepositPreview.mockReturnValue(conSena({ isPlaceholderData: true, isFetching: true }))
    render(<BookingStepConfirmation {...completo({ addons: strassX6 })} paymentsEnabled />)
    aceptarTerminos()

    expect(screen.getByTestId('deposit-preview')).toHaveTextContent('Calculando…')
    expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).toBeDisabled()
    expect(screen.getByRole('button', { name: PAGAR_MP })).toBeDisabled()
  })

  it('durante la espera del debounce los botones quedan deshabilitados', async () => {
    mockDepositPreview.mockReturnValue(conSena())
    render(<ConEstado base={{ ...completo({ addons: strassX6 }), paymentsEnabled: true }} />)
    aceptarTerminos()
    expect(screen.getByRole('button', { name: PAGAR_MP })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))

    expect(screen.getByRole('button', { name: PAGAR_MP })).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('button', { name: PAGAR_MP })).not.toBeDisabled())
  })

  it('muestra la seña que devuelve el backend sobre el total', () => {
    mockDepositPreview.mockReturnValue(conSena())
    render(<BookingStepConfirmation {...completo({ addons: strassX6 })} />)

    expect(screen.getByTestId('deposit-preview')).toHaveTextContent(/9\.000/)
    expect(ultimoPreview().addons).toEqual(['strass:6'])
  })

  it('reservar manda los adicionales elegidos', async () => {
    const base = completo({ addons: strassX6 })
    render(<BookingStepConfirmation {...base} />)
    aceptarTerminos()
    fireEvent.click(screen.getByRole('button', { name: RESERVAR_CON_SENA }))

    await waitFor(() =>
      expect(base.onConfirm).toHaveBeenCalledWith('manual', true, [
        { addon_id: 'strass', quantity: 6 }
      ])
    )
  })

  it('un adicional que desaparecio se avisa y hay que revisarlo antes de confirmar', () => {
    const base = completo({
      addons: [elegido('borrado', 'Esmalte', 900, 2), elegido('strass', 'Strass', 500, 1)]
    })
    render(<ConEstado base={base} />)
    aceptarTerminos()

    expect(
      screen.getByText(
        'Los adicionales del servicio cambiaron. Revisá tu selección antes de confirmar.'
      )
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).toBeDisabled()
    // Lo que sigue existiendo se conserva.
    expect(screen.getByLabelText('Cantidad de Strass')).toHaveTextContent('1')

    fireEvent.click(screen.getByRole('button', { name: 'Revisé mi selección' }))

    expect(screen.queryByText(/Los adicionales del servicio cambiaron/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).not.toBeDisabled()
  })

  it('un adicional con otro id pero mismo nombre y precio se remapea sin aviso', async () => {
    const base = completo({ addons: [elegido('strass-viejo', 'Strass', 500, 2)] })
    render(<BookingStepConfirmation {...base} />)
    aceptarTerminos()

    expect(screen.queryByText(/Los adicionales del servicio cambiaron/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: RESERVAR_CON_SENA }))
    await waitFor(() =>
      expect(base.onConfirm).toHaveBeenCalledWith('manual', true, [
        { addon_id: 'strass', quantity: 2 }
      ])
    )
  })

  it('el mismo nombre con otro precio no se remapea: queda en 0 y se avisa', () => {
    render(
      <BookingStepConfirmation
        {...completo({ addons: [elegido('strass-viejo', 'Strass', 400, 2)] })}
      />
    )

    expect(screen.getByText(/Los adicionales del servicio cambiaron/)).toBeInTheDocument()
    expect(screen.getByLabelText('Cantidad de Strass')).toHaveTextContent('0')
  })

  it('un 422 ADDON_UNAVAILABLE pide el catalogo salteando caches y no culpa al horario', async () => {
    const base = completo({ addons: [elegido('strass', 'Strass', 500, 1)] })
    base.onConfirm = jest.fn().mockRejectedValue(error422())
    render(<BookingStepConfirmation {...base} />)
    aceptarTerminos()
    fireEvent.click(screen.getByRole('button', { name: RESERVAR_CON_SENA }))

    await waitFor(() =>
      expect(
        screen.getByText(/Uno de los adicionales que elegiste ya no está disponible/)
      ).toBeInTheDocument()
    )
    expect(mockRefreshServices).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/El horario podria haberse ocupado/)).not.toBeInTheDocument()
  })

  it('si el preview de la seña rechaza un adicional, avisa, no deja reservar y actualizar vuelve a pedir el importe', async () => {
    const refetch = jest.fn().mockResolvedValue(undefined)
    mockDepositPreview.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: error422(),
      refetch
    })
    render(<BookingStepConfirmation {...completo({ addons: strassX6 })} />)
    aceptarTerminos()

    expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar adicionales' }))
    expect(mockRefreshServices).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1))
  })
})
describe('BookingStepConfirmation: promo sobre el total', () => {
  const strassX2 = [{ addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 2 }]
  const promo = (patch: Partial<PromotionPreview> = {}): PromotionPreview => ({
    code: 'BIENVENIDA10',
    title: 'Bienvenida',
    promotion_type: 'percent',
    base_amount: 5000,
    discount_amount: 500,
    final_amount: 4500,
    ...patch
  })
  // `price` del preview de la seña: el total que cobra el backend, con la
  // promo aplicada a servicio + adicionales.
  const precioDelBackend = (price: number) =>
    mockDepositPreview.mockReturnValue({
      isLoading: false,
      data: {
        amount: 0,
        base_amount: 0,
        extra_percent: 0,
        reasons: [],
        price,
        addons_amount: 1000,
        payments_enabled: false,
        online_payment_mandatory: false
      }
    })
  const conPromo = (preview: PromotionPreview, addons = strassX2) =>
    props({
      bookingState: estado({
        promotionCode: preview.code,
        promotionPreview: preview,
        addons
      })
    })
  const resumen = () => screen.getByTestId('booking-price-summary')

  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockServices.mockReset()
    mockDepositPreview.mockReturnValue({ data: undefined, isLoading: false })
    mockServices.mockReturnValue({
      data: [
        {
          public_id: 'svc-1',
          price: 5000,
          deposit_mode: 'none',
          deposit_type: 'percent',
          deposit_amount: null,
          addons: [{ id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }]
        }
      ],
      isLoading: false
    })
  })

  // El descuento vivia solo en el paso: al volver y avanzar, el total se
  // mostraba sin la promo que el backend si aplica.
  it('al volver a montar, el total sigue con el descuento aplicado', () => {
    precioDelBackend(5400)
    render(<BookingStepConfirmation {...conPromo(promo())} />)

    expect(resumen()).toHaveTextContent(/Total\s*\$\s*5\.400/)
    expect(screen.getByText('Bienvenida')).toBeInTheDocument()
  })

  it('un porcentaje descuenta el total con adicionales: muestra el total del backend', () => {
    // 10% de (5.000 + 2 x 500) = 600: total 5.400, no 4.500 + 1.000 = 5.500.
    precioDelBackend(5400)
    render(<BookingStepConfirmation {...conPromo(promo())} />)

    expect(screen.getByTestId('booking-price-discount')).toHaveTextContent(/BIENVENIDA10/)
    expect(screen.getByTestId('booking-price-discount')).toHaveTextContent(/600/)
    expect(resumen()).toHaveTextContent(/Total\s*\$\s*5\.400/)
    expect(resumen()).not.toHaveTextContent(/5\.500/)
    // Los importes del preview de la promo son solo del servicio: no se muestran.
    expect(screen.queryByText(/Total final:/)).not.toBeInTheDocument()
    expect(screen.getByText(/El descuento se aplica al total/)).toBeInTheDocument()
  })

  it('un monto fijo mayor al servicio sigue descontando sobre los adicionales', () => {
    // Fijo de 5.500 sobre 6.000: el preview de la promo lo topea en el
    // servicio (5.000), pero el backend descuenta del total y cobra 500.
    precioDelBackend(500)
    render(
      <BookingStepConfirmation
        {...conPromo(
          promo({
            code: 'FIJO5500',
            promotion_type: 'fixed',
            discount_amount: 5000,
            final_amount: 0
          })
        )}
      />
    )

    expect(screen.getByTestId('booking-price-discount')).toHaveTextContent(/5\.500/)
    expect(resumen()).toHaveTextContent(/Total\s*\$\s*500/)
  })

  it('con promo y adicionales, sin el total del backend dice "Calculando…"', () => {
    mockDepositPreview.mockReturnValue({ data: undefined, isLoading: true, isFetching: true })
    render(<BookingStepConfirmation {...conPromo(promo())} />)

    expect(resumen()).toHaveTextContent(/Total\s*Calculando…/)
    expect(screen.queryByTestId('booking-price-discount')).not.toBeInTheDocument()
  })

  it('con promo y sin adicionales el total es el de la promo aunque el backend no respondio', () => {
    render(<BookingStepConfirmation {...conPromo(promo(), [])} />)

    expect(resumen()).toHaveTextContent(/Total\s*\$\s*4\.500/)
    expect(screen.getByTestId('booking-price-discount')).toHaveTextContent(/500/)
    // Con descuento vuelve el detalle: servicio, descuento y total.
    expect(resumen()).toHaveTextContent(/Servicio\s*\$\s*5\.000/)
  })
})

describe('BookingStepConfirmation: la promo se revalida con los adicionales', () => {
  const servicio = {
    public_id: 'svc-1',
    price: 5000,
    deposit_mode: 'none',
    deposit_type: 'percent',
    deposit_amount: null,
    addons: [{ id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }]
  }
  const promo = (patch: Partial<PromotionPreview> = {}): PromotionPreview => ({
    code: 'MIN6000',
    title: 'Desde 6.000',
    promotion_type: 'percent',
    base_amount: 6000,
    discount_amount: 600,
    final_amount: 5400,
    ...patch
  })
  const conPromo = (quantity: number) => ({
    ...props({
      bookingState: estado({
        client: cliente({ name: 'Lucia', phone: '1155550101' }),
        promotionCode: 'MIN6000',
        promotionPreview: promo(),
        addons: [{ addonId: 'strass', name: 'Strass', unitPrice: 500, quantity }]
      })
    })
  })
  const ultimoPreviewDeSena = () =>
    mockDepositPreview.mock.calls[mockDepositPreview.mock.calls.length - 1]?.[0] as {
      addons?: string[]
    }
  const importeConfirmado = (patch: Record<string, unknown> = {}) => ({
    isLoading: false,
    refetch: jest.fn(),
    data: {
      amount: 0,
      base_amount: 0,
      extra_percent: 0,
      reasons: [],
      price: 5400,
      addons_amount: 1000,
      payments_enabled: false,
      online_payment_mandatory: false
    },
    ...patch
  })
  const quitarUno = () =>
    fireEvent.click(screen.getByRole('button', { name: 'Quitar uno de Strass' }))

  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockServices.mockReset()
    mockPreviewPromotion.mockReset()
    mockDepositPreview.mockReturnValue(importeConfirmado())
    mockServices.mockReturnValue({ data: [servicio], isLoading: false })
  })

  it('aplicar un codigo lo valida con los adicionales elegidos', async () => {
    mockPreviewPromotion.mockResolvedValue(promo())
    render(<ConEstado base={props({ bookingState: estado({ addons: [] }) })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))
    abrirCodigo()
    fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
      target: { value: 'min6000' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

    await waitFor(() =>
      expect(mockPreviewPromotion).toHaveBeenCalledWith({
        storePublicId: 'store-1',
        serviceId: 'svc-1',
        code: 'MIN6000',
        addons: ['strass:1'],
        extraServiceIds: []
      })
    )
  })

  it('cambiar la seleccion vuelve a validar el codigo tras la espera, y mientras no deja reservar', async () => {
    mockPreviewPromotion.mockResolvedValue(promo({ base_amount: 5500, final_amount: 4950 }))
    render(<ConEstado base={conPromo(2)} />)
    aceptarTerminos()
    quitarUno()

    expect(screen.getByRole('button', { name: RESERVAR })).toBeDisabled()
    expect(mockPreviewPromotion).not.toHaveBeenCalled()
    await waitFor(() =>
      expect(mockPreviewPromotion).toHaveBeenCalledWith({
        storePublicId: 'store-1',
        serviceId: 'svc-1',
        code: 'MIN6000',
        addons: ['strass:1'],
        extraServiceIds: []
      })
    )
    await waitFor(() => expect(screen.getByRole('button', { name: RESERVAR })).not.toBeDisabled())
    expect(mockPreviewPromotion).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Quitamos el código/)).not.toBeInTheDocument()
  })

  it('si el codigo ya no aplica (total bajo el minimo) se quita y se avisa', async () => {
    mockPreviewPromotion.mockRejectedValue(
      new ValidationError('La promocion no aplica a este servicio', { statusCode: 400 })
    )
    render(<ConEstado base={conPromo(2)} />)
    expect(screen.getByText('Desde 6.000')).toBeInTheDocument()
    aceptarTerminos()
    quitarUno()

    await waitFor(() =>
      expect(
        screen.getByText('Quitamos el código MIN6000: La promocion no aplica a este servicio')
      ).toBeInTheDocument()
    )
    // El wizard quedo sin codigo: no hay descuento ni caja de la promo.
    expect(screen.queryByText('Desde 6.000')).not.toBeInTheDocument()
    expect(screen.queryByTestId('booking-price-discount')).not.toBeInTheDocument()
    expect((screen.getByPlaceholderText('Ej: BIENVENIDA10') as HTMLInputElement).value).toBe('')
    await waitFor(() => expect(screen.getByRole('button', { name: RESERVAR })).not.toBeDisabled())
  })

  it('un fallo de red no quita el codigo pero lo dice', async () => {
    mockPreviewPromotion.mockRejectedValue(new Error('sin red'))
    render(<ConEstado base={conPromo(2)} />)
    quitarUno()

    await waitFor(() =>
      expect(screen.getByText(/No pudimos volver a validar el código MIN6000/)).toBeInTheDocument()
    )
    expect(screen.getByText('Desde 6.000')).toBeInTheDocument()
  })

  it('sin codigo aplicado cambiar adicionales no consulta la promo', async () => {
    render(<ConEstado base={props({ bookingState: estado({ addons: [] }) })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))

    await waitFor(() => expect(ultimoPreviewDeSena().addons).toEqual(['strass:1']))
    expect(mockPreviewPromotion).not.toHaveBeenCalled()
  })
})

describe('BookingStepConfirmation: adicionales de un servicio que no esta en el catalogo', () => {
  const elegidos = [{ addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 2 }]
  const conAdicionales = () =>
    props({
      bookingState: estado({
        client: cliente({ name: 'Lucia', phone: '1155550101' }),
        addons: elegidos
      })
    })

  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockServices.mockReset()
    mockDepositPreview.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('con el catalogo cargado y sin el servicio, avisa y no deja reservar', () => {
    mockServices.mockReturnValue({ data: [], isLoading: false })
    render(<BookingStepConfirmation {...conAdicionales()} />)
    aceptarTerminos()

    expect(screen.getByText(/Los adicionales del servicio cambiaron/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: RESERVAR })).toBeDisabled()
  })

  it('mientras el catalogo carga no avisa, pero tampoco deja reservar sin los adicionales', () => {
    mockServices.mockReturnValue({ data: undefined, isLoading: true })
    render(<BookingStepConfirmation {...conAdicionales()} />)
    aceptarTerminos()

    expect(screen.queryByText(/Los adicionales del servicio cambiaron/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: RESERVAR })).toBeDisabled()
  })
})

describe('BookingStepConfirmation: reservar solo con el importe confirmado', () => {
  const servicio = (patch: Record<string, unknown> = {}) => ({
    public_id: 'svc-1',
    price: 5000,
    deposit_mode: 'none',
    deposit_type: 'percent',
    deposit_amount: null,
    addons: [{ id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }],
    ...patch
  })
  const promo: PromotionPreview = {
    code: 'BIENVENIDA10',
    title: 'Bienvenida',
    promotion_type: 'percent',
    base_amount: 6000,
    discount_amount: 600,
    final_amount: 5400
  }
  const confirmado = {
    isLoading: false,
    data: {
      amount: 0,
      base_amount: 0,
      extra_percent: 0,
      reasons: [],
      price: 5400,
      addons_amount: 1000,
      payments_enabled: false,
      online_payment_mandatory: false
    }
  }
  const conError = (refetch: jest.Mock) => ({
    data: undefined,
    isLoading: false,
    error: new Error('sin red'),
    refetch
  })
  const estadoCompleto = (patch: Partial<BookingWizardState> = {}) =>
    estado({ client: cliente({ name: 'Lucia', phone: '1155550101' }), ...patch })
  const conPromoYAdicionales = () =>
    props({
      bookingState: estadoCompleto({
        promotionCode: 'BIENVENIDA10',
        promotionPreview: promo,
        addons: [{ addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 2 }]
      })
    })

  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockServices.mockReset()
    mockPreviewPromotion.mockReset()
    mockServices.mockReturnValue({ data: [servicio()], isLoading: false })
  })

  it('con promo y adicionales, si el preview falla no deja reservar, lo dice y reintentar lo vuelve a pedir', () => {
    // Revision de Enrique en #186: con el preview en error la pantalla decia
    // "Calculando…" pero volvia a habilitar Reservar.
    let preview: unknown = undefined
    const refetch = jest.fn(() => {
      preview = confirmado
      return Promise.resolve()
    })
    preview = conError(refetch)
    mockDepositPreview.mockImplementation(() => preview)
    const base = conPromoYAdicionales()
    const { rerender } = render(<BookingStepConfirmation {...base} />)
    aceptarTerminos()

    expect(screen.getByRole('button', { name: RESERVAR })).toBeDisabled()
    expect(screen.getByText(/No pudimos confirmar el importe/)).toBeInTheDocument()
    expect(screen.getByTestId('booking-price-summary')).toHaveTextContent(/Total\s*Sin confirmar/)

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    rerender(<BookingStepConfirmation {...base} />)

    expect(screen.queryByText(/No pudimos confirmar el importe/)).not.toBeInTheDocument()
    expect(screen.getByTestId('booking-price-summary')).toHaveTextContent(/Total\s*\$\s*5\.400/)
    expect(screen.getByRole('button', { name: RESERVAR })).not.toBeDisabled()
  })

  it('con seña y el preview en error tampoco deja reservar ni pagar', () => {
    mockServices.mockReturnValue({
      data: [servicio({ deposit_mode: 'required', deposit_amount: 30, addons: [] })],
      isLoading: false
    })
    mockDepositPreview.mockReturnValue(conError(jest.fn()))
    render(
      <BookingStepConfirmation {...props({ bookingState: estadoCompleto() })} paymentsEnabled />
    )
    aceptarTerminos()

    expect(screen.getByRole('button', { name: RESERVAR_CON_SENA })).toBeDisabled()
    expect(screen.getByRole('button', { name: PAGAR_MP })).toBeDisabled()
    expect(screen.getByText(/No pudimos confirmar el importe/)).toBeInTheDocument()
  })

  it('sin seña, promo ni adicionales un preview en error no cambia nada', () => {
    mockDepositPreview.mockReturnValue(conError(jest.fn()))
    render(<BookingStepConfirmation {...props({ bookingState: estadoCompleto() })} />)
    aceptarTerminos()

    expect(screen.getByRole('button', { name: RESERVAR })).not.toBeDisabled()
    expect(screen.queryByText(/No pudimos confirmar el importe/)).not.toBeInTheDocument()
  })

  it('si la revalidacion de la promo falla por la red, no deja reservar hasta que un reintento sale bien', async () => {
    mockDepositPreview.mockReturnValue(confirmado)
    mockPreviewPromotion.mockRejectedValueOnce(new Error('sin red')).mockResolvedValueOnce({
      ...promo,
      base_amount: 5500,
      discount_amount: 550,
      final_amount: 4950
    })
    render(<ConEstado base={conPromoYAdicionales()} />)
    aceptarTerminos()
    fireEvent.click(screen.getByRole('button', { name: 'Quitar uno de Strass' }))

    await waitFor(() =>
      expect(screen.getByText(/No pudimos volver a validar el código/)).toBeInTheDocument()
    )
    // Pasada la espera de la seña, sigue frenado: la promo no esta confirmada.
    await new Promise((resolve) => setTimeout(resolve, 450))
    expect(screen.getByRole('button', { name: RESERVAR })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))

    await waitFor(() => expect(screen.getByRole('button', { name: RESERVAR })).not.toBeDisabled())
    expect(mockPreviewPromotion).toHaveBeenCalledTimes(2)
    expect(screen.queryByText(/No pudimos volver a validar el código/)).not.toBeInTheDocument()
  })
})
