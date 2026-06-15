import { useQuery } from '@tanstack/react-query'

import { Service } from '@domain/entities/Service'

import { ServiceService } from '@application/services/ServiceService'

import { resolveService } from './resolveService'

export const useServicesCatalog = () => {
  const serviceService = resolveService<ServiceService>('serviceService')

  return useQuery<Service[]>({
    queryKey: ['services'],
    queryFn: () => serviceService.listServices()
  })
}
