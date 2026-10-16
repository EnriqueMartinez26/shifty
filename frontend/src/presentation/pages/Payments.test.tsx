import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

    fireEvent.change(screen.getByRole('textbox', { name: 'ID del cobro' }), {
      target: { value: 'pay-1' }
    })
    fireEvent.click(screen.getByRole('radio', { name: /Total:/i }))
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))
    fireEvent.click(screen.getByRole('checkbox', { name: /ya hice esta devolución/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Confirmar registro de devolución/i }))
    })

    expect(screen.getByText(/resto de/)).toHaveTextContent('2.240')
    expect(screen.getByText(/resto de/)).toHaveTextContent(/revertilo/)
  })
})

// 2026-10-16: Number('3.200') daba 3.2 y Number('3.200,50') daba NaN;
// el ultimo podia serializarse como null y convertirse en devolucion total.
describe('PaymentsPage: seguridad de devoluciones', () => {
  const renderPage = () =>
    render(
      <MemoryRouter>
        <PaymentsPage />
      </MemoryRouter>
    )

  const identifyPayment = () => {
    fireEvent.change(screen.getByRole('textbox', { name: 'ID del cobro' }), {
      target: { value: ' pay-1 ' }
    })
  }

  const reviewAndConfirm = async () => {
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))
    fireEvent.click(screen.getByRole('checkbox', { name: /ya hice esta devolución/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Confirmar registro de devolución/i }))
    })
  }

  beforeEach(() => {
    mockSummary = undefined
    mockRefund.mockReset()
    mockRefund.mockResolvedValue({ public_id: 'pay-1', live_remainder_amount: null })
  })

  it.each([
    ['3.200', 3200, /3\.200,00/],
    ['3.200,50', 3200.5, /3\.200,50/]
  ])(
    'interpreta %s como importe parcial exacto antes de registrar',
    async (input, amount, review) => {
      renderPage()
      identifyPayment()
      fireEvent.click(screen.getByRole('radio', { name: /Parcial:/i }))
      fireEvent.change(screen.getByRole('textbox', { name: /Importe devuelto en pesos/i }), {
        target: { value: input }
      })
      fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))

      expect(screen.getByText(review)).toBeInTheDocument()
      expect(mockRefund).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: /Confirmar registro/i })).toBeDisabled()
      fireEvent.click(screen.getByRole('checkbox', { name: /ya hice esta devolución/i }))
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /Confirmar registro/i }))
      })

      expect(mockRefund).toHaveBeenCalledWith({
        paymentId: 'pay-1',
        amount,
        reason: undefined,
        manual: true
      })
    }
  )

  it.each(['3.2', '3,200', ''])('rechaza el importe parcial ambiguo o vacío %j', (input) => {
    renderPage()
    identifyPayment()
    fireEvent.click(screen.getByRole('radio', { name: /Parcial:/i }))
    if (input) {
      fireEvent.change(screen.getByRole('textbox', { name: /Importe devuelto en pesos/i }), {
        target: { value: input }
      })
    }
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirmar registro/i })).not.toBeInTheDocument()
    expect(mockRefund).not.toHaveBeenCalled()
  })

  it('no permite registrar con un ID de cobro vacío', () => {
    renderPage()
    fireEvent.click(screen.getByRole('radio', { name: /Total:/i }))
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))

    expect(screen.getByRole('alert')).toHaveTextContent('Ingresá el ID del cobro')
    expect(mockRefund).not.toHaveBeenCalled()
  })

  it('exige escoger Total expresamente y no envía null para el importe', async () => {
    renderPage()
    identifyPayment()
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Elegí si la devolución fue total o parcial'
    )
    expect(mockRefund).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('radio', { name: /Total:/i }))
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))
    expect(screen.getByText(/total del cobro, según el importe registrado/i)).toBeInTheDocument()
    await reviewAndConfirm()
    expect(mockRefund).toHaveBeenCalledWith({
      paymentId: 'pay-1',
      amount: undefined,
      reason: undefined,
      manual: true
    })
  })

  it('invalida la revisión si cambia el cobro y bloquea envíos duplicados', async () => {
    let finishRefund: (value: { public_id: string; live_remainder_amount: null }) => void = () =>
      undefined
    mockRefund.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishRefund = resolve
        })
    )
    renderPage()
    identifyPayment()
    fireEvent.click(screen.getByRole('radio', { name: /Total:/i }))
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))
    fireEvent.change(screen.getByRole('textbox', { name: 'ID del cobro' }), {
      target: { value: 'pay-2' }
    })
    expect(screen.queryByRole('button', { name: /Confirmar registro/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Revisar devolución/i }))
    fireEvent.click(screen.getByRole('checkbox', { name: /ya hice esta devolución/i }))
    fireEvent.click(screen.getByRole('button', { name: /Confirmar registro/i }))
    expect(screen.getByRole('button', { name: /Registrando devolución/i })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /Registrando devolución/i }))
    expect(mockRefund).toHaveBeenCalledTimes(1)
    expect(mockRefund).toHaveBeenCalledWith(expect.objectContaining({ paymentId: 'pay-2' }))

    await act(async () => finishRefund({ public_id: 'pay-2', live_remainder_amount: null }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Confirmar registro/i })).not.toBeInTheDocument()
    )
  })

  it('muestra un rechazo sin convertirlo en devolución total y permite corregir', async () => {
    mockRefund.mockRejectedValueOnce(new Error('El cobro no admite esa devolución'))
    renderPage()
    identifyPayment()
    fireEvent.click(screen.getByRole('radio', { name: /Parcial:/i }))
    fireEvent.change(screen.getByRole('textbox', { name: /Importe devuelto en pesos/i }), {
      target: { value: '3.200,50' }
    })
    await reviewAndConfirm()

    expect(screen.getByText('No se pudo registrar la devolución')).toBeInTheDocument()
    expect(mockRefund).toHaveBeenCalledTimes(1)
    expect(mockRefund.mock.calls[0]?.[0]).toEqual(expect.objectContaining({ amount: 3200.5 }))
    fireEvent.change(screen.getByRole('textbox', { name: /Importe devuelto en pesos/i }), {
      target: { value: '3.000' }
    })
    expect(screen.queryByRole('button', { name: /Confirmar registro/i })).not.toBeInTheDocument()
  })
})
