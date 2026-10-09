// 2026-10-08: la semana de un profesional se guarda de una vez con
// PUT /staff/{id}/schedules. Path literal (regla 23) y cuerpo en snake_case.
const mockPut = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: { put: (...args: unknown[]) => mockPut(...args) }
}))

import { staffSchedulesService } from './StaffSchedulesService'

describe('StaffSchedulesService.replaceWeek', () => {
  beforeEach(() => {
    mockPut.mockReset()
  })

  it('manda la semana entera y devuelve las franjas guardadas en camelCase', async () => {
    mockPut.mockResolvedValue({
      data: [{ public_id: 'sch-1', day_of_week: 1, start_time: '09:00:00', end_time: '13:00:00' }]
    })

    const guardadas = await staffSchedulesService.replaceWeek('st-1', [
      { dayOfWeek: 1, startTime: '09:00:00', endTime: '13:00:00' }
    ])

    expect(mockPut).toHaveBeenCalledWith('/staff/st-1/schedules', {
      schedules: [{ day_of_week: 1, start_time: '09:00:00', end_time: '13:00:00' }]
    })
    expect(guardadas).toEqual([{ dayOfWeek: 1, startTime: '09:00:00', endTime: '13:00:00' }])
  })

  it('la semana vacia viaja explicita: vuelve al horario de la tienda', async () => {
    mockPut.mockResolvedValue({ data: [] })

    await expect(staffSchedulesService.replaceWeek('st-1', [])).resolves.toEqual([])

    expect(mockPut).toHaveBeenCalledWith('/staff/st-1/schedules', { schedules: [] })
  })

  it('propaga el error del cliente HTTP sin envolverlo', async () => {
    const error = new Error('422')
    mockPut.mockRejectedValue(error)

    await expect(staffSchedulesService.replaceWeek('st-1', [])).rejects.toBe(error)
  })
})
