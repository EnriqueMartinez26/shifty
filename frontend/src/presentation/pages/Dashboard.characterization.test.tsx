import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'

import { formatCurrency } from '@shared/utils/currency'

import Dashboard from './Dashboard'

// Caracterizacion de `Dashboard`: red de seguridad de las cuatro tajadas de
// F11b-09, que mueven los componentes de presentacion a `organisms/dashboard/`.
// No es un test de diseno: si una tajada cambia un texto, un orden, un color de
// estado o el destino de un clic, este archivo falla. Cada componente movido
// tiene ademas su test de props en `organisms/dashboard/<Componente>.test.tsx`,
// que fija las ramas y los literales de estilo que la pagina no ve. Cuando la
// extraccion termine (cuarta tajada) y la pagina quede solo con contenedor,
// hooks y mapeo de datos, estas expectativas se actualizan SOLO si cambio a
// proposito el comportamiento visible; lo que sea de un componente suelto se
// baja a su propio test y aca queda la pagina armada de punta a punta. Los hooks de
// datos se reemplazan por dobles que respetan el argumento `enabled` (una query
// deshabilitada de react-query devuelve `data: undefined`), asi tambien queda
// fijado que el rol gobierna que se consulta. Los graficos se reemplazan para no
// depender de recharts en jsdom.

type Scenario = {
  user: { role?: string; is_global_admin?: boolean }
  summary: { data?: object; isLoading: boolean; isError: boolean }
  flags: { data?: object; isSuccess: boolean }
  reports: { data?: object; isLoading: boolean }
  professionals: { data?: object }
  trend: { data?: object; isLoading: boolean }
  reconciliation?: object
  outbox?: object
  ledger?: object
}

const mockScenario: Scenario = {
  user: {},
  summary: { isLoading: false, isError: false },
  flags: { isSuccess: false },
  reports: { isLoading: false },
  professionals: {},
  trend: { isLoading: false },
  reconciliation: undefined,
  outbox: undefined,
  ledger: undefined
}

jest.mock('../components/organisms/dashboard/TrendChart', () => ({
  __esModule: true,
  default: ({ points, isLoading }: { points: unknown[]; isLoading: boolean }) => (
    <p>{`Grafico de tendencia: ${points.length} puntos, cargando ${String(isLoading)}`}</p>
  )
}))

jest.mock('../components/organisms/dashboard/SalesDonut', () => ({
  __esModule: true,
  default: ({ services, isLoading }: { services: unknown[]; isLoading: boolean }) => (
    <p>{`Grafico de ventas: ${services.length} servicios, cargando ${String(isLoading)}`}</p>
  )
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ token: 'token', user: mockScenario.user })
}))

jest.mock('../hooks/useDashboard', () => ({
  useDashboardSummary: (enabled = true) => ({
    ...mockScenario.summary,
    data: enabled ? mockScenario.summary.data : undefined
  })
}))

jest.mock('../hooks/useStores', () => ({
  useStoreFeatureFlags: () => mockScenario.flags
}))

jest.mock('../hooks/useReports', () => ({
  useReportSummary: (_from: string, _to: string, enabled = true) => ({
    ...mockScenario.reports,
    data: enabled ? mockScenario.reports.data : undefined
  }),
  useProfessionalReports: (_from: string, _to: string, enabled = true) => ({
    data: enabled ? mockScenario.professionals.data : undefined
  }),
  useReportTrend: (_months: number, enabled = true) => ({
    ...mockScenario.trend,
    data: enabled ? mockScenario.trend.data : undefined
  })
}))

jest.mock('../hooks/usePayments', () => ({
  useReconciliationSummary: (enabled = true) => ({
    data: enabled ? mockScenario.reconciliation : undefined
  }),
  useOutboxStats: (enabled = true) => ({ data: enabled ? mockScenario.outbox : undefined })
}))

jest.mock('../hooks/useLedger', () => ({
  useLedgerSummary: (enabled = true) => ({ data: enabled ? mockScenario.ledger : undefined })
}))

