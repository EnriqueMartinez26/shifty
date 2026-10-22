import React from 'react'

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import type {
  BookingConfirmation,
  DepositPreview,
  PublicService
} from '@application/services/PublicBookingService'

import { ValidationError } from '@shared/errors'
import { formatCurrency } from '@shared/utils/currency'

import { BookingStepConfirmation } from './BookingStepConfirmation'
import type { BookingWizardState } from './types'

// Varios servicios en un turno (2026-10-16). El total y la seña salen SOLO de
// los previews del backend (decision de Mateo): el paso nunca los calcula.

const mockDepositPreview = jest.fn()
const mockPreviewPromotion = jest.fn()
const mockServices = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicDepositPreview: (...args: unknown[]) => mockDepositPreview(...args),
  usePreviewPublicPromotion: () => ({ mutateAsync: mockPreviewPromotion, isPending: false }),
  usePublicServices: (...args: unknown[]) => mockServices(...args),
  useRefreshPublicServices: () => jest.fn()
}))

const servicio = (patch: Partial<PublicService> & { public_id: string }): PublicService => ({
  name: 'Servicio',
  description: null,
  duration_minutes: 30,
  price: 1000,
  deposit_mode: 'none',
  deposit_type: 'percent',
  deposit_amount: null,
  color: null,
  image_url: null,
  ...patch
})

const corte = servicio({
  public_id: 'corte',
  name: 'Corte',
  duration_minutes: 30,
  price: 10000,
  deposit_mode: 'required',
  deposit_amount: 50,
  addons: [{ id: 'lavado', name: 'Lavado', unit_price: 1000, max_quantity: 1, position: 0 }]
})
const barba = servicio({
  public_id: 'barba',
  name: 'Barba',
  duration_minutes: 15,
  price: 5000,
  addons: [{ id: 'toalla', name: 'Toalla caliente', unit_price: 500, max_quantity: 2, position: 0 }]
})

const estado = (patch: Partial<BookingWizardState> = {}): BookingWizardState => ({
  serviceId: 'corte',
  extraServiceIds: ['barba'],
  requestedStaffId: null,
  assignedStaffId: 'st-1',
  assignedStaff: { name: 'Ana', isResource: false },
  date: '2026-09-25',
  startTime: '09:00',
  startsAt: '2026-09-25T12:00:00+00:00',
  client: {
    name: 'Lucia',
    email: 'lucia@example.com',
    phone: '',
    notes: '',
    customFields: {}
  },
  promotionCode: '',
  promotionPreview: null,
  addons: [],
  ...patch
})

const preview = (patch: Partial<DepositPreview> = {}): DepositPreview => ({
  amount: 7500,
  base_amount: 7500,
  extra_percent: 0,
  reasons: [],
  price: 15000,
  addons_amount: 0,
  extra_services_amount: 5000,
  payments_enabled: false,
  online_payment_mandatory: false,
  ...patch
})

const confirmacion = (): BookingConfirmation => ({
  public_id: 'apt-1',
  service_id: 'corte',
  service_name: 'Corte',
  staff_id: 'st-1',
  staff_name: 'Ana',
  starts_at: '2026-09-25T12:00:00+00:00',
  ends_at: '2026-09-25T12:45:00+00:00',
  status: 'pending_payment',
  client_name: 'Lucia',
  client_phone: '1155550101',
  payment_required: true,
  extra_services: [{ public_id: 'barba', name: 'Barba', duration_minutes: 15 }],
  services_label: 'Corte + Barba'
})

type Props = React.ComponentProps<typeof BookingStepConfirmation>

const props = (patch: Partial<Props> = {}): Props => ({
  storePublicId: 'store-1',
  serviceId: 'corte',
  paymentsEnabled: false,
  storeName: 'Tienda',
  storeSlug: 'tienda',
  whatsappNumber: null,
  depositPolicy: null,
  allowManualCoordination: true,
  bookingState: estado(),
  customFields: [],
  requiresOtp: false,
  otpState: {
    code: '',
    channel: 'email',
    email: '',
    verified: false,
    verifiedPhone: '',
    expiresAt: '',
    error: '',
    rateLimited: false,
    debugCode: ''
  },
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
      onAddonsChange={(addons) => setBookingState((prev) => ({ ...prev, addons }))}
    />
  )
}

// Adicionales ya elegidos en el primer paso (S4), uno por servicio.
const conAdicionales: BookingWizardState['addons'] = [
  { addonId: 'lavado', name: 'Lavado', unitPrice: 1000, quantity: 1 },
  { addonId: 'toalla', name: 'Toalla caliente', unitPrice: 500, quantity: 1, serviceId: 'barba' }
]
// S5: el turno va en una linea de la tarjeta de pago.
const resumen = () => screen.getByTestId('booking-summary-line')
const precio = () => screen.getByTestId('booking-price-summary')

