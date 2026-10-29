import { fireEvent, render, screen } from '@testing-library/react'

import EnterpriseDashboard from './EnterpriseDashboard'
import type { EnterpriseDashboardProps } from './types'

jest.mock('./TrendChart', () => ({
  __esModule: true,
  default: () => <p>Grafico de tendencia</p>
}))

jest.mock('./SalesDonut', () => ({
  __esModule: true,
  default: () => <p>Grafico de ventas</p>
}))

const dashboardProps: EnterpriseDashboardProps = {
  reportsAllowed: true,
  copy: {
    metricsTitle: 'Pulso del negocio',
    transactionsTitle: 'Últimos movimientos',
    transactionsDescription: 'Actividad reciente',
    viewTransactionsLabel: 'Ver reportes',
    operationsTitle: 'Operación de hoy',
    operationsDescription: 'Agenda',
    actionsTitle: 'Acciones',
    moneyTitle: 'Dinero',
    performanceTitle: 'Rendimiento',
    alertsTitle: 'Alertas',
    opportunitiesTitle: 'Oportunidades',
    emptyActions: 'Sin acciones pendientes',
    emptyAgenda: 'Agenda vacía',
    emptyAlerts: 'Sin alertas',
    emptyOpportunities: 'Sin oportunidades',
    emptyTransactions: 'Sin movimientos'
  },
  hero: {
    title: 'Hoy en Shifty',
    description: 'Resumen operativo',
    periodLabel: 'Hoy',
    statusLabel: 'estable',
    health: [],
    quickActions: []
  },
  queryIssues: [],
  trendPoints: [],
  trendLoading: false,
  trendUnavailable: false,
  topServices: [],
  salesLoading: false,
  salesUnavailable: false,
  transactions: [],
  transactionsUnavailable: false,
  onViewTransactions: jest.fn(),
  todayMetrics: [],
  urgentActions: [],
  agenda: [],
  operationCards: [],
  moneyMetrics: [],
  performanceItems: [],
  performanceUnavailable: false,
  alerts: [],
  opportunities: [],
  isLoading: false
}

describe('EnterpriseDashboard responsive layout', () => {
  it('prevents intrinsic overflow and gives tablet transactions a full row before stacking on mobile', async () => {
    render(<EnterpriseDashboard {...dashboardProps} />)
    const main = screen.getByRole('main')
    const styles =
      Array.from(main.children).find((child) => child.tagName === 'STYLE')?.textContent ?? ''

    expect(await screen.findByText('Grafico de tendencia')).toBeInTheDocument()
    expect(await screen.findByText('Grafico de ventas')).toBeInTheDocument()
    expect(main.style.width).toBe('100%')
    expect(main.style.minWidth).toBe('0')
    expect(styles).toContain('min-width: 0')
    expect(styles).toContain('@media (max-width: 1100px)')
    expect(styles).toMatch(/grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
    expect(styles).toMatch(/\.dashboard-insights-grid > :last-child[\s\S]*?grid-column:\s*1 \/ -1/)
    expect(styles).toContain('@media (max-width: 720px)')
    expect(styles).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/)
    expect(styles).toMatch(/\.dashboard-insights-grid > :last-child[\s\S]*?grid-column:\s*auto/)
  })
})

describe('EnterpriseDashboard report availability', () => {
  it('shows neutral access states instead of retry prompts when reports are forbidden', () => {
    render(
      <EnterpriseDashboard
        {...dashboardProps}
        reportsAllowed={false}
        trendUnavailable
        salesUnavailable
        transactionsUnavailable
        performanceUnavailable
      />
    )

    expect(screen.getAllByText('Sin acceso a reportes')).toHaveLength(4)
    expect(screen.queryByText(/Reintentá desde el aviso/)).not.toBeInTheDocument()
    expect(screen.queryByText('Sin movimientos')).not.toBeInTheDocument()
  })

  it('keeps retry prompts when an authorized report query has a visible error notice', () => {
    const onRetry = jest.fn()

    render(
      <EnterpriseDashboard
        {...dashboardProps}
        reportsAllowed
        queryIssues={[
          {
            id: 'reports',
            title: 'Reportes del período',
            message: 'No se pudieron cargar los reportes.',
            retrying: false,
            onRetry
          },
          {
            id: 'professionals',
            title: 'Rendimiento profesional',
            message: 'No se pudo cargar el rendimiento.',
            retrying: false,
            onRetry
          },
          {
            id: 'trend',
            title: 'Tendencia',
            message: 'No se pudo cargar la tendencia.',
            retrying: false,
            onRetry
          }
        ]}
        trendUnavailable
        salesUnavailable
        transactionsUnavailable
        performanceUnavailable
      />
    )

    expect(
      screen.getByText('Tendencia no disponible. Reintentá desde el aviso del panel.')
    ).toBeInTheDocument()
    expect(
      screen.getByText('Ventas no disponibles. Reintentá desde el aviso del panel.')
    ).toBeInTheDocument()
    expect(
      screen.getByText('Transacciones no disponibles. Reintentá desde el aviso del panel.')
    ).toBeInTheDocument()
    expect(
      screen.getByText('Rendimiento no disponible. Reintentá desde el aviso del panel.')
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar reportes del período' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('does not suggest retrying when report data is unavailable without an error notice', () => {
    render(
      <EnterpriseDashboard
        {...dashboardProps}
        reportsAllowed
        queryIssues={[]}
        trendUnavailable
        salesUnavailable
        transactionsUnavailable
        performanceUnavailable
      />
    )

    expect(screen.getByText('Tendencia no disponible.')).toBeInTheDocument()
    expect(screen.getByText('Ventas no disponibles.')).toBeInTheDocument()
    expect(screen.getByText('Transacciones no disponibles.')).toBeInTheDocument()
    expect(screen.getByText('Rendimiento no disponible.')).toBeInTheDocument()
    expect(screen.queryByText(/Reintentá desde el aviso/)).not.toBeInTheDocument()
  })
})
