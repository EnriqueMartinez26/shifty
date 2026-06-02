import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  appointmentBlocksService,
  type AppointmentBlock,
  type AppointmentBlockPayload,
  type BlockTemplate,
  type RecurringAppointmentBlockPayload,
  type RecurringBlocksResult,
} from "@application/services/AppointmentBlocksService";

export const useAppointmentBlocks = () =>
  useQuery<AppointmentBlock[]>({
    queryKey: ["appointment-blocks"],
    queryFn: () => appointmentBlocksService.list(),
  });

export const useBlockTemplates = () =>
  useQuery<BlockTemplate[]>({
    queryKey: ["appointment-block-templates"],
    queryFn: () => appointmentBlocksService.getTemplates(),
  });

export const useCreateAppointmentBlock = () => {
  const queryClient = useQueryClient();
  return useMutation<AppointmentBlock, Error, AppointmentBlockPayload>({
    mutationFn: (payload) => appointmentBlocksService.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointment-blocks"] });
    },
  });
};

export const useCreateRecurringAppointmentBlock = () => {
  const queryClient = useQueryClient();
  return useMutation<RecurringBlocksResult, Error, RecurringAppointmentBlockPayload>({
    mutationFn: (payload) => appointmentBlocksService.createRecurring(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointment-blocks"] });
    },
  });
};

export const useUpdateAppointmentBlock = () => {
  const queryClient = useQueryClient();
  return useMutation<AppointmentBlock, Error, { publicId: string; payload: Partial<AppointmentBlockPayload> & { is_active?: boolean } }>({
    mutationFn: ({ publicId, payload }) => appointmentBlocksService.update(publicId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointment-blocks"] });
    },
  });
};

export const useDeleteAppointmentBlock = () => {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (publicId) => appointmentBlocksService.delete(publicId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointment-blocks"] });
    },
  });
};