describe('BookingStepConfirmation con varios servicios', () => {
  beforeEach(() => {
    mockDepositPreview.mockReset()
    mockPreviewPromotion.mockReset()
    mockServices.mockReset()
    mockServices.mockReturnValue({ data: [corte, barba], isLoading: false })
    mockDepositPreview.mockReturnValue({ data: preview(), isLoading: false })
  })

  it('el resumen nombra todos los servicios y la duracion del turno entero', () => {
    render(<BookingStepConfirmation {...props()} />)

    expect(within(resumen()).getByText('Corte + Barba')).toBeInTheDocument()
    expect(within(resumen()).getByText('45 min')).toBeInTheDocument()
  })

  it('pide la seña con los servicios sumados', () => {
    render(<BookingStepConfirmation {...props()} />)

    expect(mockDepositPreview).toHaveBeenLastCalledWith(
      expect.objectContaining({ serviceId: 'corte', extraServiceIds: ['barba'] })
    )
  })

  it('el detalle va por servicio y el total y la seña son los del backend', () => {
    // Ningun numero de aca sale de sumar en el front: 14200 y 7100 son del preview.
    mockDepositPreview.mockReturnValue({
      data: preview({ price: 14200, amount: 7100, base_amount: 7100 }),
      isLoading: false
    })
    render(<BookingStepConfirmation {...props()} />)

    const detalle = precio()
    expect(within(detalle).getByText('Corte')).toBeInTheDocument()
    expect(within(detalle).getByText('Barba')).toBeInTheDocument()
    expect(detalle).toHaveTextContent(`Total${formatCurrency(14200)}`)
    expect(screen.getByTestId('deposit-preview')).toHaveTextContent(formatCurrency(7100))
  })

  it('sin el preview el total no se inventa: queda "Calculando…" y no se reserva', () => {
    mockDepositPreview.mockReturnValue({ data: undefined, isLoading: true })
    render(<BookingStepConfirmation {...props()} />)
    fireEvent.click(screen.getByRole('checkbox'))

    expect(within(precio()).getByText('Calculando…')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Reservar y pagar la seña por WhatsApp' })
    ).toBeDisabled()
  })

  // S5: se eligen por servicio en el primer paso; aca viajan juntos.
  it('los adicionales de cada servicio viajan juntos en el pedido', async () => {
    const onConfirm = jest.fn().mockResolvedValue(confirmacion())
    render(
      <ConEstado
        base={props({
          onConfirm,
          bookingState: estado({
            client: {
              name: 'Lucia',
              email: 'lucia@example.com',
              phone: '1155550101',
              notes: '',
              customFields: {}
            },
            addons: conAdicionales
          })
        })}
      />
    )

    expect(screen.queryByRole('heading', { name: /Adicionales de/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox'))

    await waitFor(() =>
      expect(mockDepositPreview).toHaveBeenLastCalledWith(
        expect.objectContaining({ addons: ['lavado:1', 'toalla:1'], extraServiceIds: ['barba'] })
      )
    )
    const reservar = screen.getByRole('button', { name: 'Reservar y pagar la seña por WhatsApp' })
    await waitFor(() => expect(reservar).not.toBeDisabled())
    await act(async () => {
      fireEvent.click(reservar)
    })

    expect(onConfirm).toHaveBeenCalledWith('manual', true, [
      { addon_id: 'lavado', quantity: 1 },
      { addon_id: 'toalla', quantity: 1 }
    ])
  })

  it('el resumen nombra cada servicio con sus adicionales', () => {
    render(
      <BookingStepConfirmation {...props({ bookingState: estado({ addons: conAdicionales }) })} />
    )

    expect(resumen()).toHaveTextContent('Corte + Lavado + Barba + Toalla caliente · 45 min')
  })

  it('aplicar un codigo lo valida contra todos los servicios', async () => {
    mockPreviewPromotion.mockResolvedValue({
      code: 'OFF10',
      title: 'Diez off',
      promotion_type: 'percent',
      base_amount: 15000,
      discount_amount: 1500,
      final_amount: 13500
    })
    render(<BookingStepConfirmation {...props()} />)

    fireEvent.click(screen.getByRole('button', { name: '¿Tenés un código de descuento?' }))
    fireEvent.change(screen.getByPlaceholderText('Ej: BIENVENIDA10'), {
      target: { value: 'off10' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

    await waitFor(() => expect(screen.getByText('Diez off')).toBeInTheDocument())
    expect(mockPreviewPromotion).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'OFF10', extraServiceIds: ['barba'] })
    )
    expect(screen.getByText('El descuento se aplica al total del turno.')).toBeInTheDocument()
  })

  it('un 422 del preview por la combinacion de servicios dice que hacer', () => {
    mockDepositPreview.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new ValidationError('Demasiados servicios', {
        errorCode: 'TOO_MANY_SERVICES',
        statusCode: 422
      })
    })
    render(<BookingStepConfirmation {...props()} />)

    expect(
      screen.getByText(
        'Podés reservar hasta 3 servicios por turno. Volvé al primer paso y quitá alguno.'
      )
    ).toBeInTheDocument()
  })

  it.each([
    ['TOO_MANY_SERVICES', 'Podés reservar hasta 3 servicios por turno.'],
    ['SERVICES_TOO_LONG', 'Los servicios que elegiste no entran en un solo turno.'],
    ['MULTI_SERVICE_DISABLED', 'La tienda ya no toma varios servicios en un mismo turno.'],
    ['STAFF_CANNOT_PERFORM_SELECTION', 'El profesional elegido no hace todos los servicios']
  ])('si la reserva rebota con %s lo explica y no culpa al horario', async (code, texto) => {
    const onConfirm = jest
      .fn()
      .mockRejectedValue(new ValidationError('rechazado', { errorCode: code, statusCode: 422 }))
    render(
      <BookingStepConfirmation
        {...props({
          onConfirm,
          bookingState: estado({
            client: {
              name: 'Lucia',
              email: 'lucia@example.com',
              phone: '1155550101',
              notes: '',
              customFields: {}
            }
          })
        })}
      />
    )
    fireEvent.click(screen.getByRole('checkbox'))
    const reservar = screen.getByRole('button', { name: 'Reservar y pagar la seña por WhatsApp' })
    await waitFor(() => expect(reservar).not.toBeDisabled())
    await act(async () => {
      fireEvent.click(reservar)
    })

    expect(await screen.findByText(new RegExp(texto))).toBeInTheDocument()
    expect(screen.queryByText(/El horario podria haberse ocupado/)).not.toBeInTheDocument()
  })
})
