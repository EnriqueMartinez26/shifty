import { fireEvent, render, screen } from '@testing-library/react'

import type { ReportSummary } from '@application/services/ReportsService'

import ReportsPage from './Reports'

const mockSummary: ReportSummary = {
  from_date: '2026-09-01',
  to_date: '2026-09-08',
  stats: {
    total_appointments: 2,
    completed_appointments: 0,
    cancelled_appointments: 0,
    pending_appointments: 1,
    confirmed_appointments: 0,
    total_revenue: 0,
    average_ticket: 0
  },
  client_stats: { total_clients: 1, new_clients: 1, returning_clients: 0, inactive_clients: 0 },
  top_services: [],
  top_clients: [],
  debt_summary: { outstanding_balance: 0, debtors_count: 0, average_debt: 0, top_debtors: [] },
  appointments: [
    {
      public_id: 'apt-1',
      starts_at: '2026-09-02T13:00:00Z',
      ends_at: '2026-09-02T13:30:00Z',
      status: 'pending_payment',
      service_name: 'Corte',
      staff_name: 'Lucia',
      client_name: 'Ana Gomez',
      service_price: 1000
    },
    {
      public_id: 'apt-2',
      starts_at: '2026-09-03T13:00:00Z',
      ends_at: '2026-09-03T13:30:00Z',
      status: 'on_hold',
      service_name: 'Color',
      staff_name: 'Lucia',
      client_name: 'Beto Gomez',
      service_price: 2000
    }
  ],
  has_more: false
}

let mockSummaryData: ReportSummary = mockSummary
let mockFailLaterPages = false
let mockPendingLaterPages = false
// Rango (fecha "desde") cuyo resumen responde con error, p. ej. el 400 de mas
// de 370 dias.
let mockFailingFrom: string | null = null
const mockUseReportSummary = jest.fn((...args: unknown[]) => {
  const later = (args[3] as { offset: number }).offset > 0
  const failed = (mockFailLaterPages && later) || args[0] === mockFailingFrom
  return {
    data: failed ? undefined : mockSummaryData,
    isLoading: false,
    isError: failed,
    isPlaceholderData: mockPendingLaterPages && later,
    refetch: mockRefetch
  }
})
const mockRefetch = jest.fn()
let mockAuthUser: { role: string; is_global_admin?: boolean } = { role: 'store_admin' }

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockAuthUser })
}))

jest.mock('../hooks/useReports', () => ({
  useReportSummary: (...args: unknown[]) => mockUseReportSummary(...args),
  useProfessionalReports: () => ({
    data: { professionals: [] },
    isLoading: false,
    error: null
  }),
  useExportReport: () => ({ mutateAsync: jest.fn(), isPending: false })
}))

const lastOffset = () => {
  const page = mockUseReportSummary.mock.calls.at(-1)?.[3] as { offset: number }
  return page.offset
}

describe('ReportsPage', () => {
  beforeEach(() => {
    mockSummaryData = mockSummary
    mockFailLaterPages = false
    mockPendingLaterPages = false
    mockFailingFrom = null
    mockAuthUser = { role: 'store_admin' }
    mockUseReportSummary.mockClear()
  })

  it('muestra el estado del turno en castellano y deja crudo el que no conoce', () => {
    render(<ReportsPage />)

    expect(screen.getByText('Pendiente de pago')).toBeInTheDocument()
    expect(screen.queryByText('pending_payment')).not.toBeInTheDocument()
    expect(screen.getByText('on_hold')).toBeInTheDocument()
  })

  // Un <button> sin type es submit: movido dentro de un <form> lo envia.
  it('los botones de exportar declaran type="button" (F11b-26)', () => {
    const { container } = render(<ReportsPage />)

    expect(container.querySelectorAll('button:not([type])')).toHaveLength(0)
  })

  it('el profesional no ve los botones de exportar (FF-18)', () => {
    mockAuthUser = { role: 'professional' }
    render(<ReportsPage />)

    expect(screen.queryByText(/Exportar/)).not.toBeInTheDocument()
  })

  it('pagina el detalle: Siguiente solo con has_more y la fecha vuelve a la primera (FF-30)', () => {
    const { rerender } = render(<ReportsPage />)
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled()
    expect(lastOffset()).toBe(0)

    mockSummaryData = { ...mockSummary, has_more: true }
    rerender(<ReportsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }))
    expect(lastOffset()).toBe(100)

    const desde = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(desde, { target: { value: '2026-08-01' } })
    expect(lastOffset()).toBe(0)
  })

  it('si falla una pagina posterior queda la pantalla y el error va junto a la paginacion', () => {
    mockSummaryData = { ...mockSummary, has_more: true }
    mockFailLaterPages = true
    render(<ReportsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }))

    expect(screen.getByText('Total turnos')).toBeInTheDocument()
    expect(screen.getByText(/No se pudo cargar esta página del detalle/)).toBeInTheDocument()
    // Filas y rotulo de la misma pagina (la ultima buena), no "101–102".
    expect(screen.getByText(/^1–2 de 2/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(mockRefetch).toHaveBeenCalled()
    expect(screen.queryByText(/No se pudo cargar el reporte/)).not.toBeInTheDocument()
  })

  it('si falla un rango nuevo, las fechas siguen a mano para corregirlo (FF-19)', () => {
    // 2026-09-28: la pantalla de error reemplazaba la pagina entera y escondia
    // los selectores; con un rango invalido no habia forma de salir.
    mockFailingFrom = '2025-01-01'
    render(<ReportsPage />)

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2025-01-01' } })

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar el reporte')
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-09-01' } })
    expect(mockUseReportSummary.mock.calls.at(-1)?.[0]).toBe('2026-09-01')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('Total turnos')).toBeInTheDocument()
  })

  it('mientras llega la pagina 2, rotulo y filas son de la pagina que se ve', () => {
    mockSummaryData = { ...mockSummary, has_more: true }
    mockPendingLaterPages = true
    render(<ReportsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }))

    expect(screen.getByText(/^1–2 de 2 · Actualizando/)).toBeInTheDocument()
  })
})
