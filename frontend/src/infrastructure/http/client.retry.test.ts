import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

// runtime-env lee import.meta, que ts-jest no compila.
jest.mock('./runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({ apiUrl: 'http://test-api', dev: true })
}))

describe('apiClient sin reintentos automaticos', () => {
  it('un PATCH con 409 se manda una sola vez y rechaza (C3)', async () => {
    // Todo 409 del backend es determinista; con axios-retry este PATCH se
    // reenviaba 3 veces mas (~14-17 s) y una reprogramacion podia aplicarse
    // en silencio porque el backend libera la clave de idempotencia.
    const { default: apiClient } = await import('./client')
    const adapter = jest.fn((config: InternalAxiosRequestConfig) => {
      const response: AxiosResponse = {
        data: { success: false, error_code: 'APPOINTMENT_CONFLICT', message: 'Horario ocupado' },
        status: 409,
        statusText: 'Conflict',
        headers: {},
        config
      }
      return Promise.reject(
        new AxiosError('Conflict', AxiosError.ERR_BAD_REQUEST, config, null, response)
      )
    })

    await expect(
      apiClient.patch('/appointments/appt-1/reschedule', {}, { adapter })
    ).rejects.toBeTruthy()

    expect(adapter).toHaveBeenCalledTimes(1)
  })
})
