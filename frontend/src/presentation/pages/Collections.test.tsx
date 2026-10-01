import { render, screen } from '@testing-library/react'

import CollectionsPage from './Collections'

// FF-21: la conciliacion es solo de admins; al profesional el backend le
// responde 403, asi que la pantalla no la pide ni muestra sus indicadores.
const mockUseReconciliationSummary = jest.fn((enabled?: boolean) => ({
  data: enabled ? { pending_payments: 4, total_pending_amount: '1500' } : undefined,
  error: null
}))
let mockAuthUser: { role: string; is_global_admin: boolean }

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockAuthUser })
}))

jest.mock('../hooks/usePayments', () => ({
  usePaymentsAppointments: () => ({ data: [], isLoading: false, error: null }),
  useReconciliationSummary: (enabled?: boolean) => mockUseReconciliationSummary(enabled),
  useCreatePaymentPreference: () => ({ mutateAsync: jest.fn(), data: undefined }),
  useManualConfirmPayment: () => ({ mutateAsync: jest.fn() })
}))

const valorDe = (label: string) => screen.getByText(label).nextElementSibling?.textContent

describe('CollectionsPage', () => {
  beforeEach(() => {
    mockUseReconciliationSummary.mockClear()
  })

  it('al profesional no le pide la conciliacion ni le muestra pagos pendientes', () => {
    mockAuthUser = { role: 'professional', is_global_admin: false }
    render(<CollectionsPage />)

    expect(mockUseReconciliationSummary).toHaveBeenCalledWith(false)
    expect(mockUseReconciliationSummary).not.toHaveBeenCalledWith(true)
    expect(valorDe('Turnos listados')).toBe('0')
    expect(screen.queryByText('Pagos pendientes')).not.toBeInTheDocument()
    expect(screen.queryByText('Monto pendiente')).not.toBeInTheDocument()
    // Crear el link y confirmar el pago manual siguen disponibles en la pantalla.
    expect(screen.getByRole('heading', { name: 'Turnos listos para cobrar' })).toBeInTheDocument()
  })

  it.each([
    ['store_admin', false],
    ['professional', true]
  ])(
    'con el rol %s (llave global: %s) pide la conciliacion y muestra las tres tarjetas',
    (role, isGlobalAdmin) => {
      mockAuthUser = { role, is_global_admin: isGlobalAdmin }
      render(<CollectionsPage />)

      expect(mockUseReconciliationSummary).toHaveBeenCalledWith(true)
      expect(valorDe('Turnos listados')).toBe('0')
      expect(valorDe('Pagos pendientes')).toBe('4')
      expect(screen.getByText('Monto pendiente')).toBeInTheDocument()
    }
  )
})
