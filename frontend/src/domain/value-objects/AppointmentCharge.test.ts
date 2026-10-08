import { appointmentChargeOf } from './AppointmentCharge'

// 2026-10-08, QA en el celular (decision de Mateo): "Confirmar pago" no pedia
// importe y, despues de pagar, la tarjeta seguia igual. El importe se precarga
// con la sena pendiente si el turno tiene un cobro vivo; si no, con el precio
// del turno menos lo pagado. Despues de pagar se ve lo pagado y lo que resta.
describe('appointmentChargeOf', () => {
  const base = {
    appointmentStatus: 'confirmed',
    priceAmount: '3200.00',
    paymentStatus: null,
    paymentAmount: null
  }

  it('sin cobro sugiere el precio del turno', () => {
    expect(appointmentChargeOf(base)).toEqual({ kind: 'unpaid', suggested: 3200 })
  })

  it('sin precio conocido no inventa un importe', () => {
    expect(appointmentChargeOf({ ...base, priceAmount: null })).toEqual({
      kind: 'unpaid',
      suggested: null
    })
  })

  it.each(['pending', 'rejected'])('con un cobro vivo (%s) sugiere la sena pendiente', (status) => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: status, paymentAmount: '960.00' })
    ).toEqual({ kind: 'deposit', amount: 960 })
  })

  it('un cobro vencido ya no es la sena: vuelve a sugerir el precio', () => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: 'expired', paymentAmount: '960.00' })
    ).toEqual({ kind: 'unpaid', suggested: 3200 })
  })

  it.each(['approved', 'manual_confirmed'])(
    'con el cobro acreditado (%s) muestra lo pagado y lo que resta',
    (status) => {
      expect(
        appointmentChargeOf({ ...base, paymentStatus: status, paymentAmount: '960.00' })
      ).toEqual({ kind: 'paid', paid: 960, remaining: 2240 })
    }
  )

  it('pagado completo no deja resto', () => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: 'approved', paymentAmount: '3200.00' })
    ).toEqual({ kind: 'paid', paid: 3200, remaining: 0 })
  })

  it('un ausente no debe el resto del servicio que no recibio', () => {
    expect(
      appointmentChargeOf({
        ...base,
        appointmentStatus: 'absent',
        paymentStatus: 'approved',
        paymentAmount: '960.00'
      })
    ).toEqual({ kind: 'paid', paid: 960, remaining: 0 })
  })

  it('un cobro reembolsado no ofrece cobrar de nuevo', () => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: 'refunded', paymentAmount: '960.00' })
    ).toEqual({ kind: 'refunded' })
  })
})
