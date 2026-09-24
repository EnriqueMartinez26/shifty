import { render, screen } from '@testing-library/react'

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
  ]
}

jest.mock('../hooks/useReports', () => ({
  useReportSummary: () => ({ data: mockSummary, isLoading: false, error: null }),
  useProfessionalReports: () => ({
    data: { professionals: [] },
    isLoading: false,
    error: null
  }),
  useExportReport: () => ({ mutateAsync: jest.fn(), isPending: false })
}))

describe('ReportsPage', () => {
  it('muestra el estado del turno en castellano y deja crudo el que no conoce', () => {
    render(<ReportsPage />)

    expect(screen.getByText('Pendiente de pago')).toBeInTheDocument()
    expect(screen.queryByText('pending_payment')).not.toBeInTheDocument()
    expect(screen.getByText('on_hold')).toBeInTheDocument()
  })
})
