import { appointmentChargeOf, canRecordRemainder, fitsRemaining } from './AppointmentCharge'

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
    ).toEqual({ kind: 'pending', amount: 960, isDeposit: true })
  })

  // Revision de la PR #131 (S1, 2026-10-08): un link del panel por el precio
  // completo se mostraba como "Seña pendiente". Es sena solo si cobra menos
  // que el precio del turno.
  it('un cobro vivo por el precio completo es un pago pendiente, no una sena', () => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: 'pending', paymentAmount: '3200.00' })
    ).toEqual({ kind: 'pending', amount: 3200, isDeposit: false })
  })

  it('sin precio conocido un cobro vivo no se llama sena', () => {
    expect(
      appointmentChargeOf({
        ...base,
        priceAmount: null,
        paymentStatus: 'pending',
        paymentAmount: '960.00'
      })
    ).toEqual({ kind: 'pending', amount: 960, isDeposit: false })
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
      ).toEqual({ kind: 'paid', paid: 960, remaining: 2240, remainderRecorded: false })
    }
  )

  it('pagado completo no deja resto', () => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: 'approved', paymentAmount: '3200.00' })
    ).toEqual({ kind: 'paid', paid: 3200, remaining: 0, remainderRecorded: false })
  })

  it('un ausente no debe el resto del servicio que no recibio', () => {
    expect(
      appointmentChargeOf({
        ...base,
        appointmentStatus: 'absent',
        paymentStatus: 'approved',
        paymentAmount: '960.00'
      })
    ).toEqual({ kind: 'paid', paid: 960, remaining: 0, remainderRecorded: false })
  })

  it('un cobro reembolsado no ofrece cobrar de nuevo', () => {
    expect(
      appointmentChargeOf({ ...base, paymentStatus: 'refunded', paymentAmount: '960.00' })
    ).toEqual({ kind: 'refunded' })
  })
})

// Saldo restante por turno (D-20261008-01): una sena acreditada de $960 sobre
// un turno de $3.200 deja $2.240 que el cliente paga en el local. El saldo lo
// calcula el backend en SQL; la pantalla lo muestra y ofrece registrar el
// resto una sola vez.
describe('appointmentChargeOf: saldo restante', () => {
  const pagado = {
    appointmentStatus: 'completed',
    priceAmount: '3200.00',
    paymentStatus: 'approved',
    paymentAmount: '960.00'
  }

  it('usa el saldo que calcula el backend', () => {
    expect(appointmentChargeOf({ ...pagado, remainingAmount: '100.00' })).toEqual({
      kind: 'paid',
      paid: 960,
      remaining: 100,
      remainderRecorded: false
    })
  })

  it('con el resto registrado lo pagado es la sena mas el resto', () => {
    expect(
      appointmentChargeOf({ ...pagado, remainingAmount: '0.00', remainderAmount: '2240.00' })
    ).toEqual({ kind: 'paid', paid: 3200, remaining: 0, remainderRecorded: true })
  })

  it('un resto parcial deja lo que falta, pero no se registra otro', () => {
    const charge = appointmentChargeOf({
      ...pagado,
      remainingAmount: '240.00',
      remainderAmount: '2000.00'
    })
    expect(charge).toEqual({ kind: 'paid', paid: 2960, remaining: 240, remainderRecorded: true })
    expect(canRecordRemainder(charge)).toBe(false)
  })

  it('ofrece registrar el resto solo si queda saldo y no hay uno registrado', () => {
    expect(canRecordRemainder(appointmentChargeOf({ ...pagado, remainingAmount: '2240.00' }))).toBe(
      true
    )
    expect(canRecordRemainder(appointmentChargeOf({ ...pagado, remainingAmount: '0.00' }))).toBe(
      false
    )
    expect(
      canRecordRemainder(
        appointmentChargeOf({ ...pagado, paymentStatus: 'pending', remainingAmount: null })
      )
    ).toBe(false)
    expect(canRecordRemainder({ kind: 'unpaid', suggested: 3200 })).toBe(false)
  })

  it('un ausente no debe el resto aunque el backend no mande el saldo', () => {
    const charge = appointmentChargeOf({ ...pagado, appointmentStatus: 'absent' })
    expect(charge).toEqual({ kind: 'paid', paid: 960, remaining: 0, remainderRecorded: false })
    expect(canRecordRemainder(charge)).toBe(false)
  })

  it('el importe del resto tiene que entrar en el saldo, al centavo', () => {
    expect(fitsRemaining(2240.1, 2240.1)).toBe(true)
    expect(fitsRemaining(1, 2240.1)).toBe(true)
    expect(fitsRemaining(2240.11, 2240.1)).toBe(false)
    expect(fitsRemaining(0, 2240.1)).toBe(false)
  })
})
