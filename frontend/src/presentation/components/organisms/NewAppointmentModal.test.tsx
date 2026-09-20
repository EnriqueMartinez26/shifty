import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { NewAppointmentModal } from './NewAppointmentModal'

const mockServices = jest.fn()
const mockStaff = jest.fn()
const mockFeatureFlags = jest.fn()
const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()

jest.mock('@presentation/hooks/useManagedServices', () => ({
  useManagedServices: () => mockServices()
}))

jest.mock('@presentation/hooks/useManagedStaff', () => ({
  useManagedStaff: () => mockStaff()
}))

jest.mock('@presentation/hooks/useStores', () => ({
  useStoreFeatureFlags: () => mockFeatureFlags(),
  useStoreSettings: () => ({ data: { public_id: 'store-1' }, isLoading: false })
}))

jest.mock('@presentation/hooks/useCalendarAgenda', () => ({
  useCreateAppointment: () => ({ mutateAsync: jest.fn(), isPending: false })
}))

jest.mock('@presentation/hooks/usePublic', () => ({
  useRequestPublicOtp: () => ({ mutateAsync: mockRequestOtp, isPending: false }),
  useVerifyPublicOtp: () => ({ mutateAsync: mockVerifyOtp, isPending: false })
}))

const servicio = { id: 'svc-1', name: 'Corte', isActive: true }

const conOtp = (activo: boolean) => {
  mockFeatureFlags.mockReturnValue({
    data: { flags: { otp_booking: activo } },
    isLoading: false
  })
}

/**
 * Deja el formulario completo salvo la verificacion del telefono.
 * La fecha ya viene cargada con el dia de hoy al abrirse el modal, asi que
 * solo falta la hora.
 */
const completarFormulario = (container: HTMLElement) => {
  fireEvent.change(screen.getByDisplayValue('Seleccionar servicio...'), {
    target: { value: 'svc-1' }
  })
  fireEvent.change(screen.getByPlaceholderText('Ej: Juan Pérez'), {
    target: { value: 'Juan Perez' }
  })
  fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
    target: { value: '+5491155550101' }
  })
  const hora = container.querySelector<HTMLInputElement>('input[type="time"]')
  if (!hora) throw new Error('el modal ya no tiene input de hora')
  fireEvent.change(hora, { target: { value: '10:00' } })
}

const botonCrear = () => screen.getByRole('button', { name: 'Crear Turno' })
const botonEnviarCodigo = () => screen.getByRole('button', { name: 'Enviar código' })

describe('NewAppointmentModal', () => {
  beforeEach(() => {
    mockServices.mockReset()
    mockStaff.mockReset()
    mockFeatureFlags.mockReset()
    mockRequestOtp.mockReset()
    mockVerifyOtp.mockReset()
    mockServices.mockReturnValue({ data: [servicio], isLoading: false })
    mockStaff.mockReturnValue({ data: [], isLoading: false })
    conOtp(true)
  })

  it('el codigo OTP se pide por email, nunca por WhatsApp ni SMS', async () => {
    // Regresion de F11a-03: el panel ofrecia canales que produccion rechaza
    // con 422 (OTP_PROVIDER nunca es `console` en prod), asi que el alta
    // manual quedaba inutilizable. Email es el unico canal con envio real.
    mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '2026-09-25T13:00:00Z' })
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)
    fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
      target: { value: 'lucia@example.com' }
    })

    fireEvent.click(botonEnviarCodigo())

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

  it('sin el email del cliente no se puede pedir el codigo', () => {
    // El backend exige el email cuando el canal es email: mandarlo vacio
    // seria un 422 seguro, asi que el boton no habilita.
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)

    expect(botonEnviarCodigo()).toBeDisabled()
    expect(mockRequestOtp).not.toHaveBeenCalled()
  })

  it('con OTP exigido el turno no se crea hasta verificar el telefono', () => {
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)

    expect(botonCrear()).toBeDisabled()
  })

  it('sin OTP exigido el mismo formulario si habilita el turno', () => {
    // Contraprueba del test anterior: demuestra que lo que frena el submit es
    // el gate de OTP y no un campo del formulario que quedo sin llenar.
    conOtp(false)
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)

    expect(botonCrear()).not.toBeDisabled()
    expect(screen.queryByText('Verificar teléfono')).not.toBeInTheDocument()
  })
})
