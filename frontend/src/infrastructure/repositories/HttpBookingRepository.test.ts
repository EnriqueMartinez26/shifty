import type { AxiosInstance } from 'axios'

import { HttpBookingRepository } from './HttpBookingRepository'

describe('HttpBookingRepository.findAll', () => {
  afterEach(() => {
    jest.useRealTimers()
  })

  it('pide el rango en dias argentinos, no en el dia UTC (F10-10)', async () => {
    // 22:30 del 15 en Argentina ya es el 16 en UTC.
    jest.useFakeTimers().setSystemTime(new Date('2026-09-16T01:30:00Z'))
    const get = jest.fn().mockResolvedValue({ data: { results: [] } })
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    await repository.findAll()

    expect(get).toHaveBeenCalledWith(
      '/appointments/search',
      expect.objectContaining({
        params: expect.objectContaining({ from_date: '2026-08-16', to_date: '2026-09-15' })
      })
    )
  })
})
