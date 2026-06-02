import { useMutation } from "@tanstack/react-query";
import {
  authService,
  type ForgotPasswordPayload,
  type ForgotPasswordResponse,
} from "@application/services/AuthService";

export const useForgotPassword = () =>
  useMutation<ForgotPasswordResponse, Error, ForgotPasswordPayload>({
    mutationFn: (payload) => authService.forgotPassword(payload),
  });
