import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Service } from '@domain/entities/Service'

import { ServiceService } from '@application/services/ServiceService'

import { resolveService } from './resolveService'

type CreateServiceInput = Parameters<ServiceService['createService']>[0]
type UpdateServiceInput = Parameters<ServiceService['updateService']>[1]

export const useManagedServices = () => {
  const serviceService = resolveService<ServiceService>('serviceService')

  return useQuery<Service[]>({
    queryKey: ['services'],
    queryFn: () => serviceService.listServices()
  })
}

export const useCreateManagedService = () => {
  const queryClient = useQueryClient()
  const serviceService = resolveService<ServiceService>('serviceService')

  return useMutation({
    mutationFn: (data: CreateServiceInput) => serviceService.createService(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}

export const useUpdateManagedService = () => {
  const queryClient = useQueryClient()
  const serviceService = resolveService<ServiceService>('serviceService')

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateServiceInput }) =>
      serviceService.updateService(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}

export const useDeleteManagedService = () => {
  const queryClient = useQueryClient()
  const serviceService = resolveService<ServiceService>('serviceService')

  return useMutation({
    mutationFn: (id: string) => serviceService.deleteService(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}
