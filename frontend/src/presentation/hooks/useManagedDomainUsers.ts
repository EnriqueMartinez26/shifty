import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserService } from "@application/services/UserService";
import { HttpUserRepository } from "@infrastructure/repositories/HttpUserRepository";
import apiClient from "@infrastructure/http/client";
import { User } from "@domain/entities/User";

const userService = new UserService(new HttpUserRepository(apiClient));

export const useManagedDomainUsers = () =>
  useQuery<User[]>({
    queryKey: ["managed-users"],
    queryFn: () => userService.listUsers(true),
  });

export const useCreateManagedDomainUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: any) => userService.createUser(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["managed-users"] });
    },
  });
};

export const useUpdateManagedDomainUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => userService.updateUser(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["managed-users"] });
    },
  });
};

export const useDeleteManagedDomainUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => userService.deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["managed-users"] });
    },
  });
};
