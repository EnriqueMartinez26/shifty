import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import Dashboard from './Dashboard'

// 2026-09-30: recharts (~426 KB) cargaba en la primera pantalla del dueno
// porque Dashboard importaba los graficos en forma estatica (F4-13). Ahora
// llegan con lazy: mientras baja su chunk se ve un lugar reservado del alto
// del grafico y despues el grafico. Los modulos de graficos se reemplazan por
// dobles para no depender de recharts en jsdom.
jest.mock('../components/organisms/dashboard/TrendChart', () => ({
  __esModule: true,
  default: () => <p>Grafico de tendencia</p>
}))

jest.mock('../components/organisms/dashboard/SalesDonut', () => ({
  __esModule: true,
  default: () => <p>Grafico de ventas</p>
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ token: 'token', user: { role: 'store_admin' } })
}))

jest.mock('../hooks/useDashboard', () => ({
  useDashboardSummary: () => ({ data: undefined, isLoading: false, isError: false })
}))

jest.mock('../hooks/useStores', () => ({
  useStoreFeatureFlags: () => ({ data: undefined, isSuccess: false })
}))

jest.mock('../hooks/useReports', () => ({
  useReportSummary: () => ({ data: undefined, isLoading: false }),
  useProfessionalReports: () => ({ data: undefined, isLoading: false }),
  useReportTrend: () => ({ data: { points: [] }, isLoading: false })
}))

jest.mock('../hooks/usePayments', () => ({
  useReconciliationSummary: () => ({ data: undefined }),
  useOutboxStats: () => ({ data: undefined })
}))

jest.mock('../hooks/useLedger', () => ({
  useLedgerSummary: () => ({ data: undefined })
}))

const renderDashboard = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Dashboard />
    </MemoryRouter>
  )

describe('Dashboard', () => {
  it('reserva el alto de cada grafico mientras carga su chunk y despues los muestra', async () => {
    renderDashboard()

    // Antes de que resuelva el import dinamico: lugar reservado con el alto
    // del area del grafico (280 la tendencia, 200 la dona) para que la grilla
    // no salte.
    expect(screen.getByText('Cargando tendencia...').style.height).toBe('280px')
    expect(screen.getByText('Cargando ventas...').style.height).toBe('200px')

    expect(await screen.findByText('Grafico de tendencia')).toBeInTheDocument()
    expect(await screen.findByText('Grafico de ventas')).toBeInTheDocument()
    expect(screen.queryByText('Cargando tendencia...')).not.toBeInTheDocument()
    expect(screen.queryByText('Cargando ventas...')).not.toBeInTheDocument()
  })
})
