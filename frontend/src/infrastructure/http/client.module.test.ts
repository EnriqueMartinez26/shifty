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

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: mockAxiosCreate
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

declare const require: any

describe('api client module wiring', () => {
  beforeEach(() => {
    jest.resetModules()
    localStorage.clear()
    mockRequestUse.mockClear()
    mockResponseUse.mockClear()
    mockAxiosCreate.mockClear()
    mockAxiosRetry.mockClear()
  })

  it('registers axios interceptors, attaches the auth token, and normalizes auth failures', async () => {
    const { UnauthorizedError } = require('@shared/errors')

    const clientModule = require('./client')

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
})
