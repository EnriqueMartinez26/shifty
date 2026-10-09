import { NetworkError, RateLimitError, ServiceUnavailableError } from '@shared/errors'

import {
  createSessionSync,
  detectLocks,
  openChannel,
  PEER_LOGOUT_EVENT,
  PEER_SESSION_EVENT,
  SESSION_RECONNECTING_EVENT
} from './sessionSync'

/**
 * 2026-09-28 (F4-01, F4-02). Sintomas que estos tests fijan:
 * - dos pestanas (o StrictMode) refrescaban a la vez; el backend rota la
 *   sesion en cada refresh y toma el segundo como reuso: logout en todos los
 *   dispositivos;
 * - cualquier falla del refresh (red, 429, 503) cerraba la sesion.
 */

type Deps = Parameters<typeof createSessionSync>[0]
type Locks = NonNullable<Deps['locks']>
type Channel = NonNullable<Deps['channel']>

/** Web Lock falso: serializa los callbacks como `navigator.locks.request`. */
const createFakeLocks = (): Locks => {
  let tail: Promise<unknown> = Promise.resolve()
  return {
    request: (_name, callback) => {
      const run = tail.then(() => callback())
      tail = run.catch(() => undefined)
      return run
    }
  }
}

/** BroadcastChannel falso: entrega a las OTRAS puntas, no a quien publica. */
const createFakeHub = () => {
  const endpoints: Channel[] = []
  const open = (): Channel => {
    const endpoint: Channel = {
      onmessage: null,
      postMessage: (message) => {
        for (const other of endpoints) {
          if (other !== endpoint) other.onmessage?.({ data: message } as MessageEvent)
        }
      }
    }
    endpoints.push(endpoint)
    return endpoint
  }
  return { open, endpoints }
}

const createTab = (
  requestRefresh: Deps['requestRefresh'],
  options: {
    locks?: Locks
    channel?: Channel
    token?: string | null
    sleep?: () => Promise<void>
  } = {}
) => {
  let token: string | null = options.token ?? null
  const events: Event[] = []
  const sleeps: number[] = []
  const sync = createSessionSync({
    requestRefresh,
    getToken: () => token,
    setToken: (next) => {
      token = next
    },
    locks: options.locks,
    channel: options.channel,
    sleep: async (ms) => {
      sleeps.push(ms)
      await options.sleep?.()
    },
    dispatch: (event) => events.push(event)
  })
  return { sync, events, sleeps, token: () => token }
}

const httpError = (status: number, headers: Record<string, string> = {}) => ({
  response: {
    status,
    headers,
    data: { success: false, error_code: 'X', message: 'fallo' }
  },
  message: `HTTP ${status}`
})

