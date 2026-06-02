import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useService } from './useService';

export interface Shift {
  id: string;
  staffId: string;
  startTime: string;
  endTime: string;
  isAvailable: boolean;
}

export interface CreateShiftDTO {
  staffId: string;
  startTime: string;
  endTime: string;
}

export interface ShiftService {
  getShifts(): Promise<Shift[]>;
  createShift(data: CreateShiftDTO): Promise<Shift>;
  deleteShift(id: string): Promise<void>;
}

/**
 * Hook para gestionar los turnos (Shifts).
 */
export function useShifts() {
  const queryClient = useQueryClient();
  const shiftService = useService<ShiftService>('shiftService');

  const getAllShiftsQuery = useQuery<Shift[]>({
    queryKey: ['shifts'],
    queryFn: () => shiftService.getShifts(),
    staleTime: 5 * 60 * 1000,
  });

  const createShiftMutation = useMutation<Shift, Error, CreateShiftDTO>({
    mutationFn: (data) => shiftService.createShift(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shifts'] });
    },
  });

  const deleteShiftMutation = useMutation<void, Error, string>({
    mutationFn: (id) => shiftService.deleteShift(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shifts'] });
    },
  });

  return {
    getAllShiftsQuery,
    createShiftMutation,
    deleteShiftMutation,
  };
}
export default useShifts;
