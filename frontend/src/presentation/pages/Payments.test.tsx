import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

import PaymentsPage from './Payments'

let mockSummary: Record<string, unknown> | undefined
const mockRefund = jest.fn()

jest.mock('../hooks/usePayments', () => ({
  useGatewayConfig: () => ({ data: { configured: false }, isLoading: false }),
  useReconciliationSummary: () => ({ data: mockSummary, isLoading: false }),
  useOutboxStats: () => ({ data: undefined }),
  useProcessOutbox: () => ({ mutateAsync: jest.fn() }),
  useRefundPayment: () => ({ mutateAsync: mockRefund })
}))

const SettingsProbe = () => {
  const location = useLocation()
  return <p>{`settings${location.search}`}</p>
}

describe('PaymentsPage', () => {
  it('abre Configuracion dentro de la SPA, sin recargar la pagina (F11b-20)', () => {
    // Con window.location.assign la recarga completa perdia el token en
    // memoria; aca el router tiene que llegar solo a la pestaña de pagos.
    render(
      <MemoryRouter initialEntries={['/dashboard/payments']}>
        <Routes>
          <Route path="/dashboard/payments" element={<PaymentsPage />} />
          <Route path="/dashboard/settings" element={<SettingsProbe />} />
        </Routes>
      </MemoryRouter>
    )

    fireEvent.click(screen.getByRole('button', { name: 'Abrir configuración de Mercado Pago' }))

    expect(screen.getByText('settings?tab=payments')).toBeInTheDocument()
  })
})

// Revision de la PR #137 (D-20261008-01, W1 y S2).
describe('PaymentsPage: el resto del turno', () => {
  const renderPage = () =>
    render(
      <MemoryRouter>
        <PaymentsPage />
      </MemoryRouter>
    )

  beforeEach(() => {
    mockSummary = undefined
    mockRefund.mockReset()
  })

  it('el total cobrado suma los restos pagados aparte', () => {
    mockSummary = { total_approved_amount: '960.00', total_remainder_amount: '2240.00' }
    renderPage()

    expect(screen.getByText('Total cobrado').nextElementSibling).toHaveTextContent('3.200')
  })

  it('al registrar una devolucion avisa el resto vivo del turno', async () => {
    mockRefund.mockResolvedValue({
      public_id: 'pay-1',
      status: 'refunded',
      live_remainder_amount: '2240.00'
    })
    renderPage()

    fireEvent.change(screen.getByPlaceholderText(/ID del cobro/i), {
      target: { value: 'pay-1' }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Registrar devolución/i }))
    })

    expect(screen.getByText(/resto de/)).toHaveTextContent('2.240')
    expect(screen.getByText(/resto de/)).toHaveTextContent(/revertilo/)
  })
})
