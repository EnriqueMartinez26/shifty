import type { StaffSchedule } from '@domain/entities/Staff'

import apiClient from '@infrastructure/http/client'

interface StaffScheduleDTO {
  public_id: string
  day_of_week: number
  start_time: string
  end_time: string
}

/**
 * Semana de trabajo de un profesional (`PUT /staff/{public_id}/schedules`).
 *
 * Reemplaza TODAS las franjas en una transaccion del backend: lista vacia =
 * vuelve al horario de la tienda (D-20260929-01). Path literal para que el
 * test de contrato de rutas lo vea (regla 23).
 */
class StaffSchedulesService {
  async replaceWeek(
    staffId: string,
    schedules: readonly StaffSchedule[]
  ): Promise<StaffSchedule[]> {
    const { data } = await apiClient.put<StaffScheduleDTO[]>(`/staff/${staffId}/schedules`, {
      schedules: schedules.map((row) => ({
        day_of_week: row.dayOfWeek,
        start_time: row.startTime,
        end_time: row.endTime
      }))
    })
    return data.map((row) => ({
      dayOfWeek: row.day_of_week,
      startTime: row.start_time,
      endTime: row.end_time
    }))
  }
}

export const staffSchedulesService = new StaffSchedulesService()
