import apiClient from '@infrastructure/http/client'
import type { BusinessType } from '@presentation/lib/businessLabels'

export interface AuthenticatedUser {
  email: string
  role: string
  store_id: string | null
  public_id: string
  is_global_admin?: boolean
  first_name?: string
  last_name?: string
}

export interface LoginPayload {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
}

export interface RegisterBusinessPayload {
  store_name: string
  store_slug: string
  business_type: BusinessType
  admin_email: string
  admin_password: string
  admin_first_name: string
  admin_last_name: string
}

export interface ForgotPasswordPayload {
  email: string
}

export interface ForgotPasswordResponse {
  message?: string
}

export interface ResetPasswordPayload {
  token: string
  new_password: string
}

export interface ResetPasswordResponse {
  message?: string
}

export interface ChangePasswordPayload {
  current_password: string
  new_password: string
}

export class AuthService {
  async login(payload: LoginPayload): Promise<LoginResponse> {
    const { data } = await apiClient.post<LoginResponse>('/auth/login', payload)
    return data
  }

  async fetchCurrentUser(): Promise<AuthenticatedUser> {
    const { data } = await apiClient.get<AuthenticatedUser>('/me')
    return data
  }

  async registerBusiness(payload: RegisterBusinessPayload): Promise<void> {
    await apiClient.post('/auth/register', payload)
  }

  async forgotPassword(payload: ForgotPasswordPayload): Promise<ForgotPasswordResponse> {
    const { data } = await apiClient.post<ForgotPasswordResponse>('/auth/forgot-password', payload)
    return data
  }

  async resetPassword(payload: ResetPasswordPayload): Promise<ResetPasswordResponse> {
    const { data } = await apiClient.post<ResetPasswordResponse>('/auth/reset-password', payload)
    return data
  }

  async changePassword(payload: ChangePasswordPayload): Promise<void> {
    await apiClient.put('/auth/change-password', payload)
  }
}

export const authService = new AuthService()