// Los pesos salen del mismo formateador de la app; se normaliza el espacio
// duro (U+00A0) porque Testing Library compara el texto del nodo ya normalizado.
const peso = (value: number) => formatCurrency(value).replace(/\s+/g, ' ')

const ADMIN_STATS = {
  appointments_today: 12,
  pending_confirmations: 3,
  occupancy_rate: 62.5,
  new_clients_last_30d: 18,
  weekly_revenue: 450000,
  revenue_trend: 8.4,
  average_appointment_minutes: 40
}

const ADMIN_SUMMARY = {
  stats: ADMIN_STATS,
  upcoming_appointments: [
    {
      public_id: 'apt-1',
      starts_at: '2026-09-30T13:30:00Z',
      status: 'confirmed',
      service_name: 'Corte clasico',
      staff_name: 'Martina Paz',
      client_name: 'Lucia Gomez'
    },
    {
      public_id: 'apt-2',
      starts_at: '2026-09-30T15:00:00Z',
      status: 'pending',
      service_name: 'Color',
      staff_name: 'Julian Rios',
      client_name: 'Sofia Diaz'
    }
  ]
}

const ADMIN_REPORTS = {
  from_date: '2026-09-23',
  to_date: '2026-09-30',
  stats: {
    total_appointments: 44,
    completed_appointments: 30,
    cancelled_appointments: 4,
    pending_appointments: 6,
    confirmed_appointments: 4,
    total_revenue: 980000,
    average_ticket: 15000
  },
  client_stats: { total_clients: 120, new_clients: 9, returning_clients: 22, inactive_clients: 5 },
  top_services: [
    {
      service_id: 's1',
      service_name: 'Corte clasico',
      appointments: 30,
      completed_appointments: 28,
      revenue: 600000
    },
    {
      service_id: 's2',
      service_name: 'Color',
      appointments: 10,
      completed_appointments: 9,
      revenue: 380000
    }
  ],
  top_clients: [],
  debt_summary: { outstanding_balance: 99999, debtors_count: 7, top_debtors: [] },
  appointments: [
    {
      public_id: 'rep-1',
      starts_at: '2026-09-28T14:00:00Z',
      ends_at: '2026-09-28T14:40:00Z',
      status: 'completed',
      service_name: 'Corte clasico',
      staff_name: 'Martina Paz',
      client_name: 'Ana Lopez',
      service_price: 15000
    },
    {
      public_id: 'rep-2',
      starts_at: '2026-09-29T16:30:00Z',
      ends_at: '2026-09-29T17:30:00Z',
      status: 'cancelled',
      service_name: 'Color',
      staff_name: 'Julian Rios',
      client_name: 'Bruno Saenz',
      service_price: 40000
    },
    {
      public_id: 'rep-3',
      starts_at: '2026-09-27T12:00:00Z',
      ends_at: '2026-09-27T12:30:00Z',
      status: 'confirmed',
      service_name: 'Barba',
      staff_name: 'Martina Paz',
      client_name: 'Carla Vega',
      service_price: 8000
    }
  ],
  has_more: false
}

const ADMIN_PROFESSIONALS = {
  from_date: '2026-09-23',
  to_date: '2026-09-30',
  professionals: [
    { staff_id: 'p2', staff_name: 'Julian Rios', occupancy_rate: 55, revenue: 300000 },
    { staff_id: 'p1', staff_name: 'Martina Paz', occupancy_rate: 78, revenue: 500000 }
  ]
}

const adminScenario = (): Scenario => ({
  user: { role: 'store_admin' },
  summary: { data: ADMIN_SUMMARY, isLoading: false, isError: false },
  flags: { data: { flags: { payments: true, ledger: true } }, isSuccess: true },
  reports: { data: ADMIN_REPORTS, isLoading: false },
  professionals: { data: ADMIN_PROFESSIONALS },
  trend: {
    data: {
      points: [
        {
          month: '2026-08',
          total_appointments: 20,
          completed_appointments: 18,
          cancelled_appointments: 2
        },
        {
          month: '2026-09',
          total_appointments: 44,
          completed_appointments: 30,
          cancelled_appointments: 4
        }
      ]
    },
    isLoading: false
  },
  reconciliation: {
    pending_payments: 2,
    total_pending_amount: 30000,
    total_approved_amount: 700000,
    failed_webhooks: 1
  },
  outbox: { pending_with_error: 2 },
  ledger: { total_balance: 25000, debtors_count: 2 }
})

