import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ledgerService,
  type CustomerLedger,
  type LedgerMovement,
  type LedgerMovementPayload,
} from "@application/services/LedgerService";

export const useCustomerLedger = (clientId: string | null) =>
  useQuery<CustomerLedger>({
    queryKey: ["customer-ledger", clientId],
    queryFn: () => ledgerService.getCustomerLedger(clientId as string),
    enabled: Boolean(clientId),
  });

export const useAddLedgerMovement = () => {
  const queryClient = useQueryClient();
  return useMutation<LedgerMovement, Error, { clientId: string; payload: LedgerMovementPayload }>({
    mutationFn: ({ clientId, payload }) => ledgerService.addMovement(clientId, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["customer-ledger", variables.clientId] });
    },
  });
};
