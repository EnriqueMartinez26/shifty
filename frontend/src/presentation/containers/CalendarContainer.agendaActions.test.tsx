import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { ConflictError, ForbiddenError } from '@shared/errors'

import { CalendarContainer } from './CalendarContainer'

const mockCancel = jest.fn()
const mockRefetch = jest.fn()
const idleMutation = { mutateAsync: jest.fn(), isPending: false }

// Domingo 20/09/2026. Los turnos son a las 14:00 de Argentina: no empezaron.
const appointmentOf = (id: string, staffId: string, clientName: string, status = 'confirmed') => ({
  id,
  status,
  staffId,
  staffName: staffId === 'st-1' ? 'Ana Gomez' : 'Beto Diaz',
  clientName,
  serviceName: 'Corte',
  clientPhone: null,
  serviceId: 'svc-1',
  timeSpan: {
    getStartsAt: () => new Date('2026-09-20T17:00:00.000Z'),
    getEndsAt: () => new Date('2026-09-20T18:00:00.000Z')
  }
})

let mockAppointments = [
  appointmentOf('appt-own', 'st-1', 'Luis Propio'),
  appointmentOf('appt-other', 'st-2', 'Marta Ajena')
]

jest.mock('../hooks/useAppointmentBlocks', () => ({
  useAppointmentBlocks: () => ({ data: [], isLoading: false, error: null }),
  useBlockTemplates: () => ({ data: [], isLoading: false, error: null }),
  useBlockPreview: () => idleMutation,
  useCreateAppointmentBlock: () => idleMutation,
  useCreateRecurringAppointmentBlock: () => idleMutation,
  useDeleteAppointmentBlock: () => idleMutation,
  useUpdateAppointmentBlock: () => idleMutation
}))

jest.mock('../hooks/useCalendarAgenda', () => ({
  useCalendarAgenda: () => ({
    data: { appointments: mockAppointments, total: mockAppointments.length },
    isLoading: false,
    error: null,
    refetch: mockRefetch
  }),
  useCancelAppointment: () => ({ mutateAsync: mockCancel, isPending: false }),
  useCompleteAppointment: () => idleMutation,
  useConfirmAppointment: () => idleMutation,
  useMarkAbsentAppointment: () => idleMutation,
  useReleaseAppointment: () => idleMutation,
  useRescheduleAppointment: () => idleMutation
}))

// Ana: sin franjas (horario del local). Beto: franjas, pero ninguna el
// domingo (dia 6): no atiende hoy aunque el local abra.
jest.mock('../hooks/useManagedStaff', () => ({
  useManagedStaff: () => ({
    data: [
      { id: 'st-1', displayName: 'Ana Gomez', isActive: true, schedules: [] },
      {
        id: 'st-2',
        displayName: 'Beto Diaz',
        isActive: true,
        schedules: [{ dayOfWeek: 0, startTime: '09:00:00', endTime: '18:00:00' }]
      }
    ],
    isLoading: false,
    error: null
  })
}))

jest.mock('../hooks/useStores', () => ({
  useStoreSettings: () => ({
    data: {
      name: 'Peluqueria Sol',
      slug: 'sol',
      business_hours: { sun: [{ open: '10:00', close: '18:00' }] }
    }
  })
}))

const mockUser = { role: 'professional', is_global_admin: false, public_id: 'st-1' }
jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser })
}))

