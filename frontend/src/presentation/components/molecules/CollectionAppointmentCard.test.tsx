import { fireEvent, render, screen } from '@testing-library/react'

import type { AppointmentCharge } from '@domain/value-objects/AppointmentCharge'

import { CollectionAppointmentCard } from './CollectionAppointmentCard'

// Saldo restante por turno (D-20261008-01): la tarjeta de un turno con la
// sena acreditada dice "Pagado $960 · Resta $2.240" y ofrece registrar el
// resto. Registrado, dice "Pagado $3.200" y ya no lo ofrece.
describe('CollectionAppointmentCard: saldo restante', () => {
  const props = {
    clientName: 'Lucia',
    serviceName: 'Corte',
    staffName: 'Ana',
    startsAt: '2026-10-08T13:00:00Z',
    status: 'completed',
    latestLink: null,
    linkBlockedReason: null,
    confirmBlockedReason: null,
    remainderBlockedReason: null,
    onCreateLink: jest.fn(),
    onConfirmPayment: jest.fn(),
    onRecordRemainder: jest.fn(),
    onRevertRemainder: null
  }
  const conSaldo: AppointmentCharge = {
    kind: 'paid',
    paid: 960,
    remaining: 2240,
    remainderRecorded: false
  }
  const saldado: AppointmentCharge = {
    kind: 'paid',
    paid: 3200,
    remaining: 0,
    remainderRecorded: true
  }
  const registrarResto = () => screen.queryByRole('button', { name: /Registrar resto/ })

  beforeEach(() => {
    props.onRecordRemainder.mockClear()
  })

  it('con saldo muestra lo pagado, lo que resta y ofrece registrar el resto', () => {
    render(<CollectionAppointmentCard {...props} charge={conSaldo} />)

    expect(screen.getByText(/Pagado/)).toHaveTextContent('960')
    expect(screen.getByText(/Resta/)).toHaveTextContent('2.240')
    fireEvent.click(registrarResto() as HTMLElement)
    expect(props.onRecordRemainder).toHaveBeenCalledTimes(1)
    // Pagado no vuelve a ofrecer el cobro entero.
    expect(screen.queryByRole('button', { name: /Confirmar pago/ })).not.toBeInTheDocument()
  })

  it('con el resto registrado muestra el total pagado y no ofrece nada mas', () => {
    render(<CollectionAppointmentCard {...props} charge={saldado} />)

    expect(screen.getByText(/Pagado/)).toHaveTextContent('3.200')
    expect(screen.queryByText(/Resta/)).not.toBeInTheDocument()
    expect(registrarResto()).not.toBeInTheDocument()
  })

  it('sin saldo (un ausente, o pagado completo) no ofrece registrar el resto', () => {
    render(
      <CollectionAppointmentCard
        {...props}
        status="absent"
        charge={{ kind: 'paid', paid: 960, remaining: 0, remainderRecorded: false }}
      />
    )

    expect(registrarResto()).not.toBeInTheDocument()
  })

  it('con un motivo de bloqueo lo deshabilita y lo explica', () => {
    render(
      <CollectionAppointmentCard
        {...props}
        charge={conSaldo}
        remainderBlockedReason="Tienda suspendida"
      />
    )

    expect(registrarResto()).toBeDisabled()
    expect(registrarResto()).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('revertir el resto aparece solo si se puede (admin) y hay un resto', () => {
    const onRevertRemainder = jest.fn()
    const { rerender } = render(
      <CollectionAppointmentCard
        {...props}
        charge={saldado}
        onRevertRemainder={onRevertRemainder}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Revertir resto/ }))
    expect(onRevertRemainder).toHaveBeenCalledTimes(1)

    rerender(<CollectionAppointmentCard {...props} charge={saldado} onRevertRemainder={null} />)
    expect(screen.queryByRole('button', { name: /Revertir resto/ })).not.toBeInTheDocument()

    rerender(
      <CollectionAppointmentCard
        {...props}
        charge={conSaldo}
        onRevertRemainder={onRevertRemainder}
      />
    )
    expect(screen.queryByRole('button', { name: /Revertir resto/ })).not.toBeInTheDocument()
  })
})
