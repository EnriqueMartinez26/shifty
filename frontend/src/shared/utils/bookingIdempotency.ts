/**
 * Clave de idempotencia de la reserva publica, estable al recargar (F4-04).
 *
 * El wizard la generaba en un useState: recargar despues de una respuesta
 * perdida mandaba el mismo pedido con otra clave y el backend no podia
 * devolver la reserva ya hecha. Se guarda {fp, key} por tienda en
 * sessionStorage (mismo modelo que otpSession.ts, con try/catch porque el
 * storage puede no existir). La huella `fp` es obligatoria:
 * core/idempotency.py no hashea el cuerpo y, con la misma clave y otros
 * datos, devolveria la reserva vieja; asi que la clave se reusa solo con la
 * misma huella. Sin storage queda en memoria mientras la pagina siga abierta.
 */

import { createUuid } from './uuid'

interface StoredBookingKey {
  fp: string
  key: string
}

const storageKey = (storeSlug: string): string => `shifty:booking-idem:${storeSlug}`

const inMemory = new Map<string, StoredBookingKey>()

const readStored = (storeSlug: string): StoredBookingKey | null => {
  let raw: string | null
  try {
    raw = window.sessionStorage.getItem(storageKey(storeSlug))
  } catch {
    // sin storage (privado, bloqueado): vale lo que quedo en memoria
    return inMemory.get(storeSlug) ?? null
  }
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<StoredBookingKey>
    return typeof parsed.fp === 'string' && typeof parsed.key === 'string' && parsed.key
      ? { fp: parsed.fp, key: parsed.key }
      : null
  } catch {
    // valor ilegible: se reemplaza con una clave nueva
    return null
  }
}

/**
 * La clave para el pedido con esta huella: la guardada si la huella coincide,
 * o una nueva que reemplaza a la anterior.
 */
export const bookingIdempotencyKey = (storeSlug: string, fp: string): string => {
  const stored = readStored(storeSlug)
  if (stored?.fp === fp) return stored.key
  const next: StoredBookingKey = { fp, key: createUuid() }
  inMemory.set(storeSlug, next)
  try {
    window.sessionStorage.setItem(storageKey(storeSlug), JSON.stringify(next))
  } catch {
    // sin storage: queda solo en memoria
  }
  return next.key
}

/** La reserva quedo confirmada: el proximo pedido lleva otra clave. */
export const forgetBookingIdempotency = (storeSlug: string): void => {
  inMemory.delete(storeSlug)
  try {
    window.sessionStorage.removeItem(storageKey(storeSlug))
  } catch {
    // idem
  }
}
