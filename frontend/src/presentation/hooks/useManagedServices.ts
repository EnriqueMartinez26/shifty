import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Service } from '@domain/entities/Service'

import { serviceService, ServiceService } from '@application/services/ServiceService'

type CreateServiceInput = Parameters<ServiceService['createService']>[0]
type UpdateServiceInput = Parameters<ServiceService['updateService']>[1]

export const useManagedServices = () => {
  return useQuery<Service[]>({
    queryKey: ['services'],
    queryFn: () => serviceService.listServices()
  })
}

/**
 * Catalogo del panel de servicios, con los inactivos (FF-22). Va en su propia
 * clave: `['services']` lo leen el alta de turno, el de profesionales y los
 * links, que tienen que seguir viendo solo los activos, y los inactivos le dan
 * 403 a un profesional. Las mutaciones invalidan el prefijo `['services']`,
 * asi que tambien refrescan esta clave.
 */
export const useManagedServiceCatalog = () => {
  return useQuery<Service[]>({
    queryKey: ['services', 'catalog'],
    queryFn: () => serviceService.listCatalog()
  })
}

export const useCreateManagedService = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateServiceInput) => serviceService.createService(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}

export const useUpdateManagedService = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateServiceInput }) =>
      serviceService.updateService(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}

/**
 * Subir y quitar la imagen persisten al instante (sin pasar por Guardar), asi
 * que refrescan el prefijo `['services']` como las otras mutaciones.
 */
export const useUploadServiceImage = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: Blob }) => serviceService.uploadImage(id, file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}

export const useRemoveServiceImage = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => serviceService.removeImage(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}

export const useDeleteManagedService = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => serviceService.deleteService(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    }
  })
}
