import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

import PaymentsPage from './Payments'

jest.mock('../hooks/usePayments', () => ({
  useGatewayConfig: () => ({ data: { configured: false }, isLoading: false }),
  useReconciliationSummary: () => ({ data: undefined, isLoading: false }),
  useOutboxStats: () => ({ data: undefined }),
  useProcessOutbox: () => ({ mutateAsync: jest.fn() }),
  useRefundPayment: () => ({ mutateAsync: jest.fn() })
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
