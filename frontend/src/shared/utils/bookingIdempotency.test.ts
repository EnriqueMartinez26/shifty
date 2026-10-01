import { bookingIdempotencyKey, forgetBookingIdempotency } from './bookingIdempotency'

/**
 * F4-04 a (2026-10-01): la clave de idempotencia del wizard salia de
 * createUuid() en un useState: al recargar la pagina tras una respuesta
 * perdida se mandaba otra clave y el backend no podia devolver la reserva ya
 * hecha. Se guarda por tienda en sessionStorage junto con la huella del
 * pedido: el backend (core/idempotency.py) no hashea el cuerpo y, con la
 * misma clave y otros datos, devolveria la reserva vieja.
 */
describe('bookingIdempotencyKey', () => {
  const pedido = JSON.stringify({ service_id: 'svc-1', starts_at: '2026-10-02T12:00:00+00:00' })
  const otroPedido = JSON.stringify({ service_id: 'svc-1', starts_at: '2026-10-02T13:00:00+00:00' })

  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('con la misma huella devuelve la misma clave, tambien leyendola del storage', () => {
    const primera = bookingIdempotencyKey('sol', pedido)

    expect(primera).not.toBe('')
    expect(bookingIdempotencyKey('sol', pedido)).toBe(primera)
    expect(JSON.parse(window.sessionStorage.getItem('shifty:booking-idem:sol') ?? '{}')).toEqual({
      fp: pedido,
      key: primera
    })
  })

  it('con otra huella genera una clave nueva y la guarda en lugar de la anterior', () => {
    const primera = bookingIdempotencyKey('sol', pedido)

    const segunda = bookingIdempotencyKey('sol', otroPedido)

    expect(segunda).not.toBe(primera)
    expect(bookingIdempotencyKey('sol', otroPedido)).toBe(segunda)
    // Volver a los datos del primer intento ya no reusa su clave.
    expect(bookingIdempotencyKey('sol', pedido)).not.toBe(primera)
  })

  it('cada tienda tiene su propia clave', () => {
    expect(bookingIdempotencyKey('sol', pedido)).not.toBe(bookingIdempotencyKey('luna', pedido))
  })

  it('al confirmar la reserva se borra y el proximo pedido igual lleva otra clave', () => {
    const primera = bookingIdempotencyKey('sol', pedido)

    forgetBookingIdempotency('sol')

    expect(window.sessionStorage.getItem('shifty:booking-idem:sol')).toBeNull()
    expect(bookingIdempotencyKey('sol', pedido)).not.toBe(primera)
  })

  it('un valor ilegible en el storage no rompe: se genera una clave nueva', () => {
    window.sessionStorage.setItem('shifty:booking-idem:sol', '{no es json')

    const clave = bookingIdempotencyKey('sol', pedido)

    expect(clave).not.toBe('')
    expect(bookingIdempotencyKey('sol', pedido)).toBe(clave)
  })

  describe('sin storage (modo privado, bloqueado)', () => {
    let getItem: jest.SpyInstance
    let setItem: jest.SpyInstance
    let removeItem: jest.SpyInstance

    beforeEach(() => {
      const bloqueado = () => {
        throw new DOMException('bloqueado', 'SecurityError')
      }
      getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(bloqueado)
      setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(bloqueado)
      removeItem = jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(bloqueado)
    })

    afterEach(() => {
      getItem.mockRestore()
      setItem.mockRestore()
      removeItem.mockRestore()
    })

    it('no rompe y mientras la pagina siga abierta reusa la clave del mismo pedido', () => {
      const primera = bookingIdempotencyKey('sol', pedido)

      expect(primera).not.toBe('')
      expect(bookingIdempotencyKey('sol', pedido)).toBe(primera)
      expect(bookingIdempotencyKey('sol', otroPedido)).not.toBe(primera)
      expect(() => forgetBookingIdempotency('sol')).not.toThrow()
      expect(bookingIdempotencyKey('sol', otroPedido)).not.toBe(primera)
    })
  })
})
