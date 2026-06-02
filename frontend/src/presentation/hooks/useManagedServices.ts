import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ServiceService } from "@application/services/ServiceService";
import { HttpServiceRepository } from "@infrastructure/repositories/HttpServiceRepository";
import apiClient from "@infrastructure/http/client";
import { Service } from "@domain/entities/Service";

const serviceService = new ServiceService(new HttpServiceRepository(apiClient));

export const useManagedServices = () =>
  useQuery<Service[]>({
    queryKey: ["services"],
    queryFn: () => serviceService.listServices(),
  });

export const useCreateManagedService = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: any) => serviceService.createService(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
    },
  });
};

export const useUpdateManagedService = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => serviceService.updateService(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
    },
  });
};

export const useDeleteManagedService = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => serviceService.deleteService(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
    },
  });
};
