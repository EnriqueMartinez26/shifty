const mockRequestUse = jest.fn()
const mockResponseUse = jest.fn()
const mockAxiosCreate = jest.fn(() => ({
  interceptors: {
    request: {
      use: mockRequestUse
    },
    response: {
      use: mockResponseUse
    }
  }
}))
const mockAxiosRetry = jest.fn()
// El interceptor de 401 intenta una rehidratacion via POST /auth/refresh; en
// estos tests no hay sesion, asi que el refresh "falla" y el flujo debe caer
// al error normalizado original.
const mockAxiosPost = jest.fn(() => Promise.reject(new Error('sin sesion')))

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: mockAxiosCreate,
    post: mockAxiosPost
  }
}))

jest.mock('axios-retry', () => ({
  __esModule: true,
  default: mockAxiosRetry
}))

jest.mock('./runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({
    apiUrl: 'http://test-api',
    dev: true
  })
}))

describe('api client module wiring', () => {
  beforeEach(() => {
    jest.resetModules()
    localStorage.clear()
    mockRequestUse.mockClear()
    mockResponseUse.mockClear()
    mockAxiosCreate.mockClear()
    mockAxiosRetry.mockClear()
    mockAxiosPost.mockClear()
  })

  it('registers axios interceptors, attaches the auth token, and normalizes auth failures', async () => {
    const { UnauthorizedError } = await import('@shared/errors')
    const clientModule = await import('./client')

    expect(mockAxiosCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        withCredentials: true,
        headers: {
          'Content-Type': 'application/json'
        }
      })
    )
    expect(mockAxiosRetry).toHaveBeenCalledTimes(1)
    expect(mockRequestUse).toHaveBeenCalledTimes(1)
    expect(mockResponseUse).toHaveBeenCalledTimes(1)

    clientModule.setAuthToken('token-123')
    expect(clientModule.getAuthToken()).toBe('token-123')

    const requestInterceptor = mockRequestUse.mock.calls[0][0] as (config: {
      headers?: Record<string, string>
    }) => { headers?: Record<string, string> }
    const updatedConfig = requestInterceptor({})

    expect(updatedConfig.headers?.Authorization).toBe('Bearer token-123')

    const [successHandler, errorHandler] = mockResponseUse.mock.calls[0]
    expect(
      successHandler({
        data: {
          success: true,
          data: { ok: true }
        },
        status: 200
      })
    ).toMatchObject({
      data: { ok: true }
    })

    await expect(
      errorHandler({
        response: {
          status: 401,
          data: {
            success: false,
            error_code: 'AUTH_REQUIRED',
            message: 'Sesión expirada'
          }
        },
        message: 'HTTP 401'
      })
    ).rejects.toBeInstanceOf(UnauthorizedError)

    expect(clientModule.getAuthToken()).toBeNull()
  })

  it('un 401 del propio login no avisa sesion expirada, uno de otra ruta si', async () => {
    // F11c-03: el cliente avisaba sesion expirada ante CUALQUIER 401, tambien
    // el de `/auth/login`. AuthContext escucha ese evento y recarga con
    // "Sesion expirada. Redirigiendo...", asi que una clave mal tipeada
    // borraba el error del formulario antes de que se pudiera leer.
    const clientModule = await import('./client')
    const [, errorHandler] = mockResponseUse.mock.calls[0]

    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      const respuesta401 = {
        status: 401,
        data: { success: false, error_code: 'AUTH_REQUIRED', message: 'Credenciales invalidas' }
      }

      await expect(
        errorHandler({
          config: { url: 'http://test-api/auth/login' },
          response: respuesta401,
          message: 'HTTP 401'
        })
      ).rejects.toBeTruthy()
      expect(avisos).toHaveLength(0)

      // Un 401 del login SIN el envelope de la app (un proxy o un middleware
      // que responde antes) cae por la otra rama del interceptor, la de
      // payload crudo. Tiene que quedar igual de silenciosa: sin este caso,
      // sacar el guard de esa rama no rompia ningun test.
      await expect(
        errorHandler({
          config: { url: 'http://test-api/auth/login' },
          response: { status: 401, data: 'Unauthorized' },
          message: 'HTTP 401'
        })
      ).rejects.toBeTruthy()
      expect(avisos).toHaveLength(0)

      // La contraprueba: el mismo 401 en otra ruta SI tiene que avisar, o
      // quedaria un cascaron logueado dando 401 en cada request.
      await expect(
        errorHandler({
          config: { url: 'http://test-api/appointments', __shiftyRetried: true },
          response: respuesta401,
          message: 'HTTP 401'
        })
      ).rejects.toBeTruthy()
      expect(avisos).toHaveLength(1)
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  it('no reintenta nunca un POST; sí el 409 de métodos idempotentes', async () => {
    const clientModule = await import('./client')
    const { shouldRetryRequest } = clientModule

    expect(mockAxiosRetry).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ retryCondition: shouldRetryRequest })
    )

    // Un 409 al crear un turno es un conflicto de negocio real (el slot ya no
    // está libre), no algo transitorio: reintentarlo no lo resuelve y puede
    // terminar reservando después de que la UI ya mostró el conflicto.
    expect(shouldRetryRequest({ response: { status: 409 }, config: { method: 'post' } })).toBe(
      false
    )
    // Un POST abortado pudo haberse aplicado en el servidor: no se reenvia.
    expect(shouldRetryRequest({ code: 'ECONNABORTED', config: { method: 'post' } })).toBe(false)
    // Sin timeout configurado, ECONNABORTED solo llega por un aborto del
    // navegador; no es un error transitorio a reintentar.
    expect(shouldRetryRequest({ code: 'ECONNABORTED', config: { method: 'get' } })).toBe(false)
    expect(shouldRetryRequest({ response: { status: 409 }, config: { method: 'patch' } })).toBe(
      true
    )
    expect(shouldRetryRequest({ code: 'ERR_CONNECTION_REFUSED', config: { method: 'get' } })).toBe(
      false
    )
  })
})
