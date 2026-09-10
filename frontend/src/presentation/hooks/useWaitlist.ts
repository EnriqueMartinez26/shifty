import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  waitlistService,
  type WaitlistBookPayload,
  type WaitlistBookedAppointment,
  type WaitlistEntry
} from '@application/services/WaitlistService'

export const useWaitlist = () =>
  useQuery<WaitlistEntry[]>({
    queryKey: ['waitlist'],
    queryFn: () => waitlistService.list()
  })

export const useRemoveWaitlistEntry = () => {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: (entryId) => waitlistService.remove(entryId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['waitlist'] })
    }
  })
}

export const useBookFromWaitlist = () => {
  const queryClient = useQueryClient()
  return useMutation<
    WaitlistBookedAppointment,
    Error,
    { entryId: string; payload: WaitlistBookPayload }
  >({
    mutationFn: ({ entryId, payload }) => waitlistService.book(entryId, payload),
    onSuccess: () => {
      // La reserva a mano ocupa un cupo: la agenda tambien cambia.
      void queryClient.invalidateQueries({ queryKey: ['waitlist'] })
      void queryClient.invalidateQueries({ queryKey: ['calendar-agenda'] })
    }
  })
}
