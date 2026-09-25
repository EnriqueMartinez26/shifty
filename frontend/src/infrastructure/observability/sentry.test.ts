const mockInit = jest.fn()

jest.mock('@sentry/react', () => ({
  __esModule: true,
  init: (...args: unknown[]) => mockInit(...args)
}))

const mockGetRuntimeEnv = jest.fn()
jest.mock('../http/runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => mockGetRuntimeEnv()
}))

describe('initSentry', () => {
  beforeEach(() => {
    mockInit.mockClear()
    mockGetRuntimeEnv.mockReset()
  })

  it('no inicializa Sentry si no hay DSN configurado', async () => {
    mockGetRuntimeEnv.mockReturnValue({ dev: false, mode: 'production' })
    const { initSentry } = await import('./sentry')

    expect(initSentry()).toBe(false)
    expect(mockInit).not.toHaveBeenCalled()
  })

  it('inicializa con el DSN y el ambiente del runtime env', async () => {
    mockGetRuntimeEnv.mockReturnValue({
      dev: false,
      mode: 'production',
      sentryDsn: 'https://dsn.example/1',
      sentryEnvironment: 'staging',
      sentryTracesSampleRate: '0.5'
    })
    const { initSentry } = await import('./sentry')

    expect(initSentry()).toBe(true)
    expect(mockInit).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'https://dsn.example/1',
        environment: 'staging',
        tracesSampleRate: 0.5,
        sendDefaultPii: false
      })
    )
  })

  it('cae al MODE cuando no hay VITE_SENTRY_ENVIRONMENT', async () => {
    mockGetRuntimeEnv.mockReturnValue({
      dev: false,
      mode: 'production',
      sentryDsn: 'https://dsn.example/1'
    })
    const { initSentry } = await import('./sentry')

    initSentry()
    expect(mockInit).toHaveBeenCalledWith(expect.objectContaining({ environment: 'production' }))
  })

  it('beforeSend recorta datos sensibles del evento', async () => {
    mockGetRuntimeEnv.mockReturnValue({
      dev: false,
      mode: 'production',
      sentryDsn: 'https://dsn.example/1'
    })
    const { initSentry } = await import('./sentry')

    initSentry()
    const { beforeSend } = mockInit.mock.calls[0][0]
    const event = {
      request: {
        data: { password: 'secreto' },
        cookies: 'a=b',
        headers: { Authorization: 'Bearer x', Cookie: 'a=b' }
      },
      extra: { sensible: true }
    }

    const cleaned = beforeSend(event)

    expect(cleaned.request.data).toBeUndefined()
    expect(cleaned.request.cookies).toBeUndefined()
    expect(cleaned.request.headers.Authorization).toBeUndefined()
    expect(cleaned.request.headers.Cookie).toBeUndefined()
    expect(cleaned.extra).toBeUndefined()
  })
})

describe('initSentry: sin secretos de la URL ni datos de usuario (F3)', () => {
  const init = async (env: Record<string, unknown> = {}) => {
    mockGetRuntimeEnv.mockReturnValue({
      dev: false,
      mode: 'production',
      sentryDsn: 'https://dsn.example/1',
      ...env
    })
    const { initSentry } = await import('./sentry')
    initSentry()
    return mockInit.mock.calls[0][0]
  }

  beforeEach(() => {
    mockInit.mockClear()
    mockGetRuntimeEnv.mockReset()
  })

  it('usa el tunel del mismo origen solo si esta configurado', async () => {
    expect(await init({ sentryTunnel: '/sentry-tunnel' })).toMatchObject({
      tunnel: '/sentry-tunnel',
      maxBreadcrumbs: 30
    })
    mockInit.mockClear()
    expect((await init()).tunnel).toBeUndefined()
  })

  it('el token de /reset-password no llega en request.url ni query_string, y sin user', async () => {
    const { beforeSend } = await init()
    const cleaned = beforeSend({
      request: {
        url: 'https://app.example/reset-password?token=secreto#x',
        query_string: 'token=secreto'
      },
      user: { email: 'ana@example.com', ip_address: '1.2.3.4' }
    })

    expect(cleaned.request.url).toBe('https://app.example/reset-password')
    expect(cleaned.request.query_string).toBeUndefined()
    expect(cleaned.user).toBeUndefined()
  })

  it('los breadcrumbs de navegacion y fetch pierden la query', async () => {
    const { beforeBreadcrumb } = await init()

    expect(
      beforeBreadcrumb({
        category: 'navigation',
        data: { from: '/login', to: '/reset-password?token=secreto' }
      }).data
    ).toEqual({ from: '/login', to: '/reset-password' })
    expect(
      beforeBreadcrumb({
        category: 'fetch',
        data: { url: '/api/auth/reset?token=secreto', method: 'POST' }
      }).data
    ).toEqual({ url: '/api/auth/reset', method: 'POST' })
    expect(beforeBreadcrumb({ category: 'console', message: 'x' })).toBeNull()
  })
})

describe('stripQuery', () => {
  it.each([
    ['/reset-password?token=x', '/reset-password'],
    ['/a#frag', '/a'],
    ['/sin-query', '/sin-query'],
    ['', '']
  ])('%s -> %s', async (url, expected) => {
    const { stripQuery } = await import('./sentry')
    expect(stripQuery(url)).toBe(expected)
  })
})

describe('parseSampleRate', () => {
  it('clampea el valor entre 0 y 1', async () => {
    const { parseSampleRate } = await import('./sentry')

    expect(parseSampleRate('2')).toBe(1)
    expect(parseSampleRate('-1')).toBe(0)
    expect(parseSampleRate('0.3')).toBe(0.3)
  })

  it('devuelve undefined para valores vacios o invalidos', async () => {
    const { parseSampleRate } = await import('./sentry')

    expect(parseSampleRate(undefined)).toBeUndefined()
    expect(parseSampleRate('no-numero')).toBeUndefined()
  })
})
