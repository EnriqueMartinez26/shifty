import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ConflictError } from '@shared/errors'
import { argentinaLocalToUtcIso } from '@shared/utils/argentinaTime'

import { NewAppointmentModal } from './NewAppointmentModal'

const mockServices = jest.fn()
const mockStaff = jest.fn()
const mockFeatureFlags = jest.fn()
const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()
const mockCrearTurno = jest.fn()

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
  useCreateAppointment: () => ({ mutateAsync: mockCrearTurno, isPending: false })
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
    mockCrearTurno.mockReset()
    mockCrearTurno.mockResolvedValue({})
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

  it('el turno se crea en el instante UTC de la hora argentina tipeada', async () => {
    // F11a-01: concatenaba `${date}T${time}:00Z`, asi que "10:00" que tipea el
    // dueno se agendaba 10:00 UTC = 07:00 ART, tres horas antes.
    conOtp(false)
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)
    const fecha = container.querySelector<HTMLInputElement>('input[type="date"]')
    if (!fecha) throw new Error('el modal ya no tiene input de fecha')

    fireEvent.click(botonCrear())

    await waitFor(() => expect(mockCrearTurno).toHaveBeenCalledTimes(1))
    const payload = mockCrearTurno.mock.calls[0]?.[0] as { starts_at: string }
    expect(payload.starts_at).toBe(argentinaLocalToUtcIso(fecha.value, '10:00'))
    // La prueba de que no es UTC crudo: el sufijo ingenuo habria sido este.
    expect(payload.starts_at).not.toBe(`${fecha.value}T10:00:00Z`)
  })

  it('el gate de OTP abre aunque el telefono se tipee en otro formato', async () => {
    // F11a-02: `normalize_phone` del backend saca los separadores y antepone
    // `+`, asi que "11 5555-0101" vuelve como "+1155550101". Comparar las
    // cadenas crudas no coincidia nunca y el alta con OTP quedaba imposible
    // desde el panel.
    mockRequestOtp.mockResolvedValue({ ok: true })
    mockVerifyOtp.mockResolvedValue({ phone: '+1155550101' })
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)
    fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
      target: { value: '11 5555-0101' }
    })
    fireEvent.change(screen.getByPlaceholderText('juan@email.com'), {
      target: { value: 'lucia@example.com' }
    })

    fireEvent.click(botonEnviarCodigo())
    await waitFor(() => expect(mockRequestOtp).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByPlaceholderText('Ingresá el código OTP'), {
      target: { value: '123456' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verificar código' }))

    await waitFor(() => expect(botonCrear()).not.toBeDisabled())
    // Timeout explicito: el test corre en 100 ms aislado, pero encadena dos
    // `waitFor` sobre mutaciones de react-query y con la suite completa en
    // paralelo se pasaba de los 5 s por defecto de jest. Se sube solo este
    // caso; subir el global esconderia lentitud real en otros tests.
  }, 20000)

  it('un 409 al crear muestra que el horario esta ocupado, no el mensaje crudo (F9-03)', async () => {
    // El servicio propaga el ConflictError tipado. Antes el modal lo buscaba
    // en `originalError` del envoltorio y, sin envoltorio, caia al mensaje crudo.
    conOtp(false)
    mockCrearTurno.mockRejectedValue(new ConflictError('Conflict'))
    const onClose = jest.fn()
    const { container } = render(<NewAppointmentModal isOpen onClose={onClose} />)

    completarFormulario(container)
    fireEvent.click(botonCrear())

    expect(
      await screen.findByText('Ese horario ya está ocupado para ese profesional.')
    ).toBeInTheDocument()
    expect(screen.queryByText('Conflict')).not.toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('un error que no es de conflicto muestra su mensaje', async () => {
    conOtp(false)
    mockCrearTurno.mockRejectedValue(new Error('El servicio no esta disponible'))
    const { container } = render(<NewAppointmentModal isOpen onClose={jest.fn()} />)

    completarFormulario(container)
    fireEvent.click(botonCrear())

    expect(await screen.findByText('El servicio no esta disponible')).toBeInTheDocument()
    expect(
      screen.queryByText('Ese horario ya está ocupado para ese profesional.')
    ).not.toBeInTheDocument()
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