// Sin reportes, sin finanzas y sin nada urgente: el dia "vacio".
const emptyScenario = (): Scenario => ({
  ...adminScenario(),
  user: { role: 'receptionist' },
  summary: {
    data: {
      stats: {
        ...ADMIN_STATS,
        appointments_today: 0,
        pending_confirmations: 0,
        occupancy_rate: 90
      },
      upcoming_appointments: []
    },
    isLoading: false,
    isError: false
  }
})

const LocationProbe = () => <p data-testid="location">{useLocation().pathname}</p>

// El `act` asincrono deja resolver el `lazy` de los graficos (F4-13) dentro del
// render: sin el, el chunk llega despues del test y React avisa.
const renderDashboard = async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Dashboard />
        <LocationProbe />
      </MemoryRouter>
    )
  })
}

const section = (title: string) => {
  const element = screen.getByRole('heading', { name: title }).closest('section')
  if (!element) throw new Error(`Sin seccion para ${title}`)
  return within(element)
}

const cardOf = (scope: ReturnType<typeof within>, label: string) => {
  const element = scope.getByText(label).closest('button')
  if (!element) throw new Error(`Sin tarjeta para ${label}`)
  return within(element)
}

// El estilo en linea de jsdom devuelve el color ya como rgb(). Son los tres
// acentos de `toneTokens`: #b76a00, #0f9f6e y #d13b3b, mas el neutral
// (`colors2000s.text.secondary`, #5c5c5c).
const TONE = {
  neutral: 'rgb(92, 92, 92)',
  warning: 'rgb(183, 106, 0)',
  success: 'rgb(15, 159, 110)',
  danger: 'rgb(209, 59, 59)'
}

const colorOf = (element: HTMLElement) => element.style.color

// El texto de un nodo trae espacios duros (U+00A0) en los pesos; se normaliza.
const texts = (elements: HTMLElement[]) =>
  elements.map((element) => (element.textContent ?? '').replace(/\s+/g, ' '))

const textOf = (element: HTMLElement | null | undefined) =>
  (element?.textContent ?? '').replace(/\s+/g, ' ')

const currentPath = () => screen.getByTestId('location').textContent

