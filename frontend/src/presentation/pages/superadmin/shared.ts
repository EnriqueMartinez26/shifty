import type { SuperAdminCoupon } from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import {
  create2000sEmptyStateStyle,
  create2000sInnerCardStyle,
  create2000sPanelStyle
} from '../../lib/surfaceStyles'

/**
 * Tipos, estilos y helpers compartidos del panel SuperAdmin.
 *
 * Vivian dentro de SuperAdmin.tsx; se separan para que las secciones y los
 * modales (descompuestos por dominio) puedan importarlos sin ciclos.
 */

export type ActivityFilter = 'active' | 'inactive' | 'all'
export type SubscriptionFilter = 'all' | 'with' | 'without'
export type FeedbackTone = 'success' | 'error' | 'warning'
export type SuperAdminModalKey =
  | 'create-store'
  | 'edit-store'
  | 'create-admin'
  | 'edit-user'
  | 'create-plan'
  | 'edit-plan'
  | 'assign-plan'
  | 'create-coupon'
  | 'edit-coupon'
  | 'redeem-coupon'
  | null

export interface FeedbackMessage {
  tone: FeedbackTone
  text: string
}

export interface StoreFormState {
  name: string
  slug: string
  logo_url: string
  primary_color: string
  cancellation_hours: string
  buffer_minutes: string
  send_email_confirmation: boolean
  send_email_reminders: boolean
  is_active: boolean
}

export interface AdminFormState {
  email: string
  password: string
  first_name: string
  last_name: string
  phone: string
}

export interface UserFormState {
  email: string
  first_name: string
  last_name: string
  phone: string
  role: 'admin' | 'staff' | 'receptionist' | 'client'
  password: string
  is_active: boolean
}

export interface PlanFormState {
  name: string
  description: string
  price: string
  currency: string
  billing_interval: string
  max_staff: string
  max_services: string
  is_active: boolean
}

export interface SubscriptionFormState {
  plan_id: string
  status: string
  base_amount: string
  currency: string
  current_period_start: string
  current_period_end: string
}

export interface CouponFormState {
  code: string
  coupon_type: 'percent' | 'fixed'
  value: string
  currency: string
  max_uses: string
  valid_from: string
  valid_until: string
  one_time_per_store: boolean
  description: string
  is_active: boolean
}

export interface RedeemFormState {
  coupon_code: string
}

export const scopeBadgeStyle = (variant: 'global' | 'tenant' | 'danger') => {
  if (variant === 'global') {
    return {
      background: '#eff6ff',
      border: '1px solid #bfdbfe',
      color: '#1d4ed8'
    }
  }
  if (variant === 'danger') {
    return {
      background: '#fff1f2',
      border: '1px solid #fecdd3',
      color: '#be123c'
    }
  }
  return {
    background: '#fff7ed',
    border: `1px solid ${colors2000s.orange.light}`,
    color: colors2000s.orange.accent
  }
}

export const panelStyle = create2000sPanelStyle()
export const innerCardStyle = create2000sInnerCardStyle()
export const emptyStateStyle = create2000sEmptyStateStyle()

export const createEmptyStoreForm = (): StoreFormState => ({
  name: '',
  slug: '',
  logo_url: '',
  primary_color: '#ff8c42',
  cancellation_hours: '24',
  buffer_minutes: '0',
  send_email_confirmation: true,
  send_email_reminders: true,
  is_active: true
})

export const createEmptyAdminForm = (): AdminFormState => ({
  email: '',
  password: '',
  first_name: '',
  last_name: '',
  phone: ''
})

export const createEmptyUserForm = (): UserFormState => ({
  email: '',
  first_name: '',
  last_name: '',
  phone: '',
  role: 'staff',
  password: '',
  is_active: true
})

export const createEmptyPlanForm = (): PlanFormState => ({
  name: '',
  description: '',
  price: '',
  currency: 'ARS',
  billing_interval: 'monthly',
  max_staff: '',
  max_services: '',
  is_active: true
})

export const createEmptySubscriptionForm = (): SubscriptionFormState => ({
  plan_id: '',
  status: 'active',
  base_amount: '',
  currency: 'ARS',
  current_period_start: '',
  current_period_end: ''
})

export const createEmptyCouponForm = (): CouponFormState => ({
  code: '',
  coupon_type: 'percent',
  value: '',
  currency: 'ARS',
  max_uses: '',
  valid_from: '',
  valid_until: '',
  one_time_per_store: true,
  description: '',
  is_active: true
})

export const createEmptyRedeemForm = (): RedeemFormState => ({
  coupon_code: ''
})

export const roleLabel = (role: string, isGlobalAdmin: boolean) => {
  if (isGlobalAdmin) return 'Super Admin'
  if (role === 'admin') return 'Admin'
  if (role === 'staff') return 'Profesional'
  if (role === 'receptionist') return 'Recepcion'
  return 'Usuario'
}

export const statusLabel = (active: boolean) => (active ? 'Activa' : 'Inactiva')

export const parseOptionalInt = (value: string) => {
  const trimmed = value.trim()
  return trimmed ? Number.parseInt(trimmed, 10) : null
}

export const toDateTimeInput = (value: string | null) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return (
    [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join('-') +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

export const isCouponExpired = (coupon: SuperAdminCoupon) =>
  Boolean(coupon.valid_until && new Date(coupon.valid_until).getTime() < Date.now())

export const isCouponExhausted = (coupon: SuperAdminCoupon) =>
  coupon.max_uses !== null && coupon.current_uses >= coupon.max_uses

export const formGridClass = 'grid gap-4 md:grid-cols-2'

/** Lo unico que los modales necesitan saber de una mutation de react-query. */
export interface PendingState {
  isPending: boolean
}

/** Lo que las secciones leen de una query de react-query. */
export interface QueryState<T> {
  data: T | undefined
  isLoading: boolean
  isFetching: boolean
}
