const mockRequestUse = jest.fn()
const mockResponseUse = jest.fn()
const mockApiRequest = jest.fn()
const mockAxiosCreate = jest.fn(() => ({
  request: mockApiRequest,
  interceptors: {
    request: {
      use: mockRequestUse
    },
    response: {
      use: mockResponseUse
    }
  }
}))
// El interceptor de 401 intenta una rehidratacion via POST /auth/refresh; en
// estos tests no hay sesion, asi que el refresh "falla" y el flujo debe caer
// al error normalizado original.
const mockAxiosPost = jest.fn((): Promise<unknown> => Promise.reject(new Error('sin sesion')))

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: mockAxiosCreate,
    post: mockAxiosPost
  }
}))

jest.mock('./runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({
    apiUrl: 'http://test-api',
    dev: true
  })
}))

describe('token viejo en localStorage (F10-14)', () => {
  beforeEach(() => {
    jest.resetModules()
    localStorage.clear()
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it('se limpia una vez al cargar el modulo', async () => {
    localStorage.setItem('shifty_token', 'persistido')

    await import('./client')

    expect(localStorage.getItem('shifty_token')).toBeNull()
  })

  it('setAuthToken no toca el almacenamiento: el token vive solo en memoria', async () => {
    const clientModule = await import('./client')
    const removeItem = jest.spyOn(Storage.prototype, 'removeItem')
    const setItem = jest.spyOn(Storage.prototype, 'setItem')
    const accessValue = 'valor-de-acceso'

    clientModule.setAuthToken(accessValue)
    clientModule.setAuthToken(null)

    expect(removeItem).not.toHaveBeenCalled()
    expect(setItem).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
  })
})

describe('api client module wiring', () => {
  beforeEach(() => {
    jest.resetModules()
    localStorage.clear()
    mockRequestUse.mockClear()
    mockResponseUse.mockClear()
    mockAxiosCreate.mockClear()
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
})

type ErrorHandler = (error: unknown) => Promise<unknown>

describe('rehidratacion ante un 401', () => {
  const respuesta401 = {
    status: 401,
    data: { success: false, error_code: 'AUTH_REQUIRED', message: 'Sesion vencida' }
  }

  const cargarCliente = async () => {
    const clientModule = await import('./client')
    const errorHandler = mockResponseUse.mock.calls[0][1] as ErrorHandler
    return { clientModule, errorHandler }
  }

  beforeEach(() => {
    jest.resetModules()
    mockResponseUse.mockClear()
    mockAxiosPost.mockReset()
    mockApiRequest.mockReset()
  })

  it('refresca una vez y reintenta el request original con el token nuevo', async () => {
    const nuevoAcceso = 'acceso-rehidratado'
    mockAxiosPost.mockResolvedValue({ data: { access_token: nuevoAcceso } })
    mockApiRequest.mockResolvedValue({ data: { ok: true } })
    const { clientModule, errorHandler } = await cargarCliente()

    const resultado = await errorHandler({
      config: { url: '/appointments' },
      response: respuesta401,
      message: 'HTTP 401'
    })

    expect(resultado).toEqual({ data: { ok: true } })
    expect(mockAxiosPost).toHaveBeenCalledWith('http://test-api/auth/refresh', undefined, {
      withCredentials: true
    })
    expect(mockApiRequest).toHaveBeenCalledWith({
      url: '/appointments',
      __shiftyRetried: true,
      headers: { Authorization: `Bearer ${nuevoAcceso}` }
    })
    expect(clientModule.getAuthToken()).toBe(nuevoAcceso)
  })

  it('acepta el token dentro del envelope data de la respuesta de refresh', async () => {
    const nuevoAcceso = 'acceso-en-envelope'
    mockAxiosPost.mockResolvedValue({ data: { data: { access_token: nuevoAcceso } } })
    mockApiRequest.mockResolvedValue({ data: {} })
    const { clientModule, errorHandler } = await cargarCliente()

    await errorHandler({
      config: { url: '/services', headers: { 'X-Otro': '1' } },
      response: respuesta401,
      message: 'HTTP 401'
    })

    expect(mockApiRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        headers: { 'X-Otro': '1', Authorization: `Bearer ${nuevoAcceso}` }
      })
    )
    expect(clientModule.getAuthToken()).toBe(nuevoAcceso)
  })

  it('varios 401 a la vez comparten un solo refresh (single-flight)', async () => {
    let resolverRefresh: (value: unknown) => void = () => undefined
    mockAxiosPost.mockReturnValue(
      new Promise((resolve) => {
        resolverRefresh = resolve
      })
    )
    mockApiRequest.mockResolvedValue({ data: {} })
    const { errorHandler } = await cargarCliente()

    const primero = errorHandler({ config: { url: '/a' }, response: respuesta401 })
    const segundo = errorHandler({ config: { url: '/b' }, response: respuesta401 })
    resolverRefresh({ data: { access_token: 'acceso-compartido' } })
    await Promise.all([primero, segundo])

    expect(mockAxiosPost).toHaveBeenCalledTimes(1)
    expect(mockApiRequest).toHaveBeenCalledTimes(2)
  })

  it('un refresh sin token no reintenta y avisa sesion expirada', async () => {
    mockAxiosPost.mockResolvedValue({ data: {} })
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-viejo')
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      await expect(
        errorHandler({ config: { url: '/appointments' }, response: respuesta401 })
      ).rejects.toBeTruthy()

      expect(mockApiRequest).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(1)
      expect(clientModule.getAuthToken()).toBeNull()
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  it('un refresh que falla limpia el token y un 401 crudo tambien avisa', async () => {
    mockAxiosPost.mockRejectedValue(new Error('cookie vencida'))
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-viejo')
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      await expect(
        errorHandler({
          config: { url: '/appointments' },
          response: { status: 401, data: 'Unauthorized' },
          message: 'HTTP 401'
        })
      ).rejects.toBeTruthy()

      expect(mockApiRequest).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(1)
      expect(clientModule.getAuthToken()).toBeNull()
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  it('el 401 del propio refresh no dispara otro refresh', async () => {
    const { errorHandler } = await cargarCliente()

    await expect(
      errorHandler({ config: { url: 'http://test-api/auth/refresh' }, response: respuesta401 })
    ).rejects.toBeTruthy()

    expect(mockAxiosPost).not.toHaveBeenCalled()
  })

  it('un error que no es 401 se rechaza sin refrescar ni avisar', async () => {
    const { clientModule, errorHandler } = await cargarCliente()
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      await expect(
        errorHandler({
          config: { url: '/appointments' },
          response: {
            status: 409,
            data: { success: false, error_code: 'APPOINTMENT_CONFLICT', message: 'Ocupado' }
          }
        })
      ).rejects.toBeTruthy()

      expect(mockAxiosPost).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(0)
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  it('sin token en memoria el request sale sin Authorization', async () => {
    await import('./client')
    const requestInterceptor = mockRequestUse.mock.calls[
      mockRequestUse.mock.calls.length - 1
    ][0] as (config: { headers?: Record<string, string> }) => { headers?: Record<string, string> }

    expect(requestInterceptor({}).headers).toBeUndefined()
  })
})
