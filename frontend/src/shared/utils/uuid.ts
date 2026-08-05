/**
 * Genera un UUID v4 valido (RFC 4122).
 *
 * Prioridad:
 *  1. `crypto.randomUUID()` cuando esta disponible (contextos seguros: https/localhost).
 *  2. `crypto.getRandomValues()` para construir un v4 manualmente. Disponible tambien
 *     en contextos NO seguros (http), donde `randomUUID` puede no existir.
 *  3. Si no hay Web Crypto, se lanza un error en lugar de devolver un id invalido:
 *     preferimos fallar ruidosamente antes que enviar identificadores no-UUID al backend.
 */
export function createUuid(): string {
  const cryptoApi = globalThis.crypto

  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }

  if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10xx
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
    return (
      `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-` +
      `${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
    )
  }

  throw new Error('Web Crypto API no disponible: no se puede generar un UUID seguro')
}
