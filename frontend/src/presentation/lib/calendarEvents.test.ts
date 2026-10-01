import { Appointment } from '@domain/entities/Appointment'

import type { AppointmentBlock } from '@application/services/AppointmentBlocksService'

import {
  buildUnifiedEvents,
  eventPriority,
  groupEventsByDay,
  toInstantIso,
  type UnifiedCalendarEvent
} from './calendarEvents'
import {
  resetUnreadableInstantReports,
  setUnreadableInstantReporter
} from './reportUnreadableInstant'

const appointmentOf = (
  id: string,
  clientName: string,
  startsAt: string,
  endsAt: string,
  overrides: { status?: string; staffName?: string | null; staffId?: string } = {}
) =>
  Appointment.fromPrimitives({
    public_id: id,
    service_id: 'svc-1',
    service_name: 'Corte',
    staff_id: overrides.staffId ?? 'st-1',
    staff_name: overrides.staffName === undefined ? 'Ana Gomez' : overrides.staffName,
    client_name: clientName,
    client_phone: null,
    starts_at: startsAt,
    ends_at: endsAt,
    status: overrides.status ?? 'confirmed',
    notes: null
  })

const blockOf = (publicId: string, startsAt: string, endsAt: string, staffId = 'st-1') =>
  ({
    public_id: publicId,
    staff_id: staffId,
    starts_at: startsAt,
    ends_at: endsAt,
    reason: 'Tramite',
    is_active: true
  }) satisfies AppointmentBlock

const staffMembers = [
  { id: 'st-1', displayName: 'Ana Gomez' },
  { id: 'st-2', displayName: 'Beto Diaz' }
]

const START = '2026-09-20T17:00:00.000Z'
const END = '2026-09-20T18:00:00.000Z'

afterEach(() => {
  resetUnreadableInstantReports()
})

describe('toInstantIso', () => {
  it('devuelve el ISO UTC de un instante valido', () => {
    expect(toInstantIso(new Date(START))).toBe(START)
  })

  it('devuelve cadena vacia en vez de lanzar con una fecha invalida', () => {
    expect(toInstantIso(new Date('no-es-fecha'))).toBe('')
  })
})

describe('eventPriority', () => {
  it('ordena bloqueo, ausencia y turno', () => {
    const [block, absence, appointment] = buildUnifiedEvents({
      appointments: [
        appointmentOf('appt-ok', 'Luis', START, END),
        appointmentOf('appt-abs', 'Pedro', START, END, { status: 'absent' })
      ],
      blocks: [blockOf('blk-1', START, END)],
      staffMembers
    })
    if (!block || !absence || !appointment) throw new Error('Faltan eventos')

    expect(eventPriority(block)).toBe(0)
    expect(eventPriority(absence)).toBe(1)
    expect(eventPriority(appointment)).toBe(2)
  })
})

