import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Staff } from '@domain/entities/Staff'

import { StaffService } from '@application/services/StaffService'

import { resolveService } from './resolveService'

type CreateStaffInput = Parameters<StaffService['createStaff']>[0]
type UpdateStaffInput = Parameters<StaffService['updateStaff']>[1]

export const useManagedStaff = () => {
  const staffService = resolveService<StaffService>('staffService')

  return useQuery<Staff[]>({
    queryKey: ['staff'],
    queryFn: () => staffService.listStaff()
  })
}

export const useCreateManagedStaff = () => {
  const queryClient = useQueryClient()
  const staffService = resolveService<StaffService>('staffService')

  return useMutation({
    mutationFn: (data: CreateStaffInput) => staffService.createStaff(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['staff'] })
    }
  })
}

export const useUpdateManagedStaff = () => {
  const queryClient = useQueryClient()
  const staffService = resolveService<StaffService>('staffService')

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateStaffInput }) =>
      staffService.updateStaff(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['staff'] })
    }
  })
}

export const useDeleteManagedStaff = () => {
  const queryClient = useQueryClient()
  const staffService = resolveService<StaffService>('staffService')

  return useMutation({
    mutationFn: (id: string) => staffService.deleteStaff(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['staff'] })
    }
  })
}
