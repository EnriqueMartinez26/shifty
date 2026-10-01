/**
 * Clave de idempotencia de la reserva publica, estable al recargar (F4-04).
 *
 * El wizard la generaba en un useState: recargar despues de una respuesta
 * perdida mandaba el mismo pedido con otra clave y el backend no podia
 * devolver la reserva ya hecha. Se guarda {fpHash, key} por tienda en
 * sessionStorage (mismo modelo que otpSession.ts, con try/catch porque el
 * storage puede no existir). La huella es obligatoria: core/idempotency.py no
 * hashea el cuerpo y, con la misma clave y otros datos, devolveria la reserva
 * vieja; asi que la clave se reusa solo con la misma huella.
 *
 * La huella se guarda como SHA-256 del JSON del pedido, nunca en claro: el
 * pedido trae nombre, email y telefono del cliente (datos personales, Ley
 * 25.326) y sessionStorage lo lee cualquier script de la pagina. Sin
 * crypto.subtle (contexto inseguro, navegador viejo) o sin storage, la clave
 * queda solo en memoria mientras la pagina siga abierta.
 */

import { createUuid } from './uuid'

interface StoredBookingKey {
  fpHash: string
  key: string
}

interface MemoryBookingKey {
  /** El hash o, sin crypto.subtle, el JSON: vive solo en memoria. */
  fp: string
  key: string
}

const storageKey = (storeSlug: string): string => `shifty:booking-idem:${storeSlug}`

const inMemory = new Map<string, MemoryBookingKey>()

/** SHA-256 en hex, o null si el navegador no expone crypto.subtle. */
const sha256Hex = async (text: string): Promise<string | null> => {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) return null
  try {
    const digest = await subtle.digest('SHA-256', new TextEncoder().encode(text))
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  } catch {
    return null
  }
}

/** undefined: sin storage. null: no hay nada legible guardado. */
const readStored = (storeSlug: string): StoredBookingKey | null | undefined => {
  let raw: string | null
  try {
    raw = window.sessionStorage.getItem(storageKey(storeSlug))
  } catch {
    return undefined
  }
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<StoredBookingKey>
    return typeof parsed.fpHash === 'string' && typeof parsed.key === 'string' && parsed.key
      ? { fpHash: parsed.fpHash, key: parsed.key }
      : null
  } catch {
    // valor ilegible: se reemplaza con una clave nueva
    return null
  }
}

const memoryKey = (storeSlug: string, fp: string): string => {
  const remembered = inMemory.get(storeSlug)
  if (remembered?.fp === fp) return remembered.key
  const next = { fp, key: createUuid() }
  inMemory.set(storeSlug, next)
  return next.key
}

/**
 * La clave para el pedido con este JSON: la guardada si la huella coincide,
 * o una nueva que reemplaza a la anterior.
 */
export const bookingIdempotencyKey = async (
  storeSlug: string,
  payloadJson: string
): Promise<string> => {
  const fpHash = await sha256Hex(payloadJson)
  // Sin hash no se escribe nada: el JSON en claro no va al storage.
  if (fpHash === null) return memoryKey(storeSlug, payloadJson)

  const stored = readStored(storeSlug)
  if (stored?.fpHash === fpHash) return stored.key
  // La memoria cubre tambien un setItem que fallo (storage lleno).
  const key = memoryKey(storeSlug, fpHash)
  if (stored === undefined) return key
  try {
    const next: StoredBookingKey = { fpHash, key }
    window.sessionStorage.setItem(storageKey(storeSlug), JSON.stringify(next))
  } catch {
    // no se pudo guardar: queda en memoria
  }
  return key
}

/** La reserva quedo confirmada: el proximo pedido lleva otra clave. */
export const forgetBookingIdempotency = (storeSlug: string): void => {
  inMemory.delete(storeSlug)
  try {
    window.sessionStorage.removeItem(storageKey(storeSlug))
  } catch {
    // sin storage: ya se olvido la de memoria
  }
}
