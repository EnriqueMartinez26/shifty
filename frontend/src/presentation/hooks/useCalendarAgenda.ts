import { useQuery } from '@tanstack/react-query'

import { Appointment } from '@domain/entities/Appointment'

import { AppointmentService } from '@application/services/AppointmentService'

import { resolveService } from './resolveService'

export const useCalendarAgenda = (fromDate: string, toDate: string) => {
  const appointmentService = resolveService<AppointmentService>('appointmentService')

  return useQuery<Appointment[]>({
    queryKey: ['calendar-agenda', fromDate, toDate],
    enabled: Boolean(fromDate && toDate),
    queryFn: () => appointmentService.getCalendarRange(fromDate, toDate)
  })
}
