import { render, screen } from '@testing-library/react'

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
  trendPoints: [],
  trendLoading: false,
  topServices: [],
  salesLoading: false,
  transactions: [],
  onViewTransactions: jest.fn(),
  todayMetrics: [],
  urgentActions: [],
  agenda: [],
  operationCards: [],
  moneyMetrics: [],
  performanceItems: [],
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
