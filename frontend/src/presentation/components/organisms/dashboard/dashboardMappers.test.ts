import type { UpcomingAppointment } from '@application/services/DashboardService'
import type {
  ProfessionalReportItem,
  ReportAppointmentItem,
  ReportTopServiceItem
} from '@application/services/ReportsService'

import {
  getAppointmentTone,
  getTopProfessional,
  mapAgenda,
  mapTopServices,
  mapTransactions
} from './dashboardMappers'

// F11b-09 (cuarta tajada): los mapeos y el mapa de estados salieron de
// `Dashboard.tsx`. Los esperados son literales; los montos pasan por
// `normalizeSpaces` porque Intl separa simbolo y numero con un espacio duro.

const normalizeSpaces = (value: string) => value.replace(/\s+/g, ' ')

describe('getAppointmentTone', () => {
  it.each([
    ['pending', 'warning'],
    ['pending_payment', 'warning'],
    ['confirmed', 'success'],
    ['completed', 'success'],
    ['cancelled', 'danger'],
    ['absent', 'danger'],
    ['expired', 'danger']
  ])('el estado %s se pinta %s', (status, tone) => {
    expect(getAppointmentTone(status)).toBe(tone)
  })

  it('un estado desconocido o con otra capitalizacion cae en neutral', () => {
    expect(getAppointmentTone('rejected')).toBe('neutral')
    expect(getAppointmentTone('CONFIRMED')).toBe('neutral')
    expect(getAppointmentTone('')).toBe('neutral')
  })
})

const professional = (overrides: Partial<ProfessionalReportItem>): ProfessionalReportItem => ({
  staff_id: 's1',
  staff_name: 'Ana',
  appointments: 0,
  completed_appointments: 0,
  confirmed_appointments: 0,
  absent_appointments: 0,
  cancelled_appointments: 0,
  used_minutes: 0,
  used_hours: 0,
  available_minutes: 0,
  available_hours: 0,
  blocked_minutes: 0,
  blocked_hours: 0,
  occupancy_rate: 0,
  revenue: 0,
  ...overrides
})

describe('getTopProfessional', () => {
  it('devuelve undefined sin lista o con lista vacia', () => {
    expect(getTopProfessional(undefined)).toBeUndefined()
    expect(getTopProfessional([])).toBeUndefined()
  })

  it('elige al de mayor ocupacion', () => {
    const items = [
      professional({ staff_id: 's1', occupancy_rate: 40, revenue: 900 }),
      professional({ staff_id: 's2', occupancy_rate: 75, revenue: 100 }),
      professional({ staff_id: 's3', occupancy_rate: 60, revenue: 500 })
    ]

    expect(getTopProfessional(items)?.staff_id).toBe('s2')
  })

  it('desempata por mayor facturacion cuando la ocupacion es igual', () => {
    const items = [
      professional({ staff_id: 's1', occupancy_rate: 70, revenue: 100 }),
      professional({ staff_id: 's2', occupancy_rate: 70, revenue: 300 }),
      professional({ staff_id: 's3', occupancy_rate: 70, revenue: 200 })
    ]

    expect(getTopProfessional(items)?.staff_id).toBe('s2')
  })

  it('ante un empate total conserva al primero de la lista', () => {
    const items = [
      professional({ staff_id: 's1', occupancy_rate: 70, revenue: 100 }),
      professional({ staff_id: 's2', occupancy_rate: 70, revenue: 100 })
    ]

    expect(getTopProfessional(items)?.staff_id).toBe('s1')
  })

  it('no reordena la lista que recibe', () => {
    const items = [
      professional({ staff_id: 's1', occupancy_rate: 10 }),
      professional({ staff_id: 's2', occupancy_rate: 90 })
    ]

    getTopProfessional(items)

    expect(items.map((item) => item.staff_id)).toEqual(['s1', 's2'])
  })
})

const upcoming = (overrides: Partial<UpcomingAppointment>): UpcomingAppointment => ({
  public_id: 'apt-1',
  starts_at: '2026-09-30T13:30:00Z',
  status: 'confirmed',
  service_name: 'Corte clasico',
  staff_name: 'Ana',
  client_name: 'Lucia Perez',
  ...overrides
})

describe('mapAgenda', () => {
  it('devuelve una lista vacia sin turnos', () => {
    expect(mapAgenda(undefined)).toEqual([])
    expect(mapAgenda([])).toEqual([])
  })

  it('mapea cada campo con el dia y la hora de Argentina y el estado en castellano', () => {
    expect(mapAgenda([upcoming({})])).toEqual([
      {
        id: 'apt-1',
        day: '30/09',
        time: '10:30',
        title: 'Lucia Perez',
        subtitle: 'Corte clasico - Ana',
        status: 'Confirmado',
        tone: 'success'
      }
    ])
  })

  // 2026-10-02, QA en navegador: "Proximos movimientos" mezclaba turnos de
  // varios dias sin fecha y en el orden en que llegaban.
  it('ordena por inicio y lleva el dia de cada turno; un estado desconocido queda crudo', () => {
    const result = mapAgenda([
      upcoming({ public_id: 'c', starts_at: '2026-10-01T12:00:00Z', status: 'pending' }),
      upcoming({ public_id: 'b', starts_at: '2026-09-30T15:00:00Z', status: 'pending' }),
      upcoming({ public_id: 'a', starts_at: '2026-09-30T12:00:00Z', status: 'rejected' })
    ])

    expect(result.map((item) => item.id)).toEqual(['a', 'b', 'c'])
    expect(result.map((item) => item.day)).toEqual(['30/09', '30/09', '01/10'])
    expect(result.map((item) => item.time)).toEqual(['09:00', '12:00', '09:00'])
    expect(result.map((item) => item.status)).toEqual(['rejected', 'Pendiente', 'Pendiente'])
    expect(result.map((item) => item.tone)).toEqual(['neutral', 'warning', 'warning'])
  })

  it('no reordena la lista que recibe', () => {
    const received = [
      upcoming({ public_id: 'b', starts_at: '2026-09-30T15:00:00Z' }),
      upcoming({ public_id: 'a', starts_at: '2026-09-30T12:00:00Z' })
    ]
    mapAgenda(received)
    expect(received.map((item) => item.public_id)).toEqual(['b', 'a'])
  })
})

