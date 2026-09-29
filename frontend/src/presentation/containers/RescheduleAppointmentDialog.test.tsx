import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ConflictError, ForbiddenError } from '@shared/errors'

import { RescheduleAppointmentDialog } from './RescheduleAppointmentDialog'

const mockReschedule = jest.fn()
jest.mock('../hooks/useCalendarAgenda', () => ({
  useRescheduleAppointment: () => ({ mutateAsync: mockReschedule, isPending: false })
}))

// Turno del 01/10/2026 a las 10:00 de Argentina (13:00 UTC).
const appointment = {
  id: 'appt-1',
  clientName: 'Luis Perez',
  serviceName: 'Corte',
  staffName: 'Ana Gomez',
  startsAt: '2026-10-01T13:00:00.000Z'
}

const renderDialog = (isAdmin: boolean) => {
  const onDone = jest.fn()
  const onStateConflict = jest.fn()
  render(
    <RescheduleAppointmentDialog
      appointment={appointment}
      isAdmin={isAdmin}
      onClose={() => undefined}
      onDone={onDone}
      onStateConflict={onStateConflict}
    />
  )
  return { onDone, onStateConflict }
}

const moveTo = (date: string, time: string) => {
  fireEvent.change(screen.getByLabelText(/Nueva fecha/), { target: { value: date } })
  fireEvent.change(screen.getByLabelText(/Nueva hora/), { target: { value: time } })
}

const submit = () => fireEvent.click(screen.getByRole('button', { name: 'Reprogramar' }))

const backendError = (errorCode: string, statusCode: number) =>
  statusCode === 403
    ? new ForbiddenError('No autorizado', { errorCode, statusCode })
    : new ConflictError('Conflicto', { errorCode, statusCode })

describe('RescheduleAppointmentDialog (FF-31)', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date('2026-09-29T12:00:00.000Z') })
    mockReschedule.mockReset()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('precarga el horario actual en hora argentina', () => {
    renderDialog(false)
    expect((screen.getByLabelText(/Nueva fecha/) as HTMLInputElement).value).toBe('2026-10-01')
    expect((screen.getByLabelText(/Nueva hora/) as HTMLInputElement).value).toBe('10:00')
  })

  it('el administrador puede mover fuera de horario y el flag viaja', async () => {
    mockReschedule.mockResolvedValue(undefined)
    const { onDone } = renderDialog(true)

    moveTo('2026-10-02', '21:30')
    fireEvent.click(screen.getByLabelText('Permitir fuera del horario del profesional'))
    submit()

    await waitFor(() => expect(onDone).toHaveBeenCalledWith('Turno reprogramado'))
    expect(mockReschedule).toHaveBeenCalledWith({
      id: 'appt-1',
      input: {
        newStartsAt: '2026-10-03T00:30:00.000Z',
        idempotencyKey: expect.any(String),
        allowOutsideSchedule: true
      }
    })
  })

  it('el profesional no ve la opcion y nunca pide fuera de horario', async () => {
    mockReschedule.mockResolvedValue(undefined)
    const { onDone } = renderDialog(false)

    expect(
      screen.queryByLabelText('Permitir fuera del horario del profesional')
    ).not.toBeInTheDocument()
    moveTo('2026-10-02', '11:00')
    submit()

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(mockReschedule.mock.calls[0][0].input.allowOutsideSchedule).toBe(false)
  })

  it('OUT_OF_SCHEDULE al administrador le dice como moverlo igual', async () => {
    mockReschedule.mockRejectedValue(backendError('OUT_OF_SCHEDULE', 409))
    const { onDone } = renderDialog(true)

    submit()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'El profesional no atiende en ese horario. Marcá "Permitir fuera del horario del profesional" para moverlo igual.'
    )
    expect(onDone).not.toHaveBeenCalled()
  })

  it('OUT_OF_SCHEDULE al profesional solo le pide otro horario', async () => {
    mockReschedule.mockRejectedValue(backendError('OUT_OF_SCHEDULE', 409))
    renderDialog(false)

    submit()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'El profesional no atiende en ese horario. Elegí otro.'
    )
  })

  it('PERMISSION_DENIED explica que solo mueve los de su agenda', async () => {
    mockReschedule.mockRejectedValue(backendError('PERMISSION_DENIED', 403))
    renderDialog(false)

    submit()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Solo podés reprogramar los turnos de tu agenda.'
    )
  })

  it('un turno que ya no esta activo pide recargar la agenda', async () => {
    mockReschedule.mockRejectedValue(backendError('APPOINTMENT_NOT_ACTIVE', 409))
    const { onStateConflict } = renderDialog(true)

    submit()

    await waitFor(() => expect(onStateConflict).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'El turno ya terminó o fue cancelado: no se puede mover. Actualizá la agenda.'
    )
  })

  it('reintentar el mismo pedido reusa la clave; otro horario usa una nueva', async () => {
    mockReschedule.mockRejectedValue(backendError('APPOINTMENT_CONFLICT', 409))
    renderDialog(true)

    submit()
    await screen.findByRole('alert')
    submit()
    await waitFor(() => expect(mockReschedule).toHaveBeenCalledTimes(2))
    moveTo('2026-10-02', '12:00')
    submit()
    await waitFor(() => expect(mockReschedule).toHaveBeenCalledTimes(3))

    const keys = mockReschedule.mock.calls.map(([call]) => call.input.idempotencyKey)
    expect(keys[1]).toBe(keys[0])
    expect(keys[2]).not.toBe(keys[0])
  })

  it('avisa que el cliente no recibe aviso si el horario ya paso (D-20260929-07)', () => {
    renderDialog(true)
    expect(screen.queryByText(/el cliente no recibe aviso/)).not.toBeInTheDocument()

    moveTo('2026-09-28', '10:00')

    expect(screen.getByText(/el cliente no recibe aviso/)).toBeInTheDocument()
  })
})
