/**
 * Jest Setup File
 * Runs before all tests
 */

import './jest-dom'

const customGlobal = globalThis as typeof globalThis & {
  crypto?: Crypto
  TextEncoder?: typeof TextEncoder
  TextDecoder?: typeof TextDecoder
}

const createTestUuid = (): `${string}-${string}-${string}-${string}-${string}` =>
  `00000000-0000-4000-8000-${Math.random().toString(16).slice(2).padEnd(12, '0').slice(0, 12)}`

if (typeof customGlobal.crypto === 'undefined') {
  try {
    Object.defineProperty(customGlobal, 'crypto', {
      value: {
        getRandomValues: <T extends ArrayBufferView>(array: T) => array,
        randomUUID: createTestUuid
      } as Crypto,
      writable: true
    })
  } catch (_error) {
    // Fail-safe fallback if the environment disallows redefining globals.
  }
}

if (typeof customGlobal.crypto?.randomUUID !== 'function') {
  try {
    Object.defineProperty(customGlobal.crypto, 'randomUUID', {
      value: createTestUuid,
      writable: true
    })
  } catch (_error) {
    // Fail-safe fallback if the environment disallows redefining globals.
  }
}

if (typeof customGlobal.TextEncoder === 'undefined') {
  class SimpleTextEncoder {
    encode(input = ''): Uint8Array {
      return new Uint8Array(Array.from(input).map((char) => char.charCodeAt(0)))
    }
  }

  try {
    Object.defineProperty(customGlobal, 'TextEncoder', {
      value: SimpleTextEncoder,
      writable: true
    })
  } catch (_error) {
    // Fail-safe fallback if the environment disallows redefining globals.
  }
}

if (typeof customGlobal.TextDecoder === 'undefined') {
  class SimpleTextDecoder {
    decode(input?: ArrayBufferView | ArrayBuffer | null): string {
      if (!input) return ''

      const view =
        input instanceof ArrayBuffer
          ? new Uint8Array(input)
          : new Uint8Array(input.buffer, input.byteOffset, input.byteLength)

      return Array.from(view)
        .map((code) => String.fromCharCode(code))
        .join('')
    }
  }

  try {
    Object.defineProperty(customGlobal, 'TextDecoder', {
      value: SimpleTextDecoder,
      writable: true
    })
  } catch (_error) {
    // Fail-safe fallback if the environment disallows redefining globals.
  }
}
