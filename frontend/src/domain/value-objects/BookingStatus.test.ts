import { BookingStatus } from './BookingStatus'

describe('BookingStatus Value Object', () => {
  it('debe instanciar con estados válidos', () => {
    expect(BookingStatus.create('pending').getValue()).toBe('pending')
    expect(BookingStatus.create('pending_payment').getValue()).toBe('pending_payment')
    expect(BookingStatus.create('confirmed').getValue()).toBe('confirmed')
    expect(BookingStatus.create('completed').getValue()).toBe('completed')
    expect(BookingStatus.create('expired').getValue()).toBe('expired')
  })

  it('debe arrojar error con estado inválido', () => {
    expect(() => BookingStatus.create('finished')).toThrow('Estado de reserva inválido: finished')
  })

  it('debe verificar si está finalizado', () => {
    expect(BookingStatus.create('pending').isFinalized()).toBe(false)
    expect(BookingStatus.create('pending_payment').isFinalized()).toBe(false)
    expect(BookingStatus.create('completed').isFinalized()).toBe(true)
    expect(BookingStatus.create('cancelled').isFinalized()).toBe(true)
    expect(BookingStatus.create('absent').isFinalized()).toBe(true)
    expect(BookingStatus.create('expired').isFinalized()).toBe(true)
  })
})
