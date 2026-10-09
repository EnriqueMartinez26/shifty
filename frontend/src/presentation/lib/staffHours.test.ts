import { buildDayGrid, parseHhMm, SLOT_HEIGHT_PX, SLOT_MINUTES } from './calendarGrid'
import {
  mondayBasedWeekday,
  offHoursSegments,
  storeRangesFor,
  workingRangesFor
} from './staffHours'

const hhmm = (hour: number, minute = 0) => hour * 60 + minute
const range = (from: number, to: number) => ({ startMinutes: hhmm(from), endMinutes: hhmm(to) })
const px = (minutes: number) => (minutes / SLOT_MINUTES) * SLOT_HEIGHT_PX

// Lunes = 0, como `schedules.day_of_week` del backend.
const MONDAY = 0
const TUESDAY = 1

describe('parseHhMm con segundos (franjas del profesional)', () => {
  it('lee HH:MM:SS como llega un `time` de Pydantic', () => {
    expect(parseHhMm('09:00:00')).toBe(540)
    expect(parseHhMm('18:30:00')).toBe(1110)
  })

  it('rechaza segundos imposibles', () => {
    expect(parseHhMm('09:00:75')).toBeNull()
    expect(parseHhMm('09:00:')).toBeNull()
  })
})

describe('mondayBasedWeekday', () => {
  it('cuenta la semana como el backend: lunes 0, domingo 6', () => {
    expect(mondayBasedWeekday(new Date(2026, 8, 28))).toBe(0) // lunes 28/09/2026
    expect(mondayBasedWeekday(new Date(2026, 8, 27))).toBe(6) // domingo
  })
})

describe('storeRangesFor', () => {
  const businessHours = { mon: [{ open: '09:00', close: '18:00' }], sun: [] }

  it('devuelve el horario comercial de ese dia', () => {
    expect(storeRangesFor(businessHours, MONDAY)).toEqual([range(9, 18)])
  })

  it('un dia sin horario es un dia cerrado, no un dato que falta', () => {
    expect(storeRangesFor(businessHours, TUESDAY)).toEqual([])
    expect(storeRangesFor(businessHours, 6)).toEqual([])
  })

  it('sin la ficha del local todavia no se sabe: null', () => {
    expect(storeRangesFor(undefined, MONDAY)).toBeNull()
  })
})

describe('workingRangesFor (D-20260929-01, misma regla que working_hours.py)', () => {
  const store = [range(9, 18)]

  it('usa las franjas propias del dia, en HH:MM:SS', () => {
    const schedules = [
      { dayOfWeek: MONDAY, startTime: '10:00:00', endTime: '14:00:00' },
      { dayOfWeek: MONDAY, startTime: '16:00:00', endTime: '20:00:00' },
      { dayOfWeek: TUESDAY, startTime: '08:00:00', endTime: '12:00:00' }
    ]
    expect(workingRangesFor(schedules, MONDAY, store)).toEqual([range(10, 14), range(16, 20)])
  })

  it('sin NINGUNA franja cargada cae al horario del local', () => {
    expect(workingRangesFor([], MONDAY, store)).toEqual(store)
  })

  it('con franjas pero ninguna ese dia no atiende, aunque el local abra', () => {
    const schedules = [{ dayOfWeek: TUESDAY, startTime: '08:00:00', endTime: '12:00:00' }]
    expect(workingRangesFor(schedules, MONDAY, store)).toEqual([])
  })

  it('sin franjas y sin la ficha del local: todavia no se sabe', () => {
    expect(workingRangesFor([], MONDAY, null)).toBeNull()
  })

  it('una franja ilegible no inventa horario', () => {
    const schedules = [{ dayOfWeek: MONDAY, startTime: 'manana', endTime: '12:00:00' }]
    expect(workingRangesFor(schedules, MONDAY, store)).toEqual([])
  })
})

describe('offHoursSegments', () => {
  it('pinta lo que queda fuera de las franjas dentro de cada banda abierta', () => {
    // Grilla 09-18; el profesional atiende 10-14.
    const grid = buildDayGrid([range(9, 18)])
    expect(offHoursSegments(grid, [range(10, 14)])).toEqual([
      { topPx: 0, heightPx: px(60) },
      { topPx: px(5 * 60), heightPx: px(4 * 60) }
    ])
  })

  it('un profesional que no atiende ese dia queda todo fuera de horario', () => {
    const grid = buildDayGrid([range(9, 13)])
    expect(offHoursSegments(grid, [])).toEqual([{ topPx: 0, heightPx: px(4 * 60) }])
  })

  it('quien atiende toda la grilla no tiene tramos fuera de horario', () => {
    const grid = buildDayGrid([range(9, 13), range(17, 21)])
    expect(offHoursSegments(grid, [range(9, 13), range(17, 21)])).toEqual([])
  })

  it('no pinta sobre los huecos colapsados: esos ya dicen "Cerrado"', () => {
    // Jornada partida 09-13 / 17-21 con el hueco colapsado en el medio.
    const grid = buildDayGrid([range(9, 13), range(17, 21)])
    const [morning, gap, afternoon] = grid.bands
    if (!morning || !gap || !afternoon) throw new Error('grilla inesperada')
    expect(offHoursSegments(grid, [range(9, 13)])).toEqual([
      { topPx: afternoon.topPx, heightPx: afternoon.heightPx }
    ])
  })
})
