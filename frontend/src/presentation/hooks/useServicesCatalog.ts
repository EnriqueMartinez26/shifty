import { useQuery } from '@tanstack/react-query'

import { Service } from '@domain/entities/Service'

import { serviceService } from '@application/services/ServiceService'

export const useServicesCatalog = () => {
  return useQuery<Service[]>({
    queryKey: ['services'],
    queryFn: () => serviceService.listServices()
  })
}
