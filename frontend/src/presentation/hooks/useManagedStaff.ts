import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { StaffService } from "@application/services/StaffService";
import { HttpStaffRepository } from "@infrastructure/repositories/HttpStaffRepository";
import apiClient from "@infrastructure/http/client";
import { Staff } from "@domain/entities/Staff";

const staffService = new StaffService(new HttpStaffRepository(apiClient));

export const useManagedStaff = () =>
  useQuery<Staff[]>({
    queryKey: ["staff"],
    queryFn: () => staffService.listStaff(),
  });

export const useCreateManagedStaff = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: any) => staffService.createStaff(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["staff"] });
    },
  });
};

export const useUpdateManagedStaff = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => staffService.updateStaff(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["staff"] });
    },
  });
};

export const useDeleteManagedStaff = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => staffService.deleteStaff(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["staff"] });
    },
  });
};