const deferred = <T>() => {
  let resolve: (value: T) => void = () => undefined
  let reject: (reason: unknown) => void = () => undefined
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('refresh coordinado entre pestanas', () => {
  it('dos pestanas que vencen a la vez hacen UN solo POST y comparten el token', async () => {
    const respuesta = deferred<string | null>()
    const requestRefresh = jest.fn(() => respuesta.promise)
    const hub = createFakeHub()
    const locks = createFakeLocks()
    const tabA = createTab(requestRefresh, { locks, channel: hub.open(), token: 'viejo' })
    const tabB = createTab(requestRefresh, { locks, channel: hub.open(), token: 'viejo' })

    const enA = tabA.sync.refreshAccessToken('viejo')
    const enB = tabB.sync.refreshAccessToken('viejo')
    respuesta.resolve('nuevo')

    await expect(enA).resolves.toEqual({ kind: 'ok', token: 'nuevo' })
    await expect(enB).resolves.toEqual({ kind: 'ok', token: 'nuevo' })
    expect(requestRefresh).toHaveBeenCalledTimes(1)
    expect(tabB.token()).toBe('nuevo')
  })

  it('la pestana que no refresco adopta el token difundido, solo en memoria', async () => {
    const hub = createFakeHub()
    const tabA = createTab(async () => 'nuevo', { channel: hub.open() })
    const tabB = createTab(jest.fn(), { channel: hub.open(), token: 'viejo' })
    const setItem = jest.spyOn(Storage.prototype, 'setItem')

    await tabA.sync.refreshAccessToken(null)

    expect(tabB.token()).toBe('nuevo')
    expect(setItem).not.toHaveBeenCalled()
    setItem.mockRestore()
  })

  it('si el token ya cambio al entrar al lock, no pide otro', async () => {
    const requestRefresh = jest.fn(async () => 'otro')
    const tab = createTab(requestRefresh, { locks: createFakeLocks(), token: 'vigente' })

    await expect(tab.sync.refreshAccessToken('vencido')).resolves.toEqual({
      kind: 'ok',
      token: 'vigente'
    })
    expect(requestRefresh).not.toHaveBeenCalled()
  })

  // 4R 2026-09-28: un 401 del refresh mandaba 'logout' a todas las pestanas,
  // aunque fuera solo la carrera perdida (ventana de gracia del backend).
  it.each([401, 403])(
    'un %i del refresh termina la sesion SOLO en esta pestana',
    async (status) => {
      const hub = createFakeHub()
      const tabA = createTab(() => Promise.reject(httpError(status)), {
        channel: hub.open(),
        token: 'viejo'
      })
      const tabB = createTab(jest.fn(), { channel: hub.open(), token: 'viejo' })

      await expect(tabA.sync.refreshAccessToken('viejo')).resolves.toEqual({ kind: 'expired' })

      expect(tabA.token()).toBeNull()
      expect(tabA.sleeps).toEqual([])
      expect(tabB.token()).toBe('viejo')
      expect(tabB.events).toEqual([])
    }
  )

  it('sin locks, la que pierde la carrera adopta el token del ganador que llega durante su 401', async () => {
    const ganador = deferred<string | null>()
    const perdedor = deferred<string | null>()
    const hub = createFakeHub()
    const tabA = createTab(() => ganador.promise, { channel: hub.open(), token: 'viejo' })
    const tabB = createTab(() => perdedor.promise, { channel: hub.open(), token: 'viejo' })

    const enA = tabA.sync.refreshAccessToken('viejo')
    const enB = tabB.sync.refreshAccessToken('viejo')
    ganador.resolve('nuevo')
    await enA
    perdedor.reject(httpError(401))

    await expect(enB).resolves.toEqual({ kind: 'ok', token: 'nuevo' })
    expect(tabA.token()).toBe('nuevo')
    expect(tabB.token()).toBe('nuevo')
    expect([...tabA.events, ...tabB.events].map((e) => e.type)).not.toContain(PEER_LOGOUT_EVENT)
  })

  it('el lock no se retiene durante la espera: la otra pestana refresca y esta adopta', async () => {
    const requestRefresh = jest
      .fn<Promise<string | null>, []>()
      .mockRejectedValueOnce(httpError(503, { 'retry-after': '5' }))
      .mockResolvedValueOnce('nuevo')
    const espera = deferred<void>()
    const hub = createFakeHub()
    const locks = createFakeLocks()
    const tabA = createTab(requestRefresh, {
      locks,
      channel: hub.open(),
      token: 'viejo',
      sleep: () => espera.promise
    })
    const tabB = createTab(requestRefresh, { locks, channel: hub.open(), token: 'viejo' })

    const enA = tabA.sync.refreshAccessToken('viejo')
    await new Promise((r) => setTimeout(r, 0))
    await expect(tabB.sync.refreshAccessToken('viejo')).resolves.toEqual({
      kind: 'ok',
      token: 'nuevo'
    })
    espera.resolve()

    await expect(enA).resolves.toEqual({ kind: 'ok', token: 'nuevo' })
    expect(requestRefresh).toHaveBeenCalledTimes(2)
  })

  it('un 200 sin token cuenta como sesion terminada', async () => {
    const tab = createTab(async () => null, { token: 'viejo' })

    await expect(tab.sync.refreshAccessToken('viejo')).resolves.toEqual({ kind: 'expired' })
    expect(tab.token()).toBeNull()
  })
})

describe('fallas transitorias del refresh (D-20260928-03)', () => {
  it('sin red: reintenta 3 veces con espera creciente y conserva el token', async () => {
    const requestRefresh = jest.fn(() => Promise.reject({ message: 'Network Error' }))
    const tab = createTab(requestRefresh, { token: 'vigente' })

    const result = await tab.sync.refreshAccessToken('vigente')

    expect(result).toMatchObject({ kind: 'transient' })
    expect(result.kind === 'transient' && result.error).toBeInstanceOf(NetworkError)
    expect(requestRefresh).toHaveBeenCalledTimes(4)
    expect(tab.sleeps).toEqual([1_000, 2_000, 4_000])
    expect(tab.token()).toBe('vigente')
  })

  it('un 429 respeta Retry-After y corta antes de pasar los 30 s', async () => {
    const requestRefresh = jest.fn(() => Promise.reject(httpError(429, { 'retry-after': '20' })))
    const tab = createTab(requestRefresh, { token: 'vigente' })

    const result = await tab.sync.refreshAccessToken('vigente')

    expect(result).toMatchObject({ kind: 'transient', retryAfter: 20 })
    expect(result.kind === 'transient' && result.error).toBeInstanceOf(RateLimitError)
    expect(tab.sleeps).toEqual([20_000])
    expect(requestRefresh).toHaveBeenCalledTimes(2)
    expect(tab.token()).toBe('vigente')
  })

  it('un 503 que se recupera deja la sesion y avisa "reconectando" mientras espera', async () => {
    const requestRefresh = jest
      .fn<Promise<string | null>, []>()
      .mockRejectedValueOnce(httpError(503, { 'retry-after': '5' }))
      .mockResolvedValueOnce('nuevo')
    const tab = createTab(requestRefresh, { token: 'viejo' })

    await expect(tab.sync.refreshAccessToken('viejo')).resolves.toEqual({
      kind: 'ok',
      token: 'nuevo'
    })

    expect(tab.sleeps).toEqual([5_000])
    const reconectando = tab.events
      .filter((event) => event.type === SESSION_RECONNECTING_EVENT)
      .map((event) => (event as CustomEvent<boolean>).detail)
    expect(reconectando).toEqual([true, false])
  })

  it('un 503 persistente devuelve el error normalizado sin cerrar la sesion', async () => {
    const tab = createTab(() => Promise.reject(httpError(503, { 'retry-after': '1' })), {
      token: 'vigente'
    })

    const result = await tab.sync.refreshAccessToken('vigente')

    expect(result.kind === 'transient' && result.error).toBeInstanceOf(ServiceUnavailableError)
    expect(tab.sleeps).toEqual([1_000, 1_000, 1_000])
    expect(tab.token()).toBe('vigente')
  })

  it('un 4xx que no es 401/403 no se reintenta ni cierra la sesion', async () => {
    const requestRefresh = jest.fn(() => Promise.reject(httpError(422)))
    const tab = createTab(requestRefresh, { token: 'vigente' })

    await expect(tab.sync.refreshAccessToken('vigente')).resolves.toMatchObject({
      kind: 'transient'
    })
    expect(requestRefresh).toHaveBeenCalledTimes(1)
    expect(tab.token()).toBe('vigente')
  })
})

describe('mensajes de otras pestanas', () => {
  it('un login en otra pestana trae su token y avisa quien es', () => {
    const hub = createFakeHub()
    const tabA = createTab(jest.fn(), { channel: hub.open() })
    const tabB = createTab(jest.fn(), { channel: hub.open(), token: 'de-otro' })

    tabA.sync.broadcastSession('usuario-b', 'token-b')

    expect(tabB.token()).toBe('token-b')
    const aviso = tabB.events.find((event) => event.type === PEER_SESSION_EVENT)
    expect((aviso as CustomEvent<string>).detail).toBe('usuario-b')
  })

  it('un logout en otra pestana borra el token y avisa', () => {
    const hub = createFakeHub()
    const tabA = createTab(jest.fn(), { channel: hub.open() })
    const tabB = createTab(jest.fn(), { channel: hub.open(), token: 'vigente' })

    tabA.sync.broadcastLogout()

    expect(tabB.token()).toBeNull()
    expect(tabB.events.map((event) => event.type)).toEqual([PEER_LOGOUT_EVENT])
  })

  it('ignora mensajes que no son de la sesion', () => {
    const channel = createFakeHub().open()
    const tab = createTab(jest.fn(), { channel, token: 'vigente' })

    for (const data of [null, 'x', { type: 'token' }, { type: 'session' }, { type: 'otro' }]) {
      channel.onmessage?.({ data } as MessageEvent)
    }

    expect(tab.token()).toBe('vigente')
    expect(tab.events).toEqual([])
  })
})

describe('sin navigator.locks ni BroadcastChannel', () => {
  it('cae al single-flight por pestana y no difunde nada', async () => {
    const respuesta = deferred<string | null>()
    const requestRefresh = jest.fn(() => respuesta.promise)
    const tab = createTab(requestRefresh, { locks: undefined, channel: undefined })

    const primero = tab.sync.refreshAccessToken(null)
    const segundo = tab.sync.refreshAccessToken(null)
    respuesta.resolve('nuevo')

    await expect(Promise.all([primero, segundo])).resolves.toEqual([
      { kind: 'ok', token: 'nuevo' },
      { kind: 'ok', token: 'nuevo' }
    ])
    expect(requestRefresh).toHaveBeenCalledTimes(1)
    expect(() => tab.sync.broadcastLogout()).not.toThrow()
  })

  it('detectLocks y openChannel devuelven undefined si el navegador no los tiene', () => {
    const original = Reflect.get(globalThis, 'BroadcastChannel') as unknown
    Reflect.set(globalThis, 'BroadcastChannel', undefined)
    try {
      expect(detectLocks()).toBeUndefined()
      expect(openChannel()).toBeUndefined()
    } finally {
      Reflect.set(globalThis, 'BroadcastChannel', original)
    }
  })

  it('con las APIs presentes usa las del navegador', () => {
    const locks = { request: jest.fn() }
    Object.defineProperty(window.navigator, 'locks', { value: locks, configurable: true })
    class FakeChannel {
      onmessage = null
      name: string
      constructor(name: string) {
        this.name = name
      }
      postMessage() {}
    }
    const original = Reflect.get(globalThis, 'BroadcastChannel') as unknown
    Reflect.set(globalThis, 'BroadcastChannel', FakeChannel)
    try {
      expect(detectLocks()).toBe(locks)
      expect(openChannel()).toMatchObject({ name: 'shifty-auth' })
    } finally {
      Reflect.set(globalThis, 'BroadcastChannel', original)
      Reflect.deleteProperty(window.navigator, 'locks')
    }
  })
})
