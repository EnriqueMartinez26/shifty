import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  paymentsService,
  type AppointmentSearchItem,
  type GatewayConfig,
  type GatewayConfigUpsertPayload,
  type OutboxStats,
  type PaymentPreference,
  type PaymentRecord,
  type ProcessOutboxResult,
  type ReconciliationSummary,
} from "@application/services/PaymentsService";

export const useGatewayConfig = () =>
  useQuery<GatewayConfig>({
    queryKey: ["payments-gateway-config"],
    queryFn: () => paymentsService.getGatewayConfig(),
  });

export const useUpsertGatewayConfig = () => {
  const queryClient = useQueryClient();
  return useMutation<GatewayConfig, Error, GatewayConfigUpsertPayload>({
    mutationFn: (payload) => paymentsService.upsertGatewayConfig(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["payments-gateway-config"] });
    },
  });
};

export const usePaymentsAppointments = () =>
  useQuery<AppointmentSearchItem[]>({
    queryKey: ["payments-appointments"],
    queryFn: () => paymentsService.getAppointments(),
  });

export const useCreatePaymentPreference = () =>
  useMutation<PaymentPreference, Error, string>({
    mutationFn: (appointmentId) => paymentsService.createPreference(appointmentId),
  });

export const useManualConfirmPayment = () =>
  useMutation<PaymentRecord, Error, { appointmentId: string; amount?: number; notes?: string }>({
    mutationFn: ({ appointmentId, amount, notes }) => paymentsService.manualConfirm(appointmentId, amount, notes),
  });

export const useRefundPayment = () =>
  useMutation<PaymentRecord, Error, { paymentId: string; amount?: number; reason?: string; manual?: boolean }>({
    mutationFn: ({ paymentId, amount, reason, manual }) => paymentsService.refund(paymentId, amount, reason, manual),
  });

export const useReconciliationSummary = () =>
  useQuery<ReconciliationSummary>({
    queryKey: ["payments-reconciliation-summary"],
    queryFn: () => paymentsService.getReconciliationSummary(),
  });

export const useOutboxStats = () =>
  useQuery<OutboxStats>({
    queryKey: ["payments-outbox-stats"],
    queryFn: () => paymentsService.getOutboxStats(),
  });

export const useProcessOutbox = () => {
  const queryClient = useQueryClient();
  return useMutation<ProcessOutboxResult, Error, number | undefined>({
    mutationFn: (limit) => paymentsService.processOutbox(limit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["payments-outbox-stats"] });
      queryClient.invalidateQueries({ queryKey: ["payments-reconciliation-summary"] });
    },
  });
};