jest.mock('../components/organisms/NewAppointmentModal', () => ({
  NewAppointmentModal: () => null
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

const confirmarCancelacion = async () =>
  fireEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancelar turno' })
  )

const cardOf = (clientName: string) => {
  const card = screen.getByText(clientName).closest('.absolute')
  if (!(card instanceof HTMLElement)) throw new Error(`No encontre la tarjeta de ${clientName}`)
  return card
}

describe('CalendarContainer - cancelar y reprogramar (FF-31)', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date('2026-09-20T15:30:00.000Z') })
    mockCancel.mockReset()
    mockRefetch.mockReset()
    mockUser.role = 'professional'
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
    mockAppointments = [
      appointmentOf('appt-own', 'st-1', 'Luis Propio'),
      appointmentOf('appt-other', 'st-2', 'Marta Ajena')
    ]
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  // 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
  // verse deshabilitada (FF-15). POST /appointments/ y PATCH .../reschedule
  // siguen bloqueados; PATCH .../cancel no (D-20260930-12).
  it('con la tienda suspendida no deja crear ni reprogramar, pero si cancelar', async () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    mockCancel.mockResolvedValue(undefined)
    render(<CalendarContainer />)

    const nuevo = screen.getByRole('button', { name: /Nuevo turno/ })
    expect(nuevo).toBeDisabled()
    expect(nuevo).toHaveAttribute('title', 'Tienda suspendida')
    const own = within(cardOf('Luis Propio'))
    expect(own.getByRole('button', { name: 'Reprogramar turno' })).toBeDisabled()

    fireEvent.click(own.getByRole('button', { name: 'Cancelar turno' }))
    await confirmarCancelacion()
    await waitFor(() => expect(mockCancel).toHaveBeenCalledWith('appt-own'))
  })

  it('sin suspension Nuevo turno y reprogramar siguen habilitados', () => {
    render(<CalendarContainer />)

    expect(screen.getByRole('button', { name: /Nuevo turno/ })).not.toBeDisabled()
    expect(
      within(cardOf('Luis Propio')).getByRole('button', { name: 'Reprogramar turno' })
    ).not.toBeDisabled()
  })

  it('el profesional solo ve cancelar y reprogramar en los turnos de su agenda (D-20260929-03)', () => {
    render(<CalendarContainer />)

    const own = within(cardOf('Luis Propio'))
    expect(own.getByRole('button', { name: 'Cancelar turno' })).toBeInTheDocument()
    expect(own.getByRole('button', { name: 'Reprogramar turno' })).toBeInTheDocument()

    const other = within(cardOf('Marta Ajena'))
    expect(other.queryByRole('button', { name: 'Cancelar turno' })).not.toBeInTheDocument()
    expect(other.queryByRole('button', { name: 'Reprogramar turno' })).not.toBeInTheDocument()
  })

  it('recepcion cancela y reprograma cualquier turno de la tienda', () => {
    mockUser.role = 'receptionist'
    render(<CalendarContainer />)

    for (const name of ['Luis Propio', 'Marta Ajena']) {
      const card = within(cardOf(name))
      expect(card.getByRole('button', { name: 'Cancelar turno' })).toBeInTheDocument()
      expect(card.getByRole('button', { name: 'Reprogramar turno' })).toBeInTheDocument()
    }
  })

  it('cancelar pide confirmacion y cancela el turno elegido', async () => {
    mockCancel.mockResolvedValue(undefined)
    render(<CalendarContainer />)

    fireEvent.click(within(cardOf('Luis Propio')).getByRole('button', { name: 'Cancelar turno' }))
    expect(await screen.findByText('¿Cancelar el turno de Luis Propio?')).toBeInTheDocument()
    // QA 2026-10-02: "Cancelar"/"Confirmar" era ambiguo en un dialogo de
    // cancelacion. Ahora dice "Volver" y "Cancelar turno".
    expect(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Volver' })
    ).toBeInTheDocument()
    await confirmarCancelacion()

    await waitFor(() => expect(mockCancel).toHaveBeenCalledWith('appt-own'))
    expect(await screen.findByText('Turno cancelado')).toBeInTheDocument()
  })

  it('un turno que ya empezo explica que se completa y recarga la agenda (D-20260929-05)', async () => {
    mockCancel.mockRejectedValue(
      new ConflictError('El turno ya empezo', {
        errorCode: 'APPOINTMENT_ALREADY_STARTED',
        statusCode: 409
      })
    )
    render(<CalendarContainer />)

    fireEvent.click(within(cardOf('Luis Propio')).getByRole('button', { name: 'Cancelar turno' }))
    await confirmarCancelacion()

    expect(
      await screen.findByText(
        'El turno ya empezó: no se puede cancelar. Completalo o marcá la ausencia.'
      )
    ).toBeInTheDocument()
    expect(mockRefetch).toHaveBeenCalledTimes(1)
  })

  it('un 403 dice que solo cancela los de su agenda', async () => {
    mockCancel.mockRejectedValue(
      new ForbiddenError('Permiso denegado', { errorCode: 'PERMISSION_DENIED', statusCode: 403 })
    )
    render(<CalendarContainer />)

    fireEvent.click(within(cardOf('Luis Propio')).getByRole('button', { name: 'Cancelar turno' }))
    await confirmarCancelacion()

    expect(
      await screen.findByText('Solo podés cancelar los turnos de tu agenda.')
    ).toBeInTheDocument()
    expect(mockRefetch).not.toHaveBeenCalled()
  })

  it('avisa que vence el cobro al cancelar un turno pendiente de pago (D-20260929-07)', async () => {
    mockAppointments = [appointmentOf('appt-own', 'st-1', 'Luis Propio', 'pending_payment')]
    render(<CalendarContainer />)

    fireEvent.click(within(cardOf('Luis Propio')).getByRole('button', { name: 'Cancelar turno' }))

    expect(
      await screen.findByText(
        '¿Cancelar el turno de Luis Propio? El cobro pendiente se va a vencer y su link de pago deja de servir.'
      )
    ).toBeInTheDocument()
  })

  it('reprogramar abre el formulario con el turno elegido, sin la opcion de fuera de horario', () => {
    render(<CalendarContainer />)

    fireEvent.click(
      within(cardOf('Luis Propio')).getByRole('button', { name: 'Reprogramar turno' })
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Luis Propio · Corte · Ana Gomez')).toBeInTheDocument()
    expect(
      within(dialog).queryByLabelText('Permitir fuera del horario del profesional')
    ).not.toBeInTheDocument()
  })
})

describe('CalendarContainer - fuera de horario por profesional (FF-03)', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date('2026-09-20T15:30:00.000Z') })
    mockAppointments = []
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('sin franjas usa el horario del local; con franjas pero no ese dia, todo fuera de horario', () => {
    render(<CalendarContainer />)

    // Grilla 10-18 (el horario del local). Ana lo cubre entero; Beto no
    // atiende el domingo: su columna es un solo tramo gris.
    const segments = screen.getAllByTestId('staff-off-hours')
    expect(segments).toHaveLength(1)
    const [segment] = segments
    if (!segment) throw new Error('No encontre el tramo fuera de horario')
    expect(segment).toHaveTextContent('Fuera de horario')
    expect(segment.style.top).toBe('0px')
    expect(segment.style.height).toBe(`${8 * 4 * 64}px`)
  })
})
