import { PASSWORD_REJECTED_MESSAGE } from '@domain/value-objects/PasswordRules'

import type { SuperAdminCoupon } from '@application/services/SuperAdminService'

import { formatArgentinaDate } from '@shared/utils/argentinaTime'

import { superAdminGlobalScopeStyle, superAdminTenantScopeStyle } from './palette'
import { colors2000s } from '../../../theme/colors'
import { userRoleLabel } from '../../lib/enumLabels'
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
type FeedbackTone = 'success' | 'error' | 'warning'
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

export const scopeBadgeStyle = (variant: 'global' | 'tenant') => {
  if (variant === 'global') {
    return superAdminGlobalScopeStyle
  }
  return superAdminTenantScopeStyle
}

export const statusBadgeStyle = (variant: 'success' | 'warning' | 'danger' | 'info') => {
  const status = colors2000s.status[variant]
  return {
    background: status.bg,
    border: `1px solid ${status.border}`,
    color: status.text
  }
}

export const panelStyle = create2000sPanelStyle()
export const innerCardStyle = create2000sInnerCardStyle()
export const emptyStateStyle = create2000sEmptyStateStyle()

export const createEmptyStoreForm = (): StoreFormState => ({
  name: '',
  slug: '',
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

export const roleLabel = (role: string, isGlobalAdmin: boolean) =>
  isGlobalAdmin ? 'Super Admin' : userRoleLabel(role)

export const statusLabel = (active: boolean) => (active ? 'Activa' : 'Inactiva')

/**
 * Titulo de un modal que actua sobre la tienda elegida, con la tienda adentro
 * ("Crear admin en «ejemplo»"): se ve antes de enviar. 2026-10-10: un admin se
 * creo en la tienda interna porque nada mostraba cual estaba elegida.
 */
export const storeScopedTitle = (
  action: string,
  preposition: string | null,
  store: { name: string } | null
): string => {
  if (!store) return action
  const target = `«${store.name}»`
  return preposition ? `${action} ${preposition} ${target}` : `${action} ${target}`
}

/** Por que "Crear admin" no se ofrece en la tienda interna (`is_internal`). */
export const INTERNAL_STORE_NOTICE =
  'Tienda interna: solo aloja cuentas SuperAdmin. Los admins de un negocio se crean en su propia tienda.'

export const parseOptionalInt = (value: string) => {
  const trimmed = value.trim()
  return trimmed ? Number.parseInt(trimmed, 10) : null
}

/** "vence en N dias" contando dias de calendario en hora argentina. */
export const daysUntil = (value: string | null | undefined): number | null => {
  if (!value) return null
  const fin = formatArgentinaDate(value)
  const hoy = formatArgentinaDate(new Date().toISOString())
  if (!fin || !hoy) return null
  const dia = (iso: string) => Date.parse(`${iso}T00:00:00Z`)
  return Math.round((dia(fin) - dia(hoy)) / 86_400_000)
}

export const expiryLabel = (value: string | null | undefined): string => {
  const dias = daysUntil(value)
  if (dias === null) return 'Sin vencimiento'
  if (dias < 0) return `Vencida hace ${Math.abs(dias)} d`
  if (dias === 0) return 'Vence hoy'
  return `Vence en ${dias} d`
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
  error: unknown
  refetch: () => unknown
}

// Mismo patron que core/validation.py::SLUG_PATTERN.
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$/
export const SLUG_RULE_TEXT =
  'El slug va en minúsculas, números y guiones, de 2 a 100 caracteres, sin guion al principio ni al final.'

export const isValidSlug = (slug: string) => SLUG_PATTERN.test(slug)

/**
 * Un 422 de los formularios del panel nombra el campo: los modales decian
 * "No se pudo guardar la tienda" sin el motivo (QA 2026-10-02). Nunca el texto
 * crudo de Pydantic (regla 20).
 */
export const SUPERADMIN_FIELD_ERRORS: Partial<Record<string, string>> = {
  slug: SLUG_RULE_TEXT,
  name: 'Revisá el nombre: es demasiado corto, largo o tiene caracteres no permitidos.',
  primary_color: 'El color tiene que ser un hexadecimal, por ejemplo #ff8c42.',
  email: 'Revisá el email: no parece válido.',
  password: PASSWORD_REJECTED_MESSAGE,
  phone: 'Revisá el teléfono: solo números, espacios, guiones, paréntesis o +.',
  first_name: 'Revisá el nombre: es demasiado largo o tiene caracteres no permitidos.',
  last_name: 'Revisá el apellido: es demasiado largo o tiene caracteres no permitidos.',
  code: 'Revisá el código del cupón: letras, números y guiones.'
}
