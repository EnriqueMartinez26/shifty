import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { CalendarContainer } from './CalendarContainer'

// Caracterizacion antes de partir el contenedor (F11c-08): fija lo que hoy
// hacen las vistas, el orden de los eventos y la navegacion. No es un bug.

const mockDeleteBlock = jest.fn()
const idleMutation = { mutateAsync: jest.fn(), isPending: false }

const appointmentOf = (
  id: string,
  clientName: string,
  startsAt: string,
  endsAt: string,
  status = 'confirmed'
) => ({
  id,
  status,
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  clientName,
  serviceName: 'Corte',
  clientPhone: null,
  serviceId: 'svc-1',
  timeSpan: {
    getStartsAt: () => new Date(startsAt),
    getEndsAt: () => new Date(endsAt)
  }
})

const blockOf = (publicId: string, reason: string, startsAt: string, endsAt: string) => ({
  public_id: publicId,
  staff_id: 'st-1',
  starts_at: startsAt,
  ends_at: endsAt,
  reason,
  is_active: true
})

type MockAppointment = ReturnType<typeof appointmentOf>
type MockBlock = ReturnType<typeof blockOf>

let mockAppointments: MockAppointment[] = []
let mockBlocks: MockBlock[] = []
let mockTotal: number | null = null
let mockBusinessHours: Record<string, { open: string; close: string }[]> = {}

jest.mock('../hooks/useAppointmentBlocks', () => ({
  useAppointmentBlocks: () => ({ data: mockBlocks, isLoading: false, error: null }),
  useBlockTemplates: () => ({ data: [], isLoading: false, error: null }),
  useBlockPreview: () => idleMutation,
  useCreateAppointmentBlock: () => idleMutation,
  useCreateRecurringAppointmentBlock: () => idleMutation,
  useDeleteAppointmentBlock: () => ({ mutateAsync: mockDeleteBlock, isPending: false }),
  useUpdateAppointmentBlock: () => idleMutation
}))

jest.mock('../hooks/useCalendarAgenda', () => ({
  useCalendarAgenda: () => ({
    data: { appointments: mockAppointments, total: mockTotal ?? mockAppointments.length },
    isLoading: false,
    error: null,
    refetch: jest.fn()
  }),
  useCancelAppointment: () => idleMutation,
  useCompleteAppointment: () => idleMutation,
  useConfirmAppointment: () => idleMutation,
  useMarkAbsentAppointment: () => idleMutation,
  useReleaseAppointment: () => idleMutation,
  useRescheduleAppointment: () => idleMutation
}))

jest.mock('../hooks/useManagedStaff', () => ({
  useManagedStaff: () => ({
    data: [{ id: 'st-1', displayName: 'Ana Gomez', isActive: true, schedules: [] }],
    isLoading: false,
    error: null
  })
}))

jest.mock('../hooks/useStores', () => ({
  useStoreSettings: () => ({
    data: { name: 'Peluqueria Sol', slug: 'sol', business_hours: mockBusinessHours }
  })
}))

const mockUser = { role: 'store_admin', is_global_admin: false, public_id: 'adm-1' }
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

const chooseView = (label: 'Dia' | 'Semana' | 'Mes' | 'Lista') => {
  fireEvent.click(screen.getByRole('button', { name: label }))
}

/** Celda de un dia en las vistas semana y mes, por su rotulo `dd/MM`. */
const dayCell = (label: string) => {
  const cell = screen.getByText(label).parentElement?.parentElement
  if (!(cell instanceof HTMLElement)) throw new Error(`No encontre la celda del ${label}`)
  return cell
}

const timelinePanel = () => {
  const panel = screen.getByRole('heading', { name: 'Bloqueos y ausencias' }).parentElement
  if (!(panel instanceof HTMLElement)) throw new Error('No encontre el panel de bloqueos')
  return panel
}

const arrow = (container: HTMLElement, direction: 'left' | 'right') => {
  const button = container.querySelector(`.lucide-chevron-${direction}`)?.closest('button')
  if (!button) throw new Error(`No encontre la flecha ${direction}`)
  return button
}

