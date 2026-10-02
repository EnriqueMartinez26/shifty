import { bookingIdempotencyKey, forgetBookingIdempotency } from './bookingIdempotency'

/**
 * F4-04 a (2026-10-01): la clave de idempotencia del wizard salia de
 * createUuid() en un useState: al recargar la pagina tras una respuesta
 * perdida se mandaba otra clave y el backend no podia devolver la reserva ya
 * hecha. Se guarda por tienda en sessionStorage junto con la huella del
 * pedido: el backend (core/idempotency.py) no hashea el cuerpo y, con la
 * misma clave y otros datos, devolveria la reserva vieja.
 *
 * 2026-10-01 (review de #83): la huella era el JSON del pedido en claro, con
 * nombre, email y telefono del cliente en sessionStorage (datos personales,
 * Ley 25.326). Ahora se guarda solo su SHA-256.
 */
describe('bookingIdempotencyKey', () => {
  const pedido = JSON.stringify({
    service_id: 'svc-1',
    starts_at: '2026-10-02T12:00:00+00:00',
    client_name: 'Lucia Perez',
    client_email: 'lucia@example.com',
    client_phone: '+5491155550101'
  })
  const otroPedido = pedido.replace('12:00:00', '13:00:00')
  const guardado = (slug = 'sol') => window.sessionStorage.getItem(`shifty:booking-idem:${slug}`)

  beforeEach(() => {
    window.sessionStorage.clear()
    forgetBookingIdempotency('sol')
    forgetBookingIdempotency('luna')
  })

  it('guarda solo un hash del pedido, sin datos personales', async () => {
    const clave = await bookingIdempotencyKey('sol', pedido)

    const crudo = guardado() ?? ''
    expect(crudo).not.toContain('lucia@example.com')
    expect(crudo).not.toContain('5491155550101')
    expect(crudo).not.toContain('1155550101')
    expect(crudo).not.toContain('Lucia')
    const valor = JSON.parse(crudo) as Record<string, unknown>
    expect(Object.keys(valor).sort()).toEqual(['fpHash', 'key'])
    expect(valor.fpHash).toMatch(/^[0-9a-f]{64}$/)
    expect(valor.key).toBe(clave)
  })

  it('con los mismos datos devuelve la misma clave, tambien leyendola del storage', async () => {
    const primera = await bookingIdempotencyKey('sol', pedido)
    const guardadoAntes = guardado()

    expect(primera).not.toBe('')
    expect(await bookingIdempotencyKey('sol', pedido)).toBe(primera)
    expect(guardado()).toBe(guardadoAntes)
  })

  it('con otros datos genera una clave nueva y la guarda en lugar de la anterior', async () => {
    const primera = await bookingIdempotencyKey('sol', pedido)

    const segunda = await bookingIdempotencyKey('sol', otroPedido)

    expect(segunda).not.toBe(primera)
    expect(await bookingIdempotencyKey('sol', otroPedido)).toBe(segunda)
    // Volver a los datos del primer intento ya no reusa su clave.
    expect(await bookingIdempotencyKey('sol', pedido)).not.toBe(primera)
  })

  it('cada tienda tiene su propia clave', async () => {
    expect(await bookingIdempotencyKey('sol', pedido)).not.toBe(
      await bookingIdempotencyKey('luna', pedido)
    )
  })

  it('al confirmar la reserva se borra y el proximo pedido igual lleva otra clave', async () => {
    const primera = await bookingIdempotencyKey('sol', pedido)

    forgetBookingIdempotency('sol')

    expect(guardado()).toBeNull()
    expect(await bookingIdempotencyKey('sol', pedido)).not.toBe(primera)
  })

  it('un valor ilegible en el storage no rompe: se genera una clave nueva', async () => {
    window.sessionStorage.setItem('shifty:booking-idem:sol', '{no es json')

    const clave = await bookingIdempotencyKey('sol', pedido)

    expect(clave).not.toBe('')
    expect(await bookingIdempotencyKey('sol', pedido)).toBe(clave)
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

    it('no rompe y mientras la pagina siga abierta reusa la clave del mismo pedido', async () => {
      const primera = await bookingIdempotencyKey('sol', pedido)

      expect(primera).not.toBe('')
      expect(await bookingIdempotencyKey('sol', pedido)).toBe(primera)
      expect(await bookingIdempotencyKey('sol', otroPedido)).not.toBe(primera)
      expect(() => forgetBookingIdempotency('sol')).not.toThrow()
      expect(await bookingIdempotencyKey('sol', otroPedido)).not.toBe(primera)
    })
  })

  describe('sin crypto.subtle (contexto inseguro, navegador viejo)', () => {
    const subtle = globalThis.crypto.subtle

    beforeEach(() => {
      Object.defineProperty(globalThis.crypto, 'subtle', { value: undefined, configurable: true })
    })

    afterEach(() => {
      Object.defineProperty(globalThis.crypto, 'subtle', { value: subtle, configurable: true })
    })

    it('no guarda nada en el storage y reusa la clave en memoria mientras la pagina siga abierta', async () => {
      const primera = await bookingIdempotencyKey('sol', pedido)

      expect(guardado()).toBeNull()
      expect(await bookingIdempotencyKey('sol', pedido)).toBe(primera)
      expect(await bookingIdempotencyKey('sol', otroPedido)).not.toBe(primera)
      expect(guardado()).toBeNull()
    })
  })
})
