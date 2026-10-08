import { fireEvent, render, screen } from '@testing-library/react'

import { ManualPaymentModal } from './ManualPaymentModal'

// 2026-10-08, QA en el celular (decision de Mateo): "Confirmar pago" registraba
// al instante, sin confirmar, sin importe y sin decir que turno era. El dialogo
// muestra el turno (cliente, servicio, fecha y hora) y pide el importe.
describe('ManualPaymentModal', () => {
  const props = {
    clientName: 'Lucia Perez',
    serviceName: 'Corte',
    startsAt: '2026-10-08T13:00:00Z',
    suggestedAmount: 3200,
    isDeposit: false,
    busy: false,
    error: null,
    onSubmit: jest.fn(),
    onClose: jest.fn()
  }

  beforeEach(() => {
    props.onSubmit.mockClear()
    props.onClose.mockClear()
  })

  const importe = () => screen.getByLabelText(/Importe/)
  const registrar = () => screen.getByRole('button', { name: /Registrar pago/ })

  it('muestra el turno y precarga el importe sugerido', () => {
    render(<ManualPaymentModal {...props} />)

    const dialogo = screen.getByRole('dialog', { name: /Confirmar pago/ })
    expect(dialogo).toHaveTextContent('Lucia Perez')
    expect(dialogo).toHaveTextContent('Corte')
    expect(dialogo).toHaveTextContent('08/10/2026')
    expect(dialogo).toHaveTextContent('10:00')
    expect((importe() as HTMLInputElement).value).toBe('3200')
  })

  it('con una sena pendiente lo dice', () => {
    render(<ManualPaymentModal {...props} suggestedAmount={960} isDeposit />)

    expect(screen.getByText(/seña pendiente/i)).toBeInTheDocument()
    expect((importe() as HTMLInputElement).value).toBe('960')
  })

  it('registra el importe tipeado', () => {
    render(<ManualPaymentModal {...props} />)

    fireEvent.change(importe(), { target: { value: '2500' } })
    fireEvent.click(registrar())

    expect(props.onSubmit).toHaveBeenCalledWith(2500)
  })

  it.each(['', '0', '-5'])('no deja registrar un importe invalido (%p)', (valor) => {
    render(<ManualPaymentModal {...props} />)

    fireEvent.change(importe(), { target: { value: valor } })

    expect(registrar()).toBeDisabled()
    fireEvent.submit(registrar().closest('form') as HTMLFormElement)
    expect(props.onSubmit).not.toHaveBeenCalled()
  })

  it('sin precio conocido arranca vacio y pide el importe', () => {
    render(<ManualPaymentModal {...props} suggestedAmount={null} />)

    expect((importe() as HTMLInputElement).value).toBe('')
    expect(registrar()).toBeDisabled()
  })

  it('mientras envia no deja registrar dos veces y muestra el error', () => {
    render(<ManualPaymentModal {...props} busy error="No se pudo registrar el pago" />)

    expect(registrar()).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo registrar el pago')
  })

  it('cancelar cierra sin registrar', () => {
    render(<ManualPaymentModal {...props} />)

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))

    expect(props.onClose).toHaveBeenCalled()
    expect(props.onSubmit).not.toHaveBeenCalled()
  })
})