/** `a` aparece antes que `b` en el documento. */
const precedes = (a: HTMLElement, b: HTMLElement) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

const firstByText = (text: string) => {
  const [first] = screen.getAllByText(text)
  if (!first) throw new Error(`No encontre ${text}`)
  return first
}

describe('CalendarContainer - vistas, orden y navegacion (F11c-08)', () => {
  beforeEach(() => {
    // Domingo 20/09/2026, 12:30 en Argentina.
    jest.useFakeTimers({ now: new Date('2026-09-20T15:30:00.000Z') })
    mockDeleteBlock.mockReset()
    mockAppointments = []
    mockBlocks = []
    mockTotal = null
    mockBusinessHours = { sun: [{ open: '09:00', close: '21:00' }] }
    mockUser.role = 'store_admin'
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  describe('agrupan por dia argentino', () => {
    // 01:30 UTC del 15 es 22:30 del 14 en Argentina.
    const lateNight = () =>
      appointmentOf(
        'appt-late',
        'Nora Tarde',
        '2026-09-15T01:30:00.000Z',
        '2026-09-15T02:30:00.000Z'
      )

    it('semana: el turno de las 22:30 del 14 cae en la celda del 14, no del 15', () => {
      mockAppointments = [lateNight()]
      render(<CalendarContainer />)
      chooseView('Semana')

      expect(within(dayCell('14/09')).getByText('Nora Tarde')).toBeInTheDocument()
      expect(within(dayCell('15/09')).queryByText('Nora Tarde')).not.toBeInTheDocument()
      expect(within(dayCell('15/09')).getByText('Sin eventos')).toBeInTheDocument()
    })

    it('mes: el turno de las 22:30 del 14 cae en la celda del 14, no del 15', () => {
      mockAppointments = [lateNight()]
      render(<CalendarContainer />)
      chooseView('Mes')

      expect(within(dayCell('14/09')).getByText('Nora Tarde')).toBeInTheDocument()
      expect(within(dayCell('15/09')).queryByText('Nora Tarde')).not.toBeInTheDocument()
    })

    it('lista: muestra los eventos del rango en orden cronologico y en hora argentina', () => {
      mockAppointments = [
        appointmentOf(
          'appt-b',
          'Bruno Despues',
          '2026-09-23T13:00:00.000Z',
          '2026-09-23T14:00:00.000Z'
        ),
        appointmentOf(
          'appt-a',
          'Alba Antes',
          '2026-09-21T01:30:00.000Z',
          '2026-09-21T02:30:00.000Z'
        )
      ]
      render(<CalendarContainer />)
      chooseView('Lista')

      expect(precedes(screen.getByText('Alba Antes'), screen.getByText('Bruno Despues'))).toBe(true)
      expect(screen.getByText('22:30 - 23:30 · Ana Gomez')).toBeInTheDocument()
      expect(screen.getByText('10:00 - 11:00 · Ana Gomez')).toBeInTheDocument()
    })
  })

  it('mes muestra cuatro eventos por dia y "+N eventos" con el resto', () => {
    mockAppointments = [1, 2, 3, 4, 5, 6].map((n) =>
      appointmentOf(
        `appt-${n}`,
        `Cliente ${n}`,
        `2026-09-15T${10 + n}:00:00.000Z`,
        `2026-09-15T${10 + n}:30:00.000Z`
      )
    )
    render(<CalendarContainer />)
    chooseView('Mes')

    const cell = within(dayCell('15/09'))
    for (const n of [1, 2, 3, 4]) expect(cell.getByText(`Cliente ${n}`)).toBeInTheDocument()
    expect(cell.queryByText('Cliente 5')).not.toBeInTheDocument()
    expect(cell.queryByText('Cliente 6')).not.toBeInTheDocument()
    expect(cell.getByText('+2 eventos')).toBeInTheDocument()
  })

  it('semana muestra todos los eventos del dia, sin "+N eventos"', () => {
    mockAppointments = [1, 2, 3, 4, 5, 6].map((n) =>
      appointmentOf(
        `appt-${n}`,
        `Cliente ${n}`,
        `2026-09-15T${10 + n}:00:00.000Z`,
        `2026-09-15T${10 + n}:30:00.000Z`
      )
    )
    render(<CalendarContainer />)
    chooseView('Semana')

    const cell = within(dayCell('15/09'))
    for (const n of [1, 2, 3, 4, 5, 6]) expect(cell.getByText(`Cliente ${n}`)).toBeInTheDocument()
    expect(cell.queryByText(/eventos$/)).not.toBeInTheDocument()
  })

  it('a igual horario va primero el bloqueo, despues la ausencia y al final el turno', () => {
    mockAppointments = [
      appointmentOf(
        'appt-ok',
        'Luis Presente',
        '2026-09-20T17:00:00.000Z',
        '2026-09-20T18:00:00.000Z'
      ),
      appointmentOf(
        'appt-abs',
        'Pedro Ausente',
        '2026-09-20T17:00:00.000Z',
        '2026-09-20T18:00:00.000Z',
        'absent'
      )
    ]
    mockBlocks = [
      blockOf('blk-1', 'Tramite', '2026-09-20T17:00:00.000Z', '2026-09-20T18:00:00.000Z')
    ]
    render(<CalendarContainer />)
    chooseView('Lista')

    const block = firstByText('Tramite')
    const absence = firstByText('Pedro Ausente')
    const appointment = firstByText('Luis Presente')
    expect(precedes(block, absence)).toBe(true)
    expect(precedes(absence, appointment)).toBe(true)
  })

  it('un turno "absent" se clasifica como ausencia: va al panel y no ofrece acciones', () => {
    mockAppointments = [
      appointmentOf(
        'appt-ok',
        'Luis Presente',
        '2026-09-20T17:00:00.000Z',
        '2026-09-20T18:00:00.000Z'
      ),
      appointmentOf(
        'appt-abs',
        'Pedro Ausente',
        '2026-09-20T18:00:00.000Z',
        '2026-09-20T19:00:00.000Z',
        'absent'
      )
    ]
    render(<CalendarContainer />)

    const panel = within(timelinePanel())
    expect(panel.getByText('Pedro Ausente')).toBeInTheDocument()
    expect(panel.getByText('Ausencia')).toBeInTheDocument()
    expect(panel.queryByText('Luis Presente')).not.toBeInTheDocument()

    const cardOf = (name: string) => {
      const card = firstByText(name).closest('.absolute')
      if (!(card instanceof HTMLElement)) throw new Error(`No encontre la tarjeta de ${name}`)
      return within(card)
    }
    expect(
      cardOf('Luis Presente').getByRole('button', { name: 'Cancelar turno' })
    ).toBeInTheDocument()
    expect(cardOf('Pedro Ausente').queryAllByRole('button')).toHaveLength(0)
  })

  it('avisa "Se muestran N de M turnos" cuando la agenda vino recortada', () => {
    mockAppointments = [
      appointmentOf(
        'appt-1',
        'Luis Presente',
        '2026-09-20T17:00:00.000Z',
        '2026-09-20T18:00:00.000Z'
      )
    ]
    mockTotal = 5
    render(<CalendarContainer />)

    expect(
      screen.getByText(
        'Se muestran 1 de 5 turnos de este rango. Pasá a la vista de día o de semana para verlos todos.'
      )
    ).toHaveAttribute('role', 'status')
  })

  it('sin recorte no hay aviso de turnos', () => {
    mockAppointments = [
      appointmentOf(
        'appt-1',
        'Luis Presente',
        '2026-09-20T17:00:00.000Z',
        '2026-09-20T18:00:00.000Z'
      )
    ]
    render(<CalendarContainer />)

    expect(screen.queryByText(/^Se muestran/)).not.toBeInTheDocument()
  })

  it('"Editar" precarga el bloqueo en el formulario, con su dia y hora argentinos', () => {
    // 00:30 UTC del 16 es 21:30 del 15 en Argentina.
    mockBlocks = [
      blockOf('blk-1', 'Tramite', '2026-09-16T00:30:00.000Z', '2026-09-16T01:30:00.000Z')
    ]
    render(<CalendarContainer />)
    chooseView('Semana')

    const valueOf = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).value

    expect(valueOf('Motivo interno')).toBe('No atender')
    fireEvent.click(within(timelinePanel()).getByRole('button', { name: 'Editar' }))

    expect(valueOf('Motivo interno')).toBe('Tramite')
    expect(valueOf('Fecha')).toBe('2026-09-15')
    expect(valueOf('Desde')).toBe('21:30')
    expect(valueOf('Hasta')).toBe('22:30')
    expect(screen.getByRole('button', { name: 'Actualizar bloqueo' })).toBeInTheDocument()
  })

  it('"Desactivar" llama al mutation con el bloqueo y avisa "Bloqueo desactivado"', async () => {
    mockDeleteBlock.mockResolvedValue(undefined)
    mockBlocks = [
      blockOf('blk-1', 'Tramite', '2026-09-20T17:00:00.000Z', '2026-09-20T18:00:00.000Z')
    ]
    render(<CalendarContainer />)

    fireEvent.click(within(timelinePanel()).getByRole('button', { name: 'Desactivar' }))

    await waitFor(() => expect(mockDeleteBlock).toHaveBeenCalledWith('blk-1'))
    expect(await screen.findByText('Bloqueo desactivado')).toBeInTheDocument()
  })

  // 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
  // verse deshabilitada (FF-15). PATCH y DELETE /appointment-blocks/{id} no
  // estan en SUSPENSION_ALLOWED_WRITES.
  it('con la tienda suspendida "Editar" y "Desactivar" quedan deshabilitados con el motivo', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    mockBlocks = [
      blockOf('blk-1', 'Tramite', '2026-09-20T17:00:00.000Z', '2026-09-20T18:00:00.000Z')
    ]
    render(<CalendarContainer />)

    for (const name of ['Editar', 'Desactivar']) {
      const button = within(timelinePanel()).getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', 'Tienda suspendida')
    }
    fireEvent.click(within(timelinePanel()).getByRole('button', { name: 'Desactivar' }))
    expect(mockDeleteBlock).not.toHaveBeenCalled()
    // Tocar el bloqueo en la vista de dia tampoco abre su edicion.
    expect(screen.getByRole('button', { name: /^Tramite/ })).toBeDisabled()
  })

  it('el hueco cerrado de la jornada partida arranca colapsado y se expande', () => {
    mockBusinessHours = {
      sun: [
        { open: '09:00', close: '13:00' },
        { open: '16:00', close: '20:00' }
      ]
    }
    render(<CalendarContainer />)

    const gap = screen.getByTitle('Cerrado 13:00 - 16:00')
    expect(gap).toHaveAttribute('aria-expanded', 'false')
    expect(gap).toHaveTextContent('▸ Cerrado')

    fireEvent.click(gap)

    expect(screen.getByTitle('Cerrado 13:00 - 16:00')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTitle('Cerrado 13:00 - 16:00')).toHaveTextContent('▾ Cerrado')
  })

  // QA 2026-10-02: la cabecera salia en ingles ('20 de September').
  it.each([
    ['Dia', '19 de septiembre', '21 de septiembre'],
    ['Semana', '13 de septiembre', '27 de septiembre'],
    ['Mes', '21 de agosto', '20 de octubre']
  ] as const)('la vista %s salta hacia atras a %s y hacia adelante a %s', (view, back, forward) => {
    const { container } = render(<CalendarContainer />)
    chooseView(view)
    expect(screen.getByText('20 de septiembre')).toBeInTheDocument()

    fireEvent.click(arrow(container, 'left'))
    expect(screen.getByText(back)).toBeInTheDocument()

    fireEvent.click(arrow(container, 'right'))
    fireEvent.click(arrow(container, 'right'))
    expect(screen.getByText(forward)).toBeInTheDocument()
  })

  it('la lista sin eventos dice "No hay eventos para el rango seleccionado."', () => {
    render(<CalendarContainer />)
    chooseView('Lista')

    expect(screen.getByText('No hay eventos para el rango seleccionado.')).toBeInTheDocument()
  })
})
