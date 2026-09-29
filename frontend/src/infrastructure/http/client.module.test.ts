const mockRequestUse = jest.fn()
const mockResponseUse = jest.fn()
const mockApiRequest = jest.fn()
// El refresh sale por apiClient.post('/auth/refresh') (sessionSync.ts). En
// estos tests no hay sesion: por defecto responde 401, sesion terminada.
const respuestaRefresh401 = {
  response: {
    status: 401,
    data: { success: false, error_code: 'AUTH_REQUIRED', message: 'Sin sesion' }
  },
  message: 'HTTP 401'
}
const mockApiPost = jest.fn((): Promise<unknown> => Promise.reject(respuestaRefresh401))
const mockAxiosCreate = jest.fn(() => ({
  request: mockApiRequest,
  post: mockApiPost,
  interceptors: {
    request: {
      use: mockRequestUse
    },
    response: {
      use: mockResponseUse
    }
  }
}))
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: mockAxiosCreate
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
    mockApiPost.mockClear()
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

    // El request salio con el token vigente: el 401 obliga a refrescar.
    await expect(
      errorHandler({
        config: { headers: { Authorization: 'Bearer token-123' } },
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
    mockApiPost.mockReset()
    mockApiPost.mockImplementation(() => Promise.reject(respuestaRefresh401))
    mockApiRequest.mockReset()
  })

  it('refresca una vez y reintenta el request original con el token nuevo', async () => {
    const nuevoAcceso = 'acceso-rehidratado'
    mockApiPost.mockResolvedValue({ data: { access_token: nuevoAcceso } })
    mockApiRequest.mockResolvedValue({ data: { ok: true } })
    const { clientModule, errorHandler } = await cargarCliente()

    const resultado = await errorHandler({
      config: { url: '/appointments' },
      response: respuesta401,
      message: 'HTTP 401'
    })

    expect(resultado).toEqual({ data: { ok: true } })
    expect(mockApiPost).toHaveBeenCalledWith('/auth/refresh')
    expect(mockApiRequest).toHaveBeenCalledWith({
      url: '/appointments',
      __shiftyRetried: true,
      headers: { Authorization: `Bearer ${nuevoAcceso}` }
    })
    expect(clientModule.getAuthToken()).toBe(nuevoAcceso)
  })

  it('acepta el token dentro del envelope data de la respuesta de refresh', async () => {
    const nuevoAcceso = 'acceso-en-envelope'
    mockApiPost.mockResolvedValue({ data: { data: { access_token: nuevoAcceso } } })
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
    mockApiPost.mockReturnValue(
      new Promise((resolve) => {
        resolverRefresh = resolve
      })
    )
    mockApiRequest.mockResolvedValue({ data: {} })
    const { errorHandler } = await cargarCliente()

    const primero = errorHandler({ config: { url: '/a' }, response: respuesta401 })
    const segundo = errorHandler({ config: { url: '/b' }, response: respuesta401 })
    resolverRefresh({ data: { access_token: 'compartido' } })
    await Promise.all([primero, segundo])

    expect(mockApiPost).toHaveBeenCalledTimes(1)
    expect(mockApiRequest).toHaveBeenCalledTimes(2)
  })

  it('un refresh sin token no reintenta y avisa sesion expirada', async () => {
    mockApiPost.mockResolvedValue({ data: {} })
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-viejo')
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      await expect(
        errorHandler({
          config: { url: '/appointments', headers: { Authorization: 'Bearer acceso-viejo' } },
          response: respuesta401
        })
      ).rejects.toBeTruthy()

      expect(mockApiRequest).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(1)
      expect(clientModule.getAuthToken()).toBeNull()
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  // 2026-09-28 (F4-02): cualquier falla del refresh limpiaba el token y
  // cerraba la sesion, tambien un 503 o un corte de red. Ahora solo un
  // 401/403 del refresh la termina; lo transitorio la conserva.
  it('un refresh con 401 limpia el token y un 401 crudo tambien avisa', async () => {
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-viejo')
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      await expect(
        errorHandler({
          config: { url: '/appointments', headers: { Authorization: 'Bearer acceso-viejo' } },
          response: { status: 401, data: 'Unauthorized' },
          message: 'HTTP 401'
        })
      ).rejects.toBeTruthy()

      expect(mockApiPost).toHaveBeenCalledTimes(1)
      expect(mockApiRequest).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(1)
      expect(clientModule.getAuthToken()).toBeNull()
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  it('un refresh con 503 conserva el token, no avisa sesion expirada y devuelve el 503', async () => {
    const { ServiceUnavailableError } = await import('@shared/errors')
    mockApiPost.mockImplementation(() =>
      Promise.reject({
        response: {
          status: 503,
          headers: { 'retry-after': '0' },
          data: { success: false, error_code: 'RATE_LIMIT_UNAVAILABLE', message: 'x' }
        },
        message: 'HTTP 503'
      })
    )
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-viejo')
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      const error = await errorHandler({
        config: { url: '/appointments', headers: { Authorization: 'Bearer acceso-viejo' } },
        response: respuesta401,
        message: 'HTTP 401'
      }).catch((e: unknown) => e)

      expect(error).toBeInstanceOf(ServiceUnavailableError)
      expect(mockApiPost).toHaveBeenCalledTimes(4)
      expect(mockApiRequest).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(0)
      expect(clientModule.getAuthToken()).toBe('acceso-viejo')
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
  })

  it('si el token ya se renovo (otra pestana) reintenta con ese, sin otro refresh', async () => {
    mockApiRequest.mockResolvedValue({ data: {} })
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-nuevo')

    await errorHandler({
      config: { url: '/services', headers: { Authorization: 'Bearer acceso-viejo' } },
      response: respuesta401
    })

    expect(mockApiPost).not.toHaveBeenCalled()
    expect(mockApiRequest).toHaveBeenCalledWith(
      expect.objectContaining({ headers: { Authorization: 'Bearer acceso-nuevo' } })
    )
  })

  // 4R 2026-09-28: el 401 del refresh avisaba sesion expirada dos veces (el
  // request anidado de /auth/refresh y el 401 original). Ahora el anidado calla
  // y el aviso sale una sola vez, del request original.
  it('el 401 del propio refresh no dispara otro refresh ni avisa por su cuenta', async () => {
    const { clientModule, errorHandler } = await cargarCliente()
    clientModule.setAuthToken('acceso-vigente')
    const avisos: Event[] = []
    const escucha = (evento: Event) => avisos.push(evento)
    window.addEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)

    try {
      await expect(
        errorHandler({ config: { url: 'http://test-api/auth/refresh' }, response: respuesta401 })
      ).rejects.toBeTruthy()

      expect(mockApiPost).not.toHaveBeenCalled()
      expect(avisos).toHaveLength(0)
      expect(clientModule.getAuthToken()).toBe('acceso-vigente')
    } finally {
      window.removeEventListener(clientModule.SESSION_EXPIRED_EVENT, escucha)
    }
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

      expect(mockApiPost).not.toHaveBeenCalled()
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

describe('cuerpo de error en Blob (exportar reportes)', () => {
  beforeEach(() => {
    jest.resetModules()
    mockResponseUse.mockClear()
  })

  const cargarErrorHandler = async () => {
    await import('./client')
    return mockResponseUse.mock.calls[0][1] as ErrorHandler
  }

  it('el codigo y el mensaje del JSON dentro del Blob llegan a quien llamo', async () => {
    const { ValidationError } = await import('@shared/errors')
    const errorHandler = await cargarErrorHandler()
    const cuerpo = JSON.stringify({
      success: false,
      error_code: 'EXPORT_TOO_LARGE',
      message: 'El reporte tiene mas de 5000 turnos'
    })

    const error = await errorHandler({
      config: { url: '/reports/export', responseType: 'blob' },
      response: { status: 422, data: new Blob([cuerpo], { type: 'application/json' }) },
      message: 'HTTP 422'
    }).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ValidationError)
    expect(error).toMatchObject({
      message: 'El reporte tiene mas de 5000 turnos',
      context: { errorCode: 'EXPORT_TOO_LARGE', statusCode: 422 }
    })
  })

  it('un Blob que no es JSON (HTML de un 502) se normaliza sin romper', async () => {
    const { ServiceUnavailableError } = await import('@shared/errors')
    const errorHandler = await cargarErrorHandler()

    const error = await errorHandler({
      config: { url: '/reports/export', responseType: 'blob' },
      response: {
        status: 502,
        data: new Blob(['<html>Bad Gateway</html>'], { type: 'text/html' })
      },
      message: 'Request failed with status code 502'
    }).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ServiceUnavailableError)
    expect(error).toMatchObject({ context: { statusCode: 502 } })
    expect((error as { context: { errorCode?: string } }).context.errorCode).toBeUndefined()
  })
})