const topService = (overrides: Partial<ReportTopServiceItem>): ReportTopServiceItem => ({
  service_id: 'sv1',
  service_name: 'Corte clasico',
  appointments: 12,
  completed_appointments: 10,
  revenue: 36000,
  ...overrides
})

describe('mapTopServices', () => {
  it('devuelve una lista vacia sin servicios', () => {
    expect(mapTopServices(undefined)).toEqual([])
    expect(mapTopServices([])).toEqual([])
  })

  it('mapea nombre, facturacion en pesos y cantidad de reservas', () => {
    const [row] = mapTopServices([topService({})])

    expect(row).toEqual({
      id: 'sv1',
      label: 'Corte clasico',
      value: expect.any(String),
      detail: '12 reservas'
    })
    expect(normalizeSpaces(String(row?.value))).toBe('$ 36.000')
  })

  it('separa los miles de las reservas', () => {
    const [row] = mapTopServices([topService({ appointments: 1500 })])

    expect(row?.detail).toBe('1.500 reservas')
  })

  it('se queda con los primeros cuatro, sin reordenar', () => {
    const items = ['a', 'b', 'c', 'd', 'e'].map((id, index) =>
      topService({ service_id: id, revenue: (index + 1) * 100 })
    )

    expect(mapTopServices(items).map((row) => row.id)).toEqual(['a', 'b', 'c', 'd'])
  })
})

const appointment = (overrides: Partial<ReportAppointmentItem>): ReportAppointmentItem => ({
  public_id: 'apt-1',
  starts_at: '2026-09-15T12:00:00Z',
  ends_at: '2026-09-15T13:00:00Z',
  status: 'completed',
  service_name: 'Corte clasico',
  staff_name: 'Ana',
  client_name: 'Lucia Perez',
  service_price: 4500,
  ...overrides
})

describe('mapTransactions', () => {
  it('devuelve una lista vacia sin turnos', () => {
    expect(mapTransactions(undefined)).toEqual([])
    expect(mapTransactions([])).toEqual([])
  })

  it('mapea cada campo con dia, mes y hora de Argentina y el monto en pesos', () => {
    const [row] = mapTransactions([appointment({})])

    expect(row).toEqual({
      id: 'apt-1',
      title: 'Lucia Perez',
      subtitle: 'Corte clasico - 15/09 09:00',
      amount: expect.any(String),
      // QA 2026-10-02: el estado salia crudo (COMPLETED con uppercase).
      status: 'Completado',
      tone: 'success'
    })
    expect(normalizeSpaces(String(row?.amount))).toBe('$ 4.500')
  })

  it('un turno sin precio se muestra como cero pesos', () => {
    const [row] = mapTransactions([appointment({ service_price: 0 })])

    expect(normalizeSpaces(String(row?.amount))).toBe('$ 0')
  })

  it('ordena del mas reciente al mas antiguo', () => {
    const result = mapTransactions([
      appointment({ public_id: 'old', starts_at: '2026-09-10T12:00:00Z' }),
      appointment({ public_id: 'new', starts_at: '2026-09-20T12:00:00Z' }),
      appointment({ public_id: 'mid', starts_at: '2026-09-15T12:00:00Z' })
    ])

    expect(result.map((row) => row.id)).toEqual(['new', 'mid', 'old'])
  })

  it('se queda con los seis mas recientes', () => {
    const items = [1, 2, 3, 4, 5, 6, 7].map((day) =>
      appointment({ public_id: `d${day}`, starts_at: `2026-09-0${day}T12:00:00Z` })
    )

    expect(mapTransactions(items).map((row) => row.id)).toEqual([
      'd7',
      'd6',
      'd5',
      'd4',
      'd3',
      'd2'
    ])
  })

  it('no reordena la lista que recibe', () => {
    const items = [
      appointment({ public_id: 'old', starts_at: '2026-09-10T12:00:00Z' }),
      appointment({ public_id: 'new', starts_at: '2026-09-20T12:00:00Z' })
    ]

    mapTransactions(items)

    expect(items.map((item) => item.public_id)).toEqual(['old', 'new'])
  })

  it('pinta cada estado con su tono y deja neutral el desconocido', () => {
    const result = mapTransactions([
      appointment({ public_id: 'a', starts_at: '2026-09-04T12:00:00Z', status: 'cancelled' }),
      appointment({ public_id: 'b', starts_at: '2026-09-03T12:00:00Z', status: 'pending_payment' }),
      appointment({ public_id: 'c', starts_at: '2026-09-02T12:00:00Z', status: 'rejected' })
    ])

    expect(result.map((row) => row.tone)).toEqual(['danger', 'warning', 'neutral'])
  })
})
