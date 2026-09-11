import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Appointment } from '@domain/entities/Appointment'
import type { CreateBookingInput } from '@domain/repositories/IBookingRepository'

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

export const useCreateAppointment = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateBookingInput) => appointmentService.bookAppointment(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
    }
  })
}

const useAgendaTransition = (run: (id: string) => Promise<void>) => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (appointmentId: string) => run(appointmentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
    }
  })
}

// Confirmar, completar y marcar ausente existian en la API y en la capa de
// aplicacion pero ningun componente los usaba: el dueno no podia cerrar un
// turno desde la agenda (2026-09-10).
export const useConfirmAppointment = () =>
  useAgendaTransition((id) => appointmentService.confirm(id))

export const useCompleteAppointment = () =>
  useAgendaTransition((id) => appointmentService.complete(id))

export const useMarkAbsentAppointment = () =>
  useAgendaTransition((id) => appointmentService.markAbsent(id))
