import { CanonicalApiError, unwrapApiEnvelope } from './api-contract'
import { resolveApiBaseUrl } from './api-base-url'

describe('apiClient canonical envelope', () => {
  it('unwraps successful canonical responses for services', async () => {
    const data = unwrapApiEnvelope(
      { success: true, data: { public_id: 'appt_1' }, meta: { page: 1 } },
      200
    )

    expect(data).toEqual({ public_id: 'appt_1' })
  })

  it('keeps legacy payloads readable during local migration', async () => {
    const data = unwrapApiEnvelope({ public_id: 'legacy_1' }, 200)

    expect(data).toEqual({ public_id: 'legacy_1' })
  })

  it('throws a typed error for canonical error responses', async () => {
    expect(() =>
      unwrapApiEnvelope(
        {
          success: false,
          error_code: 'APPOINTMENT_CONFLICT',
          message: 'Horario ocupado',
          detail: { public_id: 'appt_1' }
        },
        409
      )
    ).toThrow(CanonicalApiError)
  })

  it('preserves canonical error details', () => {
    expect.assertions(1)
    try {
      unwrapApiEnvelope(
        {
          success: false,
          error_code: 'APPOINTMENT_CONFLICT',
          message: 'Horario ocupado',
          detail: { public_id: 'appt_1' }
        },
        409
      )
    } catch (error) {
      expect(error).toMatchObject({
        name: 'CanonicalApiError',
        errorCode: 'APPOINTMENT_CONFLICT',
        statusCode: 409,
        detail: { public_id: 'appt_1' }
      })
    }
  })

  it('normalizes configured API URLs without trailing slashes', () => {
    expect(resolveApiBaseUrl('https://api.example.com///', false)).toBe(
      'https://api.example.com'
    )
  })

  it('falls back to localhost in development when the env var is absent', () => {
    expect(resolveApiBaseUrl(undefined, true)).toBe('http://localhost:8000')
  })

  it('refuses to guess an API URL in production', () => {
    expect(() => resolveApiBaseUrl(undefined, false)).toThrow(
      'VITE_API_URL is required in production'
    )
  })
})
