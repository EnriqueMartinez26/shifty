import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Appointment } from '@domain/entities/Appointment'

import { appointmentService } from '@application/services/AppointmentService'

export const useCalendarAgenda = (fromDate: string, toDate: string) => {
  return useQuery<Appointment[]>({
    queryKey: ['calendar-agenda', fromDate, toDate],
    enabled: Boolean(fromDate && toDate),
    queryFn: () => appointmentService.getCalendarRange(fromDate, toDate)
  })
}

export const useReleaseAppointment = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (appointmentId: string) => appointmentService.release(appointmentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
    }
  })
}

const useAgendaTransition = (run: (service: AppointmentService, id: string) => Promise<void>) => {
  const queryClient = useQueryClient()
  const appointmentService = resolveService<AppointmentService>('appointmentService')

  return useMutation({
    mutationFn: (appointmentId: string) => run(appointmentService, appointmentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
    }
  })
}

// Confirmar, completar y marcar ausente existian en la API y en la capa de
// aplicacion pero ningun componente los usaba: el dueno no podia cerrar un
// turno desde la agenda (2026-09-10).
export const useConfirmAppointment = () => useAgendaTransition((service, id) => service.confirm(id))

export const useCompleteAppointment = () =>
  useAgendaTransition((service, id) => service.complete(id))

export const useMarkAbsentAppointment = () =>
  useAgendaTransition((service, id) => service.markAbsent(id))
