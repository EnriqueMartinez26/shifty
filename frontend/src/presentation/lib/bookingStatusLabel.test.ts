import { bookingStatusLabel } from './bookingStatusLabel'

describe('bookingStatusLabel', () => {
  it('traduce los estados conocidos', () => {
    expect(bookingStatusLabel('pending_payment')).toBe('Pendiente de pago')
    expect(bookingStatusLabel('absent')).toBe('Ausente')
  })

  it('muestra crudo un estado que el front todavia no conoce', () => {
    expect(bookingStatusLabel('on_hold')).toBe('on_hold')
  })
})
