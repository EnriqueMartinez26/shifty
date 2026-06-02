import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { budgetService, type BudgetItem, type BudgetPayload } from "@application/services/BudgetService";

export type { BudgetItem, BudgetPayload };

export const useBudgets = (includeInactive = false) => {
  return useQuery({
    queryKey: ["budgets", includeInactive],
    queryFn: (): Promise<BudgetItem[]> => budgetService.list(includeInactive),
  });
};

export const useCreateBudget = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BudgetPayload) => budgetService.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
};

export const useUpdateBudget = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ publicId, payload }: { publicId: string; payload: Partial<BudgetPayload> }) => budgetService.update(publicId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
};

export const useDeleteBudget = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (publicId: string) => budgetService.delete(publicId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
};