describe('buildUnifiedEvents', () => {
  it('ordena por inicio y, a igual inicio, bloqueo, ausencia y turno', () => {
    const events = buildUnifiedEvents({
      appointments: [
        appointmentOf('appt-late', 'Tarde', '2026-09-20T19:00:00.000Z', '2026-09-20T20:00:00.000Z'),
        appointmentOf('appt-ok', 'Luis', START, END),
        appointmentOf('appt-abs', 'Pedro', START, END, { status: 'absent' }),
        appointmentOf('appt-early', 'Temprano', '2026-09-20T12:00:00.000Z', START)
      ],
      blocks: [blockOf('blk-1', START, END)],
      staffMembers
    })

    expect(events.map((event) => event.id)).toEqual([
      'appt-early',
      'blk-1',
      'appt-abs',
      'appt-ok',
      'appt-late'
    ])
  })

  it('clasifica "absent" como ausencia y el resto de los estados como turno', () => {
    const events = buildUnifiedEvents({
      appointments: [
        appointmentOf('appt-abs', 'Pedro', START, END, { status: 'absent' }),
        appointmentOf('appt-done', 'Luis', START, END, { status: 'completed' })
      ],
      blocks: [],
      staffMembers
    })

    expect(events.map((event) => [event.id, event.type])).toEqual([
      ['appt-abs', 'absence'],
      ['appt-done', 'appointment']
    ])
  })

  it('arma el bloqueo con su motivo, el profesional y el estado "blocked"', () => {
    const [event] = buildUnifiedEvents({
      appointments: [],
      blocks: [blockOf('blk-1', START, END, 'st-2')],
      staffMembers
    })

    expect(event).toEqual({
      id: 'blk-1',
      type: 'block',
      staffId: 'st-2',
      staffName: 'Beto Diaz',
      title: 'Tramite',
      subtitle: 'Bloqueo de agenda',
      startsAt: new Date(START),
      endsAt: new Date(END),
      status: 'blocked'
    })
  })

  it('usa el nombre del backend, despues el del listado y al final "Profesional"', () => {
    const events = buildUnifiedEvents({
      appointments: [
        appointmentOf('appt-backend', 'A', START, END, { staffName: 'Nombre Backend' }),
        appointmentOf('appt-list', 'B', START, END, { staffName: null, staffId: 'st-2' }),
        appointmentOf('appt-none', 'C', START, END, { staffName: null, staffId: 'st-9' })
      ],
      blocks: [blockOf('blk-none', START, END, 'st-9')],
      staffMembers
    })

    expect(Object.fromEntries(events.map((event) => [event.id, event.staffName]))).toEqual({
      'appt-backend': 'Nombre Backend',
      'appt-list': 'Beto Diaz',
      'appt-none': 'Profesional',
      'blk-none': 'Profesional'
    })
  })

  it('reporta un estado desconocido sin dejar de mostrar el turno (F8-03)', () => {
    const reporter = jest.fn()
    setUnreadableInstantReporter(reporter)

    const events = buildUnifiedEvents({
      appointments: [
        appointmentOf('appt-new', 'Luis', START, END, { status: 'on_hold' }),
        appointmentOf('appt-ok', 'Pedro', START, END)
      ],
      blocks: [],
      staffMembers
    })

    expect(reporter).toHaveBeenCalledTimes(1)
    expect(reporter).toHaveBeenCalledWith('Estado desconocido en agenda: on_hold')
    expect(events.find((event) => event.id === 'appt-new')).toMatchObject({
      type: 'appointment',
      status: 'on_hold'
    })
  })
})

describe('groupEventsByDay', () => {
  const eventAt = (id: string, startsAt: string): UnifiedCalendarEvent => ({
    id,
    type: 'block',
    staffId: 'st-1',
    staffName: 'Ana Gomez',
    title: 'Tramite',
    subtitle: 'Bloqueo de agenda',
    startsAt: new Date(startsAt),
    endsAt: new Date(startsAt),
    status: 'blocked'
  })

  it('agrupa por dia argentino, no por dia UTC (regla 24)', () => {
    const byDay = groupEventsByDay([
      // 01:30 UTC del 15 es 22:30 del 14 en Argentina.
      eventAt('late', '2026-09-15T01:30:00.000Z'),
      // 03:00 UTC del 15 es la medianoche del 15 en Argentina.
      eventAt('midnight', '2026-09-15T03:00:00.000Z'),
      eventAt('noon', '2026-09-15T15:00:00.000Z')
    ])

    expect([...byDay.keys()]).toEqual(['2026-09-14', '2026-09-15'])
    expect(byDay.get('2026-09-14')?.map((event) => event.id)).toEqual(['late'])
    expect(byDay.get('2026-09-15')?.map((event) => event.id)).toEqual(['midnight', 'noon'])
  })

  it('un evento con fecha invalida no rompe la agrupacion', () => {
    const byDay = groupEventsByDay([
      eventAt('broken', 'no-es-fecha'),
      eventAt('ok', '2026-09-15T15:00:00.000Z')
    ])

    expect(byDay.get('2026-09-15')?.map((event) => event.id)).toEqual(['ok'])
    expect(byDay.get('')?.map((event) => event.id)).toEqual(['broken'])
  })

  it('sin eventos devuelve un mapa vacio', () => {
    expect(groupEventsByDay([]).size).toBe(0)
  })
})
