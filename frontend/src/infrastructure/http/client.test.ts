import { CanonicalApiError, unwrapApiEnvelope } from './api-contract'

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
})