describe('Dashboard (red de seguridad de la extraccion F11b-09)', () => {
  beforeEach(() => {
    Object.assign(mockScenario, adminScenario())
  })

  describe('admin de tienda con reportes y finanzas', () => {
    it('muestra el hero con titulo, periodo, estado y las cuatro señales de salud', async () => {
      await renderDashboard()

      const hero = section('Hoy en Shifty')
      expect(hero.getByText('Corte operativo: hoy + últimos 7 días')).toBeInTheDocument()
      expect(hero.getByText('12 turnos, 3 pendientes, ocupación 62,5%.')).toBeInTheDocument()
      expect(hero.getByText('requiere seguimiento')).toBeInTheDocument()

      const pillOf = (label: string) => within(hero.getByText(label).parentElement as HTMLElement)
      expect(colorOf(pillOf('Agenda').getByText('3 pendientes'))).toBe(TONE.warning)
      expect(colorOf(pillOf('Cobros online').getByText('3 errores'))).toBe(TONE.danger)
      expect(colorOf(pillOf('Cuentas pendientes').getByText('2 clientes con deuda'))).toBe(
        TONE.warning
      )
      expect(pillOf('Ingresos').getByText('+8,4% de variación')).toBeInTheDocument()
    })

    it('muestra las cuatro metricas del resumen del dia con su señal y su detalle', async () => {
      await renderDashboard()

      const summary = section('Resumen del día')
      expect(
        summary.getByText(
          'Cuatro señales para entender el pulso del negocio antes de entrar al detalle.'
        )
      ).toBeInTheDocument()
      expect(summary.getByText('Lectura rápida del día')).toBeInTheDocument()

      const revenue = cardOf(summary, 'Ingreso semanal')
      expect(revenue.getByText(peso(450000))).toBeInTheDocument()
      expect(revenue.getByText('+8,4% vs semana pasada')).toBeInTheDocument()
      expect(revenue.getByText('Tendencia positiva')).toBeInTheDocument()

      const clients = cardOf(summary, 'Clientes nuevos')
      expect(clients.getByText('18')).toBeInTheDocument()
      expect(clients.getByText('22 recurrentes activos')).toBeInTheDocument()
      expect(clients.getByText('Adquisición en curso')).toBeInTheDocument()

      const occupancy = cardOf(summary, 'Ocupación')
      expect(occupancy.getByText('62,5%')).toBeInTheDocument()
      expect(occupancy.getByText('37,5% de capacidad libre')).toBeInTheDocument()
      expect(occupancy.getByText('Ritmo estable')).toBeInTheDocument()

      const cancellations = cardOf(summary, 'Cancelaciones')
      expect(cancellations.getByText('4')).toBeInTheDocument()
      expect(cancellations.getByText('2 próximos en agenda')).toBeInTheDocument()
      expect(cancellations.getByText('Revisar patron')).toBeInTheDocument()
    })

    it('lista la agenda de hoy con hora argentina, subtitulo y estado con su tono', async () => {
      await renderDashboard()

      const operation = section('Operación de hoy')
      expect(
        operation.getByText('Turnos, carga operativa y capacidad disponible en una sola vista.')
      ).toBeInTheDocument()
      expect(operation.getByText('Próximos movimientos de agenda')).toBeInTheDocument()

      // QA 2026-10-02: los estados salian crudos de la API; ahora en castellano.
      expect(colorOf(operation.getByText('Confirmado'))).toBe(TONE.success)
      const row = (name: string) => operation.getByText(name).parentElement?.parentElement
      expect(textOf(row('Lucia Gomez'))).toContain('10:30')
      expect(textOf(row('Lucia Gomez'))).toContain('Corte clasico - Martina Paz')
      expect(textOf(row('Sofia Diaz'))).toContain('12:00')
      expect(textOf(row('Sofia Diaz'))).toContain('Color - Julian Rios')
      expect(colorOf(operation.getByText('Pendiente'))).toBe(TONE.warning)
    })

    it('muestra las cuatro tarjetas de señal de la operacion', async () => {
      await renderDashboard()

      const operation = section('Operación de hoy')
      const signal = (title: string) =>
        operation.getByText(title, { selector: 'span' }).parentElement as HTMLElement

      expect(textOf(signal('Pendientes por confirmar'))).toContain('3')
      expect(textOf(signal('Pendientes por confirmar'))).toContain(
        'Hay reservas esperando decisión'
      )
      expect(textOf(signal('Capacidad disponible'))).toContain('37,5%')
      expect(textOf(signal('Capacidad disponible'))).toContain('Espacio operativo libre para hoy')
      expect(textOf(signal('Cancelaciones'))).toContain('Impacto registrado en el periodo')
      expect(textOf(signal('Profesional destacado'))).toContain('78%')
      expect(textOf(signal('Profesional destacado'))).toContain('Martina Paz')
    })

    it('arma las acciones urgentes, el dinero y el rendimiento semanal en orden', async () => {
      await renderDashboard()

      const urgent = section('Acciones urgentes')
      expect(texts(urgent.getAllByRole('button'))).toEqual([
        'Confirmar turnosReservas esperando decisión3',
        `Revisar cobros pendientes${peso(30000)}2`,
        'Revisar cobros onlineHay pagos pendientes de actualizar3',
        `Gestionar deuda${peso(25000)}2`
      ])

      const money = section('Dinero')
      expect(cardOf(money, 'Cobrado').getByText(peso(700000))).toBeInTheDocument()
      expect(cardOf(money, 'Cobrado').getByText('Pagos aprobados y manuales')).toBeInTheDocument()
      expect(cardOf(money, 'Ticket promedio').getByText(peso(15000))).toBeInTheDocument()
      expect(
        cardOf(money, 'Ticket promedio').getByText('Promedio móvil de 7 días')
      ).toBeInTheDocument()
      expect(cardOf(money, 'Saldo pendiente').getByText(peso(25000))).toBeInTheDocument()
      expect(cardOf(money, 'Saldo pendiente').getByText('2 clientes con deuda')).toBeInTheDocument()

      const ranking = section('Rendimiento semanal')
      expect(texts(ranking.getAllByRole('listitem'))).toEqual([
        `1Martina Paz${peso(500000)} por profesional78%`,
        `2Corte clasico30 reservas${peso(600000)}`,
        `3Color10 reservas${peso(380000)}`,
        '4Clientes recurrentes9 nuevos en el periodo22'
      ])
    })

    it('muestra las alertas y las oportunidades con sus acciones', async () => {
      await renderDashboard()

      const alerts = section('Alertas del sistema')
      expect(texts(alerts.getAllByRole('button'))).toEqual([
        'Cancelaciones en el periodoRevisar patron por servicio o profesional4'
      ])

      const opportunities = section('Oportunidades')
      expect(opportunities.getByText('Día con capacidad libre')).toBeInTheDocument()
      expect(
        opportunities.getByText(
          'Queda 37,5% sin ocupar. Conviene reforzar agenda o activar promociones.'
        )
      ).toBeInTheDocument()
      expect(opportunities.getByText('Hay una referencia clara para replicar')).toBeInTheDocument()
      expect(
        opportunities.getByText('Martina Paz lidera con 78%. Sirve como benchmark interno.')
      ).toBeInTheDocument()
      expect(opportunities.getByText('Base de clientes en movimiento')).toBeInTheDocument()
      expect(
        opportunities.getByText(
          '9 clientes nuevos ingresaron al periodo. Conviene trabajar recurrencia y rebook.'
        )
      ).toBeInTheDocument()
      expect(texts(opportunities.getAllByRole('button'))).toEqual([
        'Ver agenda',
        'Ver rendimiento',
        'Abrir usuarios'
      ])
    })

    it('ordena las transacciones por fecha descendente con monto y estado con su tono', async () => {
      await renderDashboard()

      const transactions = section('Transacciones')
      expect(
        transactions.getByText('Últimos turnos del periodo con su estado y monto.')
      ).toBeInTheDocument()

      expect(
        transactions
          .getAllByText(/^(Bruno Saenz|Ana Lopez|Carla Vega)$/)
          .map((name) => name.textContent)
      ).toEqual(['Bruno Saenz', 'Ana Lopez', 'Carla Vega'])

      const row = (name: string) => transactions.getByText(name).parentElement?.parentElement
      expect(textOf(row('Bruno Saenz'))).toContain('Color - 29/09 13:30')
      expect(textOf(row('Bruno Saenz'))).toContain(peso(40000))
      expect(textOf(row('Ana Lopez'))).toContain('Corte clasico - 28/09 11:00')
      expect(textOf(row('Ana Lopez'))).toContain(peso(15000))
      expect(textOf(row('Carla Vega'))).toContain('Barba - 27/09 09:00')
      expect(textOf(row('Carla Vega'))).toContain(peso(8000))

      expect(colorOf(transactions.getByText('Cancelado'))).toBe(TONE.danger)
      expect(colorOf(transactions.getByText('Completado'))).toBe(TONE.success)
      expect(colorOf(transactions.getByText('Confirmado'))).toBe(TONE.success)
      expect(transactions.getByRole('button', { name: 'Ver todas' })).toBeInTheDocument()
    })

    it('pinta pendiente y pago pendiente en warning y un estado desconocido en neutral', async () => {
      Object.assign(mockScenario, {
        reports: {
          data: {
            ...ADMIN_REPORTS,
            appointments: [
              { ...ADMIN_REPORTS.appointments[0], public_id: 'rep-4', status: 'pending' },
              { ...ADMIN_REPORTS.appointments[1], public_id: 'rep-5', status: 'pending_payment' },
              { ...ADMIN_REPORTS.appointments[2], public_id: 'rep-6', status: 'desconocido' }
            ]
          },
          isLoading: false
        }
      })
      await renderDashboard()

      const transactions = section('Transacciones')
      expect(colorOf(transactions.getByText('Pendiente'))).toBe(TONE.warning)
      expect(colorOf(transactions.getByText('Pendiente de pago'))).toBe(TONE.warning)
      expect(colorOf(transactions.getByText('desconocido'))).toBe(TONE.neutral)
    })

    it('el modo compacto es solo de las alertas: 64 contra los 72 de las acciones urgentes', async () => {
      await renderDashboard()

      const minHeightOf = (title: string) =>
        (screen.getByText(title).closest('button') as HTMLButtonElement).style.minHeight

      expect(minHeightOf('Confirmar turnos')).toBe('72px')
      expect(minHeightOf('Cancelaciones en el periodo')).toBe('64px')
    })

    it('entrega a los graficos los puntos de tendencia y los servicios con su carga', async () => {
      await renderDashboard()

      expect(
        await screen.findByText('Grafico de tendencia: 2 puntos, cargando false')
      ).toBeInTheDocument()
      expect(
        await screen.findByText('Grafico de ventas: 2 servicios, cargando false')
      ).toBeInTheDocument()
    })

    it.each([
      ['Ver agenda', 'hero', '/dashboard/calendar'],
      ['Registrar cobro', 'hero', '/dashboard/collections'],
      ['Abrir reportes', 'hero', '/dashboard/reports'],
      ['Gestionar deuda', 'Acciones urgentes', '/dashboard/ledger'],
      ['Revisar cobros online', 'Acciones urgentes', '/dashboard/payments'],
      ['Ocupación', 'Resumen del día', '/dashboard/reports'],
      ['Clientes nuevos', 'Resumen del día', '/dashboard/users'],
      ['Saldo pendiente', 'Dinero', '/dashboard/ledger'],
      ['Cobrado', 'Dinero', '/dashboard/collections'],
      ['Ver rendimiento', 'Oportunidades', '/dashboard/reports'],
      ['Ver todas', 'Transacciones', '/dashboard/reports']
    ])('al tocar "%s" (%s) navega a %s', async (label, where, path) => {
      await renderDashboard()

      const scope = section(where === 'hero' ? 'Hoy en Shifty' : where)
      fireEvent.click(scope.getByText(label))

      expect(currentPath()).toBe(path)
    })
  })

  describe('profesional sin finanzas', () => {
    beforeEach(() => {
      Object.assign(mockScenario, { user: { role: 'professional' } })
    })

    it('no consulta cobros ni outbox: sin esas acciones y con el cobrado de los reportes', async () => {
      await renderDashboard()

      const urgent = section('Acciones urgentes')
      expect(texts(urgent.getAllByRole('button'))).toEqual([
        'Confirmar turnosReservas esperando decisión3',
        `Gestionar deuda${peso(25000)}2`
      ])
      expect(screen.queryByText('Revisar cobros pendientes')).not.toBeInTheDocument()
      expect(screen.queryByText('Revisar cobros online')).not.toBeInTheDocument()

      const hero = section('Hoy en Shifty')
      expect(
        within(hero.getByText('Cobros online').parentElement as HTMLElement).getByText('sin fallas')
      ).toBeInTheDocument()

      const money = section('Dinero')
      expect(cardOf(money, 'Cobrado').getByText(peso(980000))).toBeInTheDocument()
    })
  })

  describe('modulos desactivados', () => {
    it('avisa en el hero y en las alertas cuando cobros y cuentas estan apagados', async () => {
      Object.assign(mockScenario, {
        flags: { data: { flags: { payments: false, ledger: false } }, isSuccess: true }
      })
      await renderDashboard()

      const hero = section('Hoy en Shifty')
      const pillOf = (label: string) => within(hero.getByText(label).parentElement as HTMLElement)
      expect(pillOf('Cobros online').getByText('deshabilitados')).toBeInTheDocument()
      expect(pillOf('Cuentas pendientes').getByText('desactivadas')).toBeInTheDocument()

      const alerts = section('Alertas del sistema')
      expect(texts(alerts.getAllByRole('button'))).toEqual([
        'Cobros online desactivadosNo hay cobro automático activo',
        'Cuentas pendientes desactivadasNo se lleva la deuda de cada cliente',
        'Cancelaciones en el periodoRevisar patron por servicio o profesional4'
      ])

      fireEvent.click(screen.getByRole('button', { name: /Cobros online desactivados/ }))
      expect(currentPath()).toBe('/dashboard/settings')
    })
  })

  describe('estados de carga y error', () => {
    it('muestra solo "Cargando panel..." mientras carga el resumen', async () => {
      Object.assign(mockScenario, {
        summary: { data: undefined, isLoading: true, isError: false }
      })
      await renderDashboard()

      expect(screen.getByText('Cargando panel...')).toBeInTheDocument()
      expect(screen.queryByText('Resumen del día')).not.toBeInTheDocument()
      expect(screen.queryByText('Hoy en Shifty')).not.toBeInTheDocument()
    })

    it('muestra el ErrorPanel arriba de todo y el resto de la pagina igual', async () => {
      Object.assign(mockScenario, {
        summary: { data: undefined, isLoading: false, isError: true }
      })
      await renderDashboard()

      const message = screen.getByText('No se pudo cargar el resumen operativo.')
      expect(colorOf(message)).toBe(TONE.danger)
      expect(message.closest('main')?.firstElementChild).toBe(message)
      expect(screen.getByText('Resumen del día')).toBeInTheDocument()
      expect(screen.getByText('Hoy en Shifty')).toBeInTheDocument()
    })

    it('entrega la carga de tendencia y de ventas a cada grafico', async () => {
      Object.assign(mockScenario, {
        trend: { data: undefined, isLoading: true },
        reports: { data: undefined, isLoading: true }
      })
      await renderDashboard()

      expect(
        await screen.findByText('Grafico de tendencia: 0 puntos, cargando true')
      ).toBeInTheDocument()
      expect(
        await screen.findByText('Grafico de ventas: 0 servicios, cargando true')
      ).toBeInTheDocument()
    })
  })

  describe('listas vacias', () => {
    beforeEach(() => {
      Object.assign(mockScenario, emptyScenario())
    })

    it('muestra el texto de EmptyState de cada panel', async () => {
      await renderDashboard()

      expect(
        section('Operación de hoy').getByText('No hay próximos turnos para mostrar.')
      ).toBeInTheDocument()
      expect(
        section('Acciones urgentes').getByText('No hay tareas criticas por resolver.')
      ).toBeInTheDocument()
      expect(
        section('Rendimiento semanal').getByText('Sin datos para este periodo.')
      ).toBeInTheDocument()
      expect(section('Alertas del sistema').getByText('Sin alertas activas.')).toBeInTheDocument()
      expect(
        section('Oportunidades').getByText('Sin oportunidades destacadas por ahora.')
      ).toBeInTheDocument()
      expect(
        section('Transacciones').getByText('No hay turnos registrados en el periodo.')
      ).toBeInTheDocument()
    })

    it('marca el estado estable y las señales neutras sin pendientes ni deuda', async () => {
      await renderDashboard()

      const hero = section('Hoy en Shifty')
      expect(hero.getByText('estable')).toBeInTheDocument()
      const pillOf = (label: string) => within(hero.getByText(label).parentElement as HTMLElement)
      expect(colorOf(pillOf('Agenda').getByText('al día'))).toBe(TONE.success)
      expect(pillOf('Cobros online').getByText('sin fallas')).toBeInTheDocument()
      expect(pillOf('Cuentas pendientes').getByText('sin deuda')).toBeInTheDocument()

      const operation = section('Operación de hoy')
      expect(operation.getByText('Sin lider claro')).toBeInTheDocument()
      expect(operation.getByText('--')).toBeInTheDocument()
      expect(operation.getByText('No hay confirmaciones pendientes')).toBeInTheDocument()
    })
  })
})
