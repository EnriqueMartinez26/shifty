import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type {
  AppointmentRange,
  CreateBookingInput,
  RescheduleInput
} from '@domain/repositories/IBookingRepository'

import { appointmentService } from '@application/services/AppointmentService'

export const useCalendarAgenda = (fromDate: string, toDate: string) => {
  return useQuery<AppointmentRange>({
    queryKey: ['calendar-agenda', fromDate, toDate],
    enabled: Boolean(fromDate && toDate),
    queryFn: () => appointmentService.getCalendarRange(fromDate, toDate),
    // Al cambiar de dia o de vista, los turnos del rango anterior quedan hasta
    // que llegan los nuevos en vez de parpadear vacios (F4-07).
    placeholderData: keepPreviousData
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
      void queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] })
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

// Cancelar existia en la API y en la capa de aplicacion sin ningun llamador
// (FF-31). Mismo refresco que liberar.
export const useCancelAppointment = () => useAgendaTransition((id) => appointmentService.cancel(id))

/**
 * Reprogramar mueve el turno de dia u hora: se refresca lo mismo que tras un
 * alta (la agenda y el resumen del dashboard).
 */
export const useRescheduleAppointment = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: RescheduleInput }) =>
      appointmentService.reschedule(id, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] })
    }
  })
}
