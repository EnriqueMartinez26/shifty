import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { BookingWizardContainer } from './BookingWizardContainer'
import type { PublicStore } from '../../../hooks/usePublic'

const mockServices = jest.fn()
const mockStaff = jest.fn()
const mockAvailability = jest.fn()
const mockRequestOtp = jest.fn()

jest.mock('../../../hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockServices(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicDepositPreview: () => ({ data: undefined, isLoading: false }),
  usePreviewPublicPromotion: () => ({ mutateAsync: jest.fn(), isPending: false }),
  useJoinWaitlist: () => ({ mutateAsync: jest.fn(), isPending: false, isSuccess: false }),
  useCreatePublicBooking: () => ({ mutateAsync: jest.fn(), isPending: false }),
  useRequestPublicOtp: () => ({ mutateAsync: mockRequestOtp, isPending: false }),
  useVerifyPublicOtp: () => ({ mutateAsync: jest.fn(), isPending: false })
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
})
