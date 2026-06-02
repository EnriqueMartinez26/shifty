import { useQuery } from "@tanstack/react-query";
import { ServiceService } from "@application/services/ServiceService";
import { HttpServiceRepository } from "@infrastructure/repositories/HttpServiceRepository";
import apiClient from "@infrastructure/http/client";

const serviceService = new ServiceService(new HttpServiceRepository(apiClient));

export const useServicesCatalog = () =>
  useQuery({
    queryKey: ["services"],
    queryFn: () => serviceService.listServices(),
  });
