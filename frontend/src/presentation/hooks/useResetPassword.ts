import { useMutation } from "@tanstack/react-query";
import {
  authService,
  type ResetPasswordPayload,
  type ResetPasswordResponse,
} from "@application/services/AuthService";

export const useResetPassword = () =>
  useMutation<ResetPasswordResponse, Error, ResetPasswordPayload>({
    mutationFn: (payload) => authService.resetPassword(payload),
  });
