import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ConflictError } from '@shared/errors'
import { argentinaLocalToUtcIso } from '@shared/utils/argentinaTime'

import { NewAppointmentModal } from './NewAppointmentModal'

const mockCrearTurno = jest.fn()

jest.mock('@presentation/hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: [{ id: 'svc-1', name: 'Corte', isActive: true }] })
}))

jest.mock('@presentation/hooks/useManagedStaff', () => ({
  useManagedStaff: () => ({
    data: [{ id: 'st-1', displayName: 'Lucia', isActive: true, serviceIds: ['svc-1'] }]
  })
}))

jest.mock('@presentation/hooks/useCalendarAgenda', () => ({
  useCreateAppointment: () => ({ mutateAsync: mockCrearTurno, isPending: false })
}))

type Payload = { starts_at: string; idempotency_key: string; client_name: string }

const payloadDe = (llamada: number) => mockCrearTurno.mock.calls[llamada]?.[0] as Payload

const completarFormulario = (container: HTMLElement, fecha: string, hora: string) => {
  fireEvent.change(screen.getByDisplayValue('Seleccionar servicio...'), {
    target: { value: 'svc-1' }
  })
  fireEvent.change(screen.getByPlaceholderText('Ej: Juan Pérez'), {
    target: { value: 'Juan Perez' }
  })
  fireEvent.change(screen.getByPlaceholderText('PREFIJO + NUM'), {
    target: { value: '+5491155550101' }
  })
  const inputFecha = container.querySelector<HTMLInputElement>('input[type="date"]')
  const inputHora = container.querySelector<HTMLInputElement>('input[type="time"]')
  if (!inputFecha || !inputHora) throw new Error('el modal ya no tiene fecha u hora')
  fireEvent.change(inputFecha, { target: { value: fecha } })
  fireEvent.change(inputHora, { target: { value: hora } })
}

const crear = () => fireEvent.click(screen.getByRole('button', { name: 'Crear Turno' }))

describe('NewAppointmentModal', () => {
  beforeEach(() => {
    mockCrearTurno.mockReset()
    mockCrearTurno.mockResolvedValue('appt-1')
  })

  it('crea un turno pasado en el instante UTC de la hora argentina tipeada', async () => {
    // F11a-01: "13:00" se mandaba como 13:00 UTC. D-20260925-01: se aceptan
    // fechas pasadas para cargar turnos atrasados.
    const onClose = jest.fn()
    const { container } = render(<NewAppointmentModal onClose={onClose} />)

    completarFormulario(container, '2025-01-15', '13:00')
    crear()

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    const payload = payloadDe(0)
    expect(payload.starts_at).toBe(argentinaLocalToUtcIso('2025-01-15', '13:00'))
    expect(payload.starts_at).toMatch(/^2025-01-15T16:00/)
  })

  it('reintentar tras un 409 reusa la clave; editar el formulario usa una nueva', async () => {
    mockCrearTurno.mockRejectedValue(
      new ConflictError('texto del servidor', { errorCode: 'OUT_OF_SCHEDULE' })
    )
    const { container } = render(<NewAppointmentModal onClose={jest.fn()} />)

    completarFormulario(container, '2026-10-01', '10:00')
    crear()
    expect(
      await screen.findByText('El profesional no atiende en ese horario. Elegí otro.')
    ).toBeInTheDocument()
    crear()
    await waitFor(() => expect(mockCrearTurno).toHaveBeenCalledTimes(2))

    fireEvent.change(screen.getByPlaceholderText('Ej: Juan Pérez'), {
      target: { value: 'Juan Perez Gomez' }
    })
    crear()
    await waitFor(() => expect(mockCrearTurno).toHaveBeenCalledTimes(3))

    expect(payloadDe(1).idempotency_key).toBe(payloadDe(0).idempotency_key)
    expect(payloadDe(2).idempotency_key).not.toBe(payloadDe(0).idempotency_key)
  })

  it('el profesional no elige profesional: el backend le asigna su agenda', () => {
    const { unmount } = render(<NewAppointmentModal onClose={jest.fn()} />)
    expect(screen.getByDisplayValue('Cualquiera')).toBeInTheDocument()
    unmount()

    render(<NewAppointmentModal onClose={jest.fn()} isProfessional />)
    expect(screen.queryByDisplayValue('Cualquiera')).not.toBeInTheDocument()
  })
})
