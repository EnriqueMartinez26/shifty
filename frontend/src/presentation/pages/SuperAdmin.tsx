import React, { useEffect, useMemo, useState } from 'react'

import {
  AlertTriangle,
  BadgeCheck,
  Building2,
  CreditCard,
  Filter,
  Loader2,
  Search,
  Shield,
  Tag,
  Users
} from 'lucide-react'

import {
  type SuperAdminCoupon,
  type SuperAdminPlan,
  type SuperAdminStoreRow,
  type SuperAdminUser
} from '@application/services/SuperAdminService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { SuperAdminAuditTimeline } from '../components/organisms/SuperAdminAuditTimeline'
import { SuperAdminFormModal } from '../components/organisms/SuperAdminFormModal'
import { SuperAdminHealthPanel } from '../components/organisms/SuperAdminHealthPanel'
import { useAuth } from '../context/AuthContext'
import {
  useAssignSuperAdminSubscription,
  useCreateSuperAdminCoupon,
  useCreateSuperAdminPlan,
  useCreateSuperAdminStore,
  useCreateSuperAdminStoreAdmin,
  useRedeemSuperAdminCoupon,
  useSetSuperAdminGlobalAdmin,
  useSuperAdminCoupons,
  useSuperAdminStoreAudit,
  useSuperAdminOverview,
  useSuperAdminPlans,
  useSuperAdminStores,
  useUpdateSuperAdminCoupon,
  useUpdateSuperAdminPlan,
  useUpdateSuperAdminStore,
  useUpdateSuperAdminUser
} from '../hooks/useSuperAdmin'
import { formatCurrencyEsAr, formatDateEsAr, formatDateTimeEsAr } from '../lib/formatters'
import {
  create2000sEmptyStateStyle,
  create2000sInputStyle,
  create2000sInnerCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

type ActivityFilter = 'active' | 'inactive' | 'all'
type SubscriptionFilter = 'all' | 'with' | 'without'
type FeedbackTone = 'success' | 'error' | 'warning'
type SuperAdminModalKey =
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

interface FeedbackMessage {
  tone: FeedbackTone
  text: string
}

interface StoreFormState {
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

interface AdminFormState {
  email: string
  password: string
  first_name: string
  last_name: string
  phone: string
}

interface UserFormState {
  email: string
  first_name: string
  last_name: string
  phone: string
  role: 'admin' | 'staff' | 'receptionist' | 'client'
  password: string
  is_active: boolean
}

interface PlanFormState {
  name: string
  description: string
  price: string
  currency: string
  billing_interval: string
  max_staff: string
  max_services: string
  is_active: boolean
}

interface SubscriptionFormState {
  plan_id: string
  status: string
  base_amount: string
  currency: string
  current_period_start: string
  current_period_end: string
}

interface CouponFormState {
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

interface RedeemFormState {
  coupon_code: string
}

const scopeBadgeStyle = (variant: 'global' | 'tenant' | 'danger') => {
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

const panelStyle = create2000sPanelStyle()
const innerCardStyle = create2000sInnerCardStyle()
const emptyStateStyle = create2000sEmptyStateStyle()

const primaryActionStyle = {
  ...buttonStyles2000s.selected,
  borderRadius: '14px',
  padding: '12px 16px',
  fontSize: '10px',
  fontWeight: 900,
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const
}

const secondaryActionStyle = {
  ...buttonStyles2000s.default,
  borderRadius: '14px',
  padding: '12px 16px',
  fontSize: '10px',
  fontWeight: 900,
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const
}

const dangerActionStyle = {
  ...buttonStyles2000s.default,
  borderRadius: '14px',
  padding: '12px 16px',
  fontSize: '10px',
  fontWeight: 900,
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const,
  color: '#b91c1c',
  background: 'rgba(239,68,68,0.06)'
}

const createEmptyStoreForm = (): StoreFormState => ({
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

const createEmptyAdminForm = (): AdminFormState => ({
  email: '',
  password: '',
  first_name: '',
  last_name: '',
  phone: ''
})

const createEmptyUserForm = (): UserFormState => ({
  email: '',
  first_name: '',
  last_name: '',
  phone: '',
  role: 'staff',
  password: '',
  is_active: true
})

const createEmptyPlanForm = (): PlanFormState => ({
  name: '',
  description: '',
  price: '',
  currency: 'ARS',
  billing_interval: 'monthly',
  max_staff: '',
  max_services: '',
  is_active: true
})

const createEmptySubscriptionForm = (): SubscriptionFormState => ({
  plan_id: '',
  status: 'active',
  base_amount: '',
  currency: 'ARS',
  current_period_start: '',
  current_period_end: ''
})

const createEmptyCouponForm = (): CouponFormState => ({
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

const createEmptyRedeemForm = (): RedeemFormState => ({
  coupon_code: ''
})

const roleLabel = (role: string, isGlobalAdmin: boolean) => {
  if (isGlobalAdmin) return 'Super Admin'
  if (role === 'admin') return 'Admin'
  if (role === 'staff') return 'Profesional'
  if (role === 'receptionist') return 'Recepcion'
  return 'Usuario'
}

const statusLabel = (active: boolean) => (active ? 'Activa' : 'Inactiva')

const parseOptionalInt = (value: string) => {
  const trimmed = value.trim()
  return trimmed ? Number.parseInt(trimmed, 10) : null
}

const toDateTimeInput = (value: string | null) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return (
    [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join('-') +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

const isCouponExpired = (coupon: SuperAdminCoupon) =>
  Boolean(coupon.valid_until && new Date(coupon.valid_until).getTime() < Date.now())

const isCouponExhausted = (coupon: SuperAdminCoupon) =>
  coupon.max_uses !== null && coupon.current_uses >= coupon.max_uses

const formGridClass = 'grid gap-4 md:grid-cols-2'

const FieldLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <label
    className="mb-1 block text-[10px] font-black uppercase tracking-widest"
    style={{ color: colors2000s.text.secondary }}
  >
    {children}
  </label>
)

const TextInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({
  className = '',
  ...props
}) => (
  <input
    {...props}
    className={`w-full rounded-2xl px-4 py-3 text-sm font-bold ${className}`.trim()}
    style={create2000sInputStyle()}
  />
)

const TextArea: React.FC<React.TextareaHTMLAttributes<HTMLTextAreaElement>> = ({
  className = '',
  ...props
}) => (
  <textarea
    {...props}
    className={`min-h-24 w-full rounded-2xl px-4 py-3 text-sm font-bold resize-y ${className}`.trim()}
    style={create2000sInputStyle()}
  />
)

const SelectInput: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({
  className = '',
  children,
  ...props
}) => (
  <select
    {...props}
    className={`w-full rounded-2xl px-4 py-3 text-sm font-bold ${className}`.trim()}
    style={create2000sInputStyle()}
  >
    {children}
  </select>
)

const ToggleRow: React.FC<{
  label: string
  description: string
  checked: boolean
  onToggle: () => void
}> = ({ label, description, checked, onToggle }) => (
  <div
    className="flex items-center justify-between gap-4 rounded-2xl px-4 py-3"
    style={create2000sInnerCardStyle()}
  >
    <div>
      <p
        className="text-[10px] font-black uppercase tracking-widest"
        style={{ color: colors2000s.text.secondary }}
      >
        {label}
      </p>
      <p className="mt-1 text-xs font-bold" style={{ color: colors2000s.text.primary }}>
        {description}
      </p>
    </div>
    <button
      type="button"
      onClick={onToggle}
      className="relative h-7 w-14 rounded-full"
      style={{
        background: checked ? colors2000s.orange.light : colors2000s.bg.disabled,
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.insetDark
      }}
    >
      <span
        className="absolute top-1 h-5 w-5 rounded-full transition-all"
        style={{
          left: checked ? '32px' : '4px',
          background: 'white',
          boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
        }}
      />
    </button>
  </div>
)

const ActionButton: React.FC<{
  label: string
  onClick: () => void
  disabled?: boolean
  tone?: 'primary' | 'secondary' | 'danger'
}> = ({ label, onClick, disabled = false, tone = 'secondary' }) => {
  const style =
    tone === 'primary'
      ? primaryActionStyle
      : tone === 'danger'
        ? dangerActionStyle
        : secondaryActionStyle
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="disabled:opacity-50"
      style={style}
    >
      {label}
    </button>
  )
}

const MiniButton: React.FC<{
  label: string
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void
  tone?: 'default' | 'primary' | 'danger'
  disabled?: boolean
}> = ({ label, onClick, tone = 'default', disabled = false }) => {
  const style =
    tone === 'primary'
      ? primaryActionStyle
      : tone === 'danger'
        ? dangerActionStyle
        : secondaryActionStyle
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="px-3 py-2 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
      style={{ ...style, padding: '8px 12px' }}
    >
      {label}
    </button>
  )
}

const SuperAdminPage: React.FC = () => {
  const { user } = useAuth()

  const [search, setSearch] = useState('')
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>('active')
  const [subscriptionFilter, setSubscriptionFilter] = useState<SubscriptionFilter>('all')
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null)
  const [modal, setModal] = useState<SuperAdminModalKey>(null)
  const [feedback, setFeedback] = useState<FeedbackMessage | null>(null)
  const [modalError, setModalError] = useState<string | null>(null)

  const [storeForm, setStoreForm] = useState<StoreFormState>(createEmptyStoreForm())
  const [adminForm, setAdminForm] = useState<AdminFormState>(createEmptyAdminForm())
  const [userForm, setUserForm] = useState<UserFormState>(createEmptyUserForm())
  const [planForm, setPlanForm] = useState<PlanFormState>(createEmptyPlanForm())
  const [subscriptionForm, setSubscriptionForm] = useState<SubscriptionFormState>(
    createEmptySubscriptionForm()
  )
  const [couponForm, setCouponForm] = useState<CouponFormState>(createEmptyCouponForm())
  const [redeemForm, setRedeemForm] = useState<RedeemFormState>(createEmptyRedeemForm())

  const [editingUser, setEditingUser] = useState<SuperAdminUser | null>(null)
  const [editingPlan, setEditingPlan] = useState<SuperAdminPlan | null>(null)
  const [editingCoupon, setEditingCoupon] = useState<SuperAdminCoupon | null>(null)

  const storeParams = useMemo(
    () => ({
      search: search.trim() || undefined,
      is_active: activityFilter === 'all' ? null : activityFilter === 'active',
      has_subscription: subscriptionFilter === 'all' ? null : subscriptionFilter === 'with'
    }),
    [activityFilter, search, subscriptionFilter]
  )

  const storesQuery = useSuperAdminStores(storeParams)
  const overviewQuery = useSuperAdminOverview(selectedStoreId)
  const auditQuery = useSuperAdminStoreAudit(selectedStoreId)
  const plansQuery = useSuperAdminPlans(true)
  const couponsQuery = useSuperAdminCoupons(true)

  const createStoreMutation = useCreateSuperAdminStore()
  const updateStoreMutation = useUpdateSuperAdminStore()
  const createAdminMutation = useCreateSuperAdminStoreAdmin()
  const updateUserMutation = useUpdateSuperAdminUser()
  const setGlobalAdminMutation = useSetSuperAdminGlobalAdmin()
  const createPlanMutation = useCreateSuperAdminPlan()
  const updatePlanMutation = useUpdateSuperAdminPlan()
  const assignSubscriptionMutation = useAssignSuperAdminSubscription()
  const createCouponMutation = useCreateSuperAdminCoupon()
  const updateCouponMutation = useUpdateSuperAdminCoupon()
  const redeemCouponMutation = useRedeemSuperAdminCoupon()

  useEffect(() => {
    const firstStore = storesQuery.data?.[0]
    if (!firstStore) {
      setSelectedStoreId(null)
      return
    }
    const selectedExists = storesQuery.data?.some(
      (store) => store.public_id === selectedStoreId
    )
    if (!selectedExists) {
      setSelectedStoreId(firstStore.public_id)
    }
  }, [selectedStoreId, storesQuery.data])

  useEffect(() => {
    setModalError(null)
  }, [modal])

  const selectedStore = useMemo(
    () => storesQuery.data?.find((store) => store.public_id === selectedStoreId) ?? null,
    [selectedStoreId, storesQuery.data]
  )

  const overview = overviewQuery.data
  const activePlans = useMemo(
    () => (plansQuery.data ?? []).filter((plan) => plan.is_active),
    [plansQuery.data]
  )
  const activeCoupons = useMemo(
    () => (couponsQuery.data ?? []).filter((coupon) => coupon.is_active),
    [couponsQuery.data]
  )
  const hasSelectedStoreSubscription = Boolean(overview?.subscription)
  const selectedStoreUnavailable = !selectedStore || !selectedStore.is_active

  const closeModal = () => {
    setModal(null)
    setModalError(null)
  }

  const openCreateStoreModal = () => {
    setStoreForm(createEmptyStoreForm())
    setModal('create-store')
  }

  const openEditStoreFor = (store: SuperAdminStoreRow) => {
    setStoreForm({
      name: store.name,
      slug: store.slug,
      logo_url:
        overview?.store.public_id === store.public_id
          ? overview.store.logo_url || ''
          : store.logo_url || '',
      primary_color: store.primary_color,
      cancellation_hours: String(
        overview?.store.public_id === store.public_id
          ? overview.store.cancellation_hours
          : store.cancellation_hours
      ),
      buffer_minutes: String(
        overview?.store.public_id === store.public_id
          ? overview.store.buffer_minutes
          : store.buffer_minutes
      ),
      send_email_confirmation:
        overview?.store.public_id === store.public_id
          ? overview.store.send_email_confirmation
          : store.send_email_confirmation,
      send_email_reminders:
        overview?.store.public_id === store.public_id
          ? overview.store.send_email_reminders
          : store.send_email_reminders,
      is_active: store.is_active
    })
    setModal('edit-store')
  }

  const openEditStoreModal = () => {
    if (!selectedStore) return
    openEditStoreFor(selectedStore)
  }

  const openCreateAdminModal = () => {
    setAdminForm(createEmptyAdminForm())
    setModal('create-admin')
  }

  const openEditUserModal = (targetUser: SuperAdminUser) => {
    setEditingUser(targetUser)
    setUserForm({
      email: targetUser.email,
      first_name: targetUser.first_name || '',
      last_name: targetUser.last_name || '',
      phone: targetUser.phone || '',
      role: targetUser.role,
      password: '',
      is_active: targetUser.is_active
    })
    setModal('edit-user')
  }

  const openCreatePlanModal = () => {
    setEditingPlan(null)
    setPlanForm(createEmptyPlanForm())
    setModal('create-plan')
  }

  const openEditPlanModal = (plan: SuperAdminPlan) => {
    setEditingPlan(plan)
    setPlanForm({
      name: plan.name,
      description: plan.description || '',
      price: String(plan.price),
      currency: plan.currency,
      billing_interval: plan.billing_interval,
      max_staff: plan.max_staff !== null ? String(plan.max_staff) : '',
      max_services: plan.max_services !== null ? String(plan.max_services) : '',
      is_active: plan.is_active
    })
    setModal('edit-plan')
  }

  const openAssignPlanModal = () => {
    if (!selectedStore) return
    setSubscriptionForm({
      plan_id: overview?.subscription?.plan_id || activePlans[0]?.public_id || '',
      status: overview?.subscription?.status || 'active',
      base_amount: overview?.subscription?.base_amount
        ? String(overview.subscription.base_amount)
        : '',
      currency: overview?.subscription?.currency || 'ARS',
      current_period_start: toDateTimeInput(overview?.subscription?.current_period_start || null),
      current_period_end: toDateTimeInput(overview?.subscription?.current_period_end || null)
    })
    setModal('assign-plan')
  }

  const openCreateCouponModal = () => {
    setEditingCoupon(null)
    setCouponForm(createEmptyCouponForm())
    setModal('create-coupon')
  }

  const openEditCouponModal = (coupon: SuperAdminCoupon) => {
    setEditingCoupon(coupon)
    setCouponForm({
      code: coupon.code,
      coupon_type: coupon.coupon_type as 'percent' | 'fixed',
      value: String(coupon.value),
      currency: coupon.currency || 'ARS',
      max_uses: coupon.max_uses !== null ? String(coupon.max_uses) : '',
      valid_from: toDateTimeInput(coupon.valid_from),
      valid_until: toDateTimeInput(coupon.valid_until),
      one_time_per_store: coupon.one_time_per_store,
      description: coupon.description || '',
      is_active: coupon.is_active
    })
    setModal('edit-coupon')
  }

  const openRedeemCouponModal = () => {
    setRedeemForm({
      coupon_code: activeCoupons[0]?.code || ''
    })
    setModal('redeem-coupon')
  }

  const handleStoreSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setModalError(null)

    try {
      const payload = {
        name: storeForm.name.trim(),
        slug: storeForm.slug.trim(),
        logo_url: storeForm.logo_url.trim() || null,
        primary_color: storeForm.primary_color.trim() || '#ff8c42',
        cancellation_hours: Number(storeForm.cancellation_hours || 0),
        buffer_minutes: Number(storeForm.buffer_minutes || 0),
        send_email_confirmation: storeForm.send_email_confirmation,
        send_email_reminders: storeForm.send_email_reminders
      }

      if (modal === 'create-store') {
        const created = await createStoreMutation.mutateAsync(payload)
        setSelectedStoreId(created.public_id)
        setFeedback({ tone: 'success', text: `Tienda creada: ${created.name}` })
      } else if (selectedStore) {
        const updated = await updateStoreMutation.mutateAsync({
          storePublicId: selectedStore.public_id,
          payload: {
            ...payload,
            is_active: storeForm.is_active
          }
        })
        setFeedback({ tone: 'success', text: `Tienda actualizada: ${updated.name}` })
      }

      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo guardar la tienda'))
    }
  }

  const handleAdminSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedStore) return
    setModalError(null)

    try {
      const created = await createAdminMutation.mutateAsync({
        storePublicId: selectedStore.public_id,
        payload: {
          email: adminForm.email.trim(),
          password: adminForm.password,
          first_name: adminForm.first_name.trim(),
          last_name: adminForm.last_name.trim(),
          phone: adminForm.phone.trim() || null
        }
      })
      setFeedback({ tone: 'success', text: `Admin creado: ${created.email}` })
      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo crear el admin'))
    }
  }

  const handleUserSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!editingUser) return
    setModalError(null)

    try {
      const updated = await updateUserMutation.mutateAsync({
        userPublicId: editingUser.public_id,
        payload: {
          first_name: userForm.first_name.trim() || undefined,
          last_name: userForm.last_name.trim() || undefined,
          phone: userForm.phone.trim() || null,
          role: userForm.role,
          password: userForm.password.trim() || undefined,
          is_active: userForm.is_active
        }
      })
      setFeedback({ tone: 'success', text: `Usuario actualizado: ${updated.email}` })
      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo actualizar el usuario'))
    }
  }

  const handlePlanSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setModalError(null)

    try {
      const payload = {
        name: planForm.name.trim(),
        description: planForm.description.trim() || null,
        price: planForm.price.trim(),
        currency: planForm.currency.trim() || 'ARS',
        billing_interval: planForm.billing_interval.trim() || 'monthly',
        max_staff: parseOptionalInt(planForm.max_staff),
        max_services: parseOptionalInt(planForm.max_services)
      }

      if (modal === 'create-plan') {
        const created = await createPlanMutation.mutateAsync(payload)
        setFeedback({ tone: 'success', text: `Plan creado: ${created.name}` })
      } else if (editingPlan) {
        const updated = await updatePlanMutation.mutateAsync({
          planPublicId: editingPlan.public_id,
          payload: {
            ...payload,
            is_active: planForm.is_active
          }
        })
        setFeedback({ tone: 'success', text: `Plan actualizado: ${updated.name}` })
      }

      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo guardar el plan'))
    }
  }

  const handleSubscriptionSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedStore) return
    setModalError(null)

    try {
      await assignSubscriptionMutation.mutateAsync({
        storePublicId: selectedStore.public_id,
        payload: {
          plan_id: subscriptionForm.plan_id,
          status: subscriptionForm.status.trim() || 'active',
          base_amount: subscriptionForm.base_amount.trim() || null,
          currency: subscriptionForm.currency.trim() || null,
          current_period_start: subscriptionForm.current_period_start || null,
          current_period_end: subscriptionForm.current_period_end || null
        }
      })
      setFeedback({ tone: 'success', text: `Suscripcion actualizada para ${selectedStore.name}` })
      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo asignar el plan'))
    }
  }

  const handleCouponSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setModalError(null)

    try {
      const payload = {
        code: couponForm.code.trim().toUpperCase(),
        coupon_type: couponForm.coupon_type,
        value: couponForm.value.trim(),
        currency: couponForm.coupon_type === 'fixed' ? couponForm.currency.trim() || 'ARS' : null,
        max_uses: parseOptionalInt(couponForm.max_uses),
        valid_from: couponForm.valid_from || null,
        valid_until: couponForm.valid_until || null,
        one_time_per_store: couponForm.one_time_per_store,
        description: couponForm.description.trim() || null
      }

      if (modal === 'create-coupon') {
        const created = await createCouponMutation.mutateAsync(payload)
        setFeedback({ tone: 'success', text: `Cupon creado: ${created.code}` })
      } else if (editingCoupon) {
        const updated = await updateCouponMutation.mutateAsync({
          couponPublicId: editingCoupon.public_id,
          payload: {
            ...payload,
            is_active: couponForm.is_active
          }
        })
        setFeedback({ tone: 'success', text: `Cupon actualizado: ${updated.code}` })
      }

      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo guardar el cupon'))
    }
  }

  const handleRedeemSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedStore) return
    setModalError(null)

    try {
      const redemption = await redeemCouponMutation.mutateAsync({
        storePublicId: selectedStore.public_id,
        couponCode: redeemForm.coupon_code.trim().toUpperCase()
      })
      setFeedback({
        tone: 'success',
        text: `Cupon ${redemption.code_snapshot} canjeado en ${selectedStore.name}`
      })
      closeModal()
    } catch (error) {
      setModalError(getErrorMessage(error, 'No se pudo canjear el cupon'))
    }
  }

  const toggleStoreActive = async (store: SuperAdminStoreRow) => {
    const nextActiveState = !store.is_active
    const confirmed = window.confirm(
      nextActiveState
        ? `Activar ${store.name}?`
        : `Desactivar ${store.name}? Esto puede bloquear nuevas operaciones del tenant.`
    )
    if (!confirmed) return

    try {
      await updateStoreMutation.mutateAsync({
        storePublicId: store.public_id,
        payload: { is_active: nextActiveState }
      })
      setFeedback({
        tone: nextActiveState ? 'success' : 'warning',
        text: `Tienda ${nextActiveState ? 'activada' : 'desactivada'}: ${store.name}`
      })
    } catch (error) {
      setFeedback({
        tone: 'error',
        text: getErrorMessage(error, 'No se pudo cambiar el estado de la tienda')
      })
    }
  }

  const toggleUserActive = async (targetUser: SuperAdminUser) => {
    const nextActiveState = !targetUser.is_active
    const confirmed = window.confirm(
      nextActiveState ? `Activar ${targetUser.email}?` : `Desactivar ${targetUser.email}?`
    )
    if (!confirmed) return

    try {
      await updateUserMutation.mutateAsync({
        userPublicId: targetUser.public_id,
        payload: { is_active: nextActiveState }
      })
      setFeedback({
        tone: nextActiveState ? 'success' : 'warning',
        text: `Usuario ${nextActiveState ? 'activado' : 'desactivado'}: ${targetUser.email}`
      })
    } catch (error) {
      setFeedback({
        tone: 'error',
        text: getErrorMessage(error, 'No se pudo cambiar el estado del usuario')
      })
    }
  }

  const toggleGlobalAdmin = async (targetUser: SuperAdminUser) => {
    const nextGlobalState = !targetUser.is_global_admin
    if (!nextGlobalState && user?.public_id === targetUser.public_id) {
      setFeedback({
        tone: 'warning',
        text: 'No podés revocarte tu propio permiso global desde esta sesion.'
      })
      return
    }

    const confirmed = window.confirm(
      nextGlobalState
        ? `Promover a ${targetUser.email} como Super Admin global?`
        : `Revocar Super Admin global a ${targetUser.email}? El backend impedira dejar al sistema sin un admin global activo.`
    )
    if (!confirmed) return

    try {
      await setGlobalAdminMutation.mutateAsync({
        userPublicId: targetUser.public_id,
        isGlobalAdmin: nextGlobalState
      })
      setFeedback({
        tone: nextGlobalState ? 'success' : 'warning',
        text: `${targetUser.email} ${nextGlobalState ? 'ahora es' : 'dejo de ser'} Super Admin`
      })
    } catch (error) {
      setFeedback({
        tone: 'error',
        text: getErrorMessage(error, 'No se pudo actualizar el permiso global')
      })
    }
  }

  const togglePlanActive = async (plan: SuperAdminPlan) => {
    const nextActiveState = !plan.is_active
    const confirmed = window.confirm(
      nextActiveState ? `Activar plan ${plan.name}?` : `Desactivar plan ${plan.name}?`
    )
    if (!confirmed) return

    try {
      await updatePlanMutation.mutateAsync({
        planPublicId: plan.public_id,
        payload: { is_active: nextActiveState }
      })
      setFeedback({
        tone: nextActiveState ? 'success' : 'warning',
        text: `Plan ${nextActiveState ? 'activado' : 'desactivado'}: ${plan.name}`
      })
    } catch (error) {
      setFeedback({ tone: 'error', text: getErrorMessage(error, 'No se pudo actualizar el plan') })
    }
  }

  const toggleCouponActive = async (coupon: SuperAdminCoupon) => {
    const nextActiveState = !coupon.is_active
    const confirmed = window.confirm(
      nextActiveState ? `Activar cupon ${coupon.code}?` : `Desactivar cupon ${coupon.code}?`
    )
    if (!confirmed) return

    try {
      await updateCouponMutation.mutateAsync({
        couponPublicId: coupon.public_id,
        payload: { is_active: nextActiveState }
      })
      setFeedback({
        tone: nextActiveState ? 'success' : 'warning',
        text: `Cupon ${nextActiveState ? 'activado' : 'desactivado'}: ${coupon.code}`
      })
    } catch (error) {
      setFeedback({ tone: 'error', text: getErrorMessage(error, 'No se pudo actualizar el cupon') })
    }
  }

  const feedbackStyle =
    feedback?.tone === 'success'
      ? { background: '#ecfdf5', border: '1px solid #bbf7d0', color: '#15803d' }
      : feedback?.tone === 'warning'
        ? { background: '#fff7ed', border: '1px solid #fed7aa', color: '#c2410c' }
        : { background: '#fff1f2', border: '1px solid #fecdd3', color: '#be123c' }

  return (
    <div className="space-y-6">
      {feedback ? (
        <div
          className="flex items-start gap-3 rounded-[1.5rem] px-5 py-4 text-sm font-bold"
          style={feedbackStyle}
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0" />
          <div className="flex-1">
            <p>{feedback.text}</p>
          </div>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-xs font-black uppercase tracking-widest"
          >
            Cerrar
          </button>
        </div>
      ) : null}

      <section className="rounded-[2rem] p-6" style={panelStyle}>
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span
                className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                style={scopeBadgeStyle('global')}
              >
                Alcance Global
              </span>
              <span
                className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                style={scopeBadgeStyle('tenant')}
              >
                Tienda Seleccionada
              </span>
            </div>
            <div>
              <h1
                className="text-3xl font-black uppercase tracking-tight"
                style={{ color: colors2000s.text.primary }}
              >
                Control Global
              </h1>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                Operacion multi-tenant para tiendas, admins, suscripciones y cupones.
              </p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <ActionButton label="Crear tienda" onClick={openCreateStoreModal} tone="primary" />
            <ActionButton
              label="Editar tienda"
              onClick={openEditStoreModal}
              disabled={!selectedStore}
            />
            <ActionButton
              label="Crear admin"
              onClick={openCreateAdminModal}
              disabled={!selectedStore}
            />
            <ActionButton
              label="Asignar plan"
              onClick={openAssignPlanModal}
              disabled={!selectedStore || !activePlans.length}
            />
            <ActionButton
              label="Canjear cupon"
              onClick={openRedeemCouponModal}
              disabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
            />
          </div>
        </div>

        <div className="mt-6 rounded-[1.75rem] p-5" style={innerCardStyle}>
          {selectedStore ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
                <div>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Tienda activa
                  </p>
                  <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>
                    {selectedStore.name}
                  </p>
                </div>
                <div>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Estado
                  </p>
                  <span
                    className="inline-flex rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                    style={
                      selectedStore.is_active
                        ? scopeBadgeStyle('tenant')
                        : scopeBadgeStyle('danger')
                    }
                  >
                    {statusLabel(selectedStore.is_active)}
                  </span>
                </div>
                <div>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Slug
                  </p>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>
                    {selectedStore.slug}
                  </p>
                </div>
                <div>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Color de marca
                  </p>
                  <div className="mt-1 flex items-center gap-3">
                    <span
                      className="h-5 w-5 rounded-full border"
                      style={{
                        background: selectedStore.primary_color,
                        borderColor: colors2000s.border.default
                      }}
                    />
                    <span className="font-black" style={{ color: colors2000s.text.primary }}>
                      {selectedStore.primary_color}
                    </span>
                  </div>
                </div>
                <div>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    SLA booking
                  </p>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>
                    {overview?.store.cancellation_hours ?? selectedStore.cancellation_hours}h
                    cancel. / {overview?.store.buffer_minutes ?? selectedStore.buffer_minutes}m
                    buffer
                  </p>
                </div>
                <div>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Suscripcion
                  </p>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>
                    {selectedStore.current_plan_name || 'Sin suscripcion'}
                  </p>
                </div>
              </div>

              <div
                className="rounded-2xl px-4 py-3"
                style={{ ...scopeBadgeStyle('danger'), boxShadow: colors2000s.shadows.outer }}
              >
                <p className="text-[10px] font-black uppercase tracking-widest">Protecciones</p>
                <p className="mt-1 text-[11px] font-bold">
                  Revocar Super Admin, desactivar tienda, reemplazar suscripcion y canjear cupon
                  tienen confirmacion y reglas de backend.
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
              <Building2 className="mx-auto mb-3 h-10 w-10 opacity-30" />
              <p
                className="text-sm font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.primary }}
              >
                No hay tienda seleccionada
              </p>
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_420px]">
        <div className="space-y-6">
          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                    style={scopeBadgeStyle('global')}
                  >
                    Tiendas
                  </span>
                </div>
                <h2
                  className="text-2xl font-black uppercase tracking-tight"
                  style={{ color: colors2000s.text.primary }}
                >
                  Operacion por tenant
                </h2>
                <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                  Filtros directos por estado y suscripcion para triage operativo rapido.
                </p>
              </div>

              <div className="flex flex-col gap-3 md:flex-row md:items-center">
                <div className="relative">
                  <Search
                    className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2"
                    style={{ color: colors2000s.text.disabled }}
                  />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Buscar por nombre o slug"
                    className="w-full rounded-2xl py-3 pl-11 pr-4 text-sm font-bold outline-none md:w-72"
                    style={create2000sInputStyle()}
                  />
                </div>

                <div className="flex items-center gap-2 rounded-2xl p-2" style={innerCardStyle}>
                  <Filter className="h-4 w-4" style={{ color: colors2000s.text.secondary }} />
                  {[
                    { value: 'active', label: 'Activas' },
                    { value: 'inactive', label: 'Inactivas' },
                    { value: 'all', label: 'Todas' }
                  ].map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setActivityFilter(item.value as ActivityFilter)}
                      className="rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                      style={
                        activityFilter === item.value
                          ? buttonStyles2000s.selected
                          : buttonStyles2000s.default
                      }
                    >
                      {item.label}
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-2 rounded-2xl p-2" style={innerCardStyle}>
                  {[
                    { value: 'all', label: 'Todas' },
                    { value: 'with', label: 'Con suscripcion' },
                    { value: 'without', label: 'Sin suscripcion' }
                  ].map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setSubscriptionFilter(item.value as SubscriptionFilter)}
                      className="rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                      style={
                        subscriptionFilter === item.value
                          ? buttonStyles2000s.selected
                          : buttonStyles2000s.default
                      }
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-6 overflow-hidden rounded-[1.75rem]" style={innerCardStyle}>
              {storesQuery.isLoading ? (
                <div
                  className="flex items-center justify-center gap-3 p-10"
                  style={{ color: colors2000s.text.secondary }}
                >
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span className="font-bold">Cargando tiendas...</span>
                </div>
              ) : storesQuery.data?.length ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left">
                    <thead style={{ background: colors2000s.bg.disabled }}>
                      <tr>
                        {[
                          'Tienda',
                          'Estado',
                          'Recordatorios',
                          'Usuarios',
                          'Suscripcion',
                          'Renueva',
                          'Acciones'
                        ].map((label) => (
                          <th
                            key={label}
                            className="px-4 py-3 text-[10px] font-black uppercase tracking-widest"
                            style={{ color: colors2000s.text.secondary }}
                          >
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {storesQuery.data.map((store) => {
                        const isSelected = store.public_id === selectedStoreId
                        return (
                          <tr
                            key={store.public_id}
                            onClick={() => setSelectedStoreId(store.public_id)}
                            className="cursor-pointer transition-colors"
                            style={{
                              background: isSelected ? '#fff7ed' : 'transparent',
                              borderTop: `1px solid ${colors2000s.border.light}`
                            }}
                          >
                            <td className="px-4 py-4">
                              <div className="flex items-center gap-3">
                                <span
                                  className="h-4 w-4 rounded-full border"
                                  style={{
                                    background: store.primary_color,
                                    borderColor: colors2000s.border.default
                                  }}
                                />
                                <div>
                                  <p
                                    className="font-black"
                                    style={{ color: colors2000s.text.primary }}
                                  >
                                    {store.name}
                                  </p>
                                  <p
                                    className="text-[10px] font-bold uppercase tracking-widest"
                                    style={{ color: colors2000s.text.secondary }}
                                  >
                                    {store.slug}
                                  </p>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-4">
                              <span
                                className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                                style={
                                  store.is_active
                                    ? scopeBadgeStyle('tenant')
                                    : scopeBadgeStyle('danger')
                                }
                              >
                                {statusLabel(store.is_active)}
                              </span>
                            </td>
                            <td
                              className="px-4 py-4 text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              <div>
                                Confirmacion:{' '}
                                <span style={{ color: colors2000s.text.primary }}>
                                  {store.send_email_confirmation ? 'On' : 'Off'}
                                </span>
                              </div>
                              <div className="mt-1">
                                Reminders:{' '}
                                <span style={{ color: colors2000s.text.primary }}>
                                  {store.send_email_reminders ? 'On' : 'Off'}
                                </span>
                              </div>
                            </td>
                            <td className="px-4 py-4">
                              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                                {store.active_users_count}/{store.users_count}
                              </p>
                              <p
                                className="text-[10px] font-bold uppercase tracking-widest"
                                style={{ color: colors2000s.text.secondary }}
                              >
                                {store.admins_count} admins
                              </p>
                            </td>
                            <td className="px-4 py-4">
                              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                                {store.current_plan_name || 'Sin plan'}
                              </p>
                              <p
                                className="text-[10px] font-bold uppercase tracking-widest"
                                style={{ color: colors2000s.text.secondary }}
                              >
                                {store.subscription_status || 'Sin suscripcion'}
                              </p>
                            </td>
                            <td
                              className="px-4 py-4 text-sm font-bold"
                              style={{ color: colors2000s.text.primary }}
                            >
                              {formatDateEsAr(store.current_period_end)}
                            </td>
                            <td className="px-4 py-4">
                              <div className="flex flex-wrap gap-2">
                                <MiniButton
                                  label="Ver"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setSelectedStoreId(store.public_id)
                                  }}
                                />
                                <MiniButton
                                  label="Editar"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setSelectedStoreId(store.public_id)
                                    openEditStoreFor(store)
                                  }}
                                  tone="primary"
                                />
                                <MiniButton
                                  label={store.is_active ? 'Desactivar' : 'Activar'}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    void toggleStoreActive(store)
                                  }}
                                  tone={store.is_active ? 'danger' : 'default'}
                                />
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="rounded-[1.5rem] p-10 text-center" style={emptyStateStyle}>
                  <Building2 className="mx-auto mb-3 h-10 w-10 opacity-25" />
                  <p
                    className="text-sm font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.primary }}
                  >
                    No hay tiendas para este filtro
                  </p>
                  <p
                    className="mt-2 text-xs font-bold"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Ajusta busqueda, estado o suscripcion para recuperar resultados.
                  </p>
                </div>
              )}
            </div>
          </section>

          <div className="grid gap-6 xl:grid-cols-2">
            <section className="rounded-[2rem] p-6" style={panelStyle}>
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <span
                    className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                    style={scopeBadgeStyle('global')}
                  >
                    Planes
                  </span>
                  <h2
                    className="mt-2 text-xl font-black uppercase tracking-tight"
                    style={{ color: colors2000s.text.primary }}
                  >
                    Catalogo global
                  </h2>
                </div>
                <ActionButton label="Crear plan" onClick={openCreatePlanModal} tone="primary" />
              </div>

              <div className="space-y-3">
                {plansQuery.data?.map((plan) => (
                  <div key={plan.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-black" style={{ color: colors2000s.text.primary }}>
                          {plan.name}
                        </p>
                        <p
                          className="text-[10px] font-bold uppercase tracking-widest"
                          style={{ color: colors2000s.text.secondary }}
                        >
                          {plan.billing_interval} · {formatCurrencyEsAr(plan.price, plan.currency)}
                        </p>
                      </div>
                      <span
                        className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                        style={
                          plan.is_active ? scopeBadgeStyle('global') : scopeBadgeStyle('danger')
                        }
                      >
                        {plan.is_active ? 'Activo' : 'Inactivo'}
                      </span>
                    </div>

                    <div
                      className="mt-4 grid grid-cols-3 gap-3 text-[10px] font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      <div>
                        Max staff:{' '}
                        <span style={{ color: colors2000s.text.primary }}>
                          {plan.max_staff ?? 'Libre'}
                        </span>
                      </div>
                      <div>
                        Max services:{' '}
                        <span style={{ color: colors2000s.text.primary }}>
                          {plan.max_services ?? 'Libre'}
                        </span>
                      </div>
                      <div>
                        Ciclo:{' '}
                        <span style={{ color: colors2000s.text.primary }}>
                          {plan.billing_interval}
                        </span>
                      </div>
                    </div>

                    {plan.description ? (
                      <p
                        className="mt-4 text-xs font-bold"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        {plan.description}
                      </p>
                    ) : null}

                    <div className="mt-4 flex flex-wrap gap-2">
                      <MiniButton
                        label="Editar"
                        onClick={(event) => {
                          event.stopPropagation()
                          openEditPlanModal(plan)
                        }}
                        tone="primary"
                      />
                      <MiniButton
                        label={plan.is_active ? 'Desactivar' : 'Activar'}
                        onClick={(event) => {
                          event.stopPropagation()
                          void togglePlanActive(plan)
                        }}
                        tone={plan.is_active ? 'danger' : 'default'}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-[2rem] p-6" style={panelStyle}>
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <span
                    className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                    style={scopeBadgeStyle('global')}
                  >
                    Cupones
                  </span>
                  <h2
                    className="mt-2 text-xl font-black uppercase tracking-tight"
                    style={{ color: colors2000s.text.primary }}
                  >
                    Maestro editable
                  </h2>
                </div>
                <ActionButton label="Crear cupon" onClick={openCreateCouponModal} tone="primary" />
              </div>

              <div className="space-y-3">
                {couponsQuery.data?.length ? (
                  couponsQuery.data.map((coupon) => {
                    const expired = isCouponExpired(coupon)
                    const exhausted = isCouponExhausted(coupon)
                    return (
                      <div
                        key={coupon.public_id}
                        className="rounded-[1.5rem] p-4"
                        style={innerCardStyle}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-black" style={{ color: colors2000s.text.primary }}>
                              {coupon.code}
                            </p>
                            <p
                              className="text-[10px] font-bold uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              {coupon.coupon_type} ·{' '}
                              {coupon.coupon_type === 'percent'
                                ? `${coupon.value}%`
                                : formatCurrencyEsAr(coupon.value, coupon.currency || 'ARS')}
                            </p>
                          </div>
                          <span
                            className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                            style={
                              coupon.is_active
                                ? scopeBadgeStyle('global')
                                : scopeBadgeStyle('danger')
                            }
                          >
                            {coupon.current_uses}
                            {coupon.max_uses ? `/${coupon.max_uses}` : ''} usos
                          </span>
                        </div>

                        <div
                          className="mt-4 grid grid-cols-2 gap-3 text-[10px] font-black uppercase tracking-widest"
                          style={{ color: colors2000s.text.secondary }}
                        >
                          <div>
                            Vigencia:{' '}
                            <span style={{ color: colors2000s.text.primary }}>
                              {formatDateEsAr(coupon.valid_from)} a{' '}
                              {formatDateEsAr(coupon.valid_until)}
                            </span>
                          </div>
                          <div>
                            Canje unico:{' '}
                            <span style={{ color: colors2000s.text.primary }}>
                              {coupon.one_time_per_store ? 'Si' : 'No'}
                            </span>
                          </div>
                        </div>

                        {coupon.description ? (
                          <p
                            className="mt-3 text-xs font-bold"
                            style={{ color: colors2000s.text.secondary }}
                          >
                            {coupon.description}
                          </p>
                        ) : null}

                        {expired || exhausted ? (
                          <div
                            className="mt-4 rounded-2xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                            style={scopeBadgeStyle('danger')}
                          >
                            {expired ? 'Cupon expirado' : 'Maximo de usos alcanzado'}
                          </div>
                        ) : null}

                        <div className="mt-4 flex flex-wrap gap-2">
                          <MiniButton
                            label="Editar"
                            onClick={(event) => {
                              event.stopPropagation()
                              openEditCouponModal(coupon)
                            }}
                            tone="primary"
                          />
                          <MiniButton
                            label={coupon.is_active ? 'Desactivar' : 'Activar'}
                            onClick={(event) => {
                              event.stopPropagation()
                              void toggleCouponActive(coupon)
                            }}
                            tone={coupon.is_active ? 'danger' : 'default'}
                          />
                        </div>
                      </div>
                    )
                  })
                ) : (
                  <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                    <Tag className="mx-auto mb-3 h-10 w-10 opacity-25" />
                    <p
                      className="text-sm font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.primary }}
                    >
                      No hay cupones todavia
                    </p>
                    <p
                      className="mt-2 text-xs font-bold"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      Crea el primer cupon global para empezar a operar descuentos.
                    </p>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>

        <aside className="space-y-6 xl:sticky xl:top-8 xl:self-start">
          <SuperAdminHealthPanel
            selectedStore={selectedStore}
            overview={overview}
            onCreateAdmin={openCreateAdminModal}
            onAssignPlan={openAssignPlanModal}
            onRedeemCoupon={openRedeemCouponModal}
            onEditStore={openEditStoreModal}
            activePlansCount={activePlans.length}
            activeCouponsCount={activeCoupons.length}
          />

          <SuperAdminAuditTimeline
            entries={auditQuery.data}
            isLoading={auditQuery.isLoading || auditQuery.isFetching}
          />

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="mb-4 flex items-center justify-between">
              <div>
                <span
                  className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                  style={scopeBadgeStyle('tenant')}
                >
                  Admins y Usuarios
                </span>
                <h2
                  className="mt-2 text-xl font-black uppercase tracking-tight"
                  style={{ color: colors2000s.text.primary }}
                >
                  Detalle del tenant
                </h2>
              </div>
              {overviewQuery.isFetching ? (
                <Loader2
                  className="h-4 w-4 animate-spin"
                  style={{ color: colors2000s.orange.accent }}
                />
              ) : null}
            </div>

            {!overview && overviewQuery.isLoading ? (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin" />
                <p
                  className="text-sm font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.primary }}
                >
                  Cargando contexto
                </p>
              </div>
            ) : overview ? (
              <div className="space-y-4">
                {!selectedStore?.is_active ? (
                  <div
                    className="rounded-[1.5rem] px-4 py-3 text-xs font-bold"
                    style={scopeBadgeStyle('danger')}
                  >
                    Contexto de tienda inactiva. Crear admins, asignar planes y canjear cupones
                    puede quedar bloqueado por reglas de backend.
                  </div>
                ) : null}

                <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                  <div className="mb-3 flex items-center gap-2">
                    <Shield className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
                    <p
                      className="text-[10px] font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      Admins
                    </p>
                  </div>
                  {overview.users.admins.length ? (
                    <div className="space-y-3">
                      {overview.users.admins.map((admin) => (
                        <div
                          key={admin.public_id}
                          className="rounded-2xl p-3"
                          style={{ background: colors2000s.bg.button }}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                                {[admin.first_name, admin.last_name].filter(Boolean).join(' ') ||
                                  admin.email}
                              </p>
                              <p
                                className="text-[10px] font-bold uppercase tracking-widest"
                                style={{ color: colors2000s.text.secondary }}
                              >
                                {admin.email}
                              </p>
                            </div>
                            <span
                              className="rounded-full px-2 py-1 text-[10px] font-black uppercase tracking-widest"
                              style={
                                admin.is_global_admin
                                  ? scopeBadgeStyle('danger')
                                  : scopeBadgeStyle('tenant')
                              }
                            >
                              {roleLabel(admin.role, admin.is_global_admin)}
                            </span>
                          </div>

                          <div className="mt-3 flex flex-wrap gap-2">
                            <MiniButton
                              label="Editar"
                              onClick={(event) => {
                                event.stopPropagation()
                                openEditUserModal(admin)
                              }}
                              tone="primary"
                            />
                            <MiniButton
                              label={admin.is_active ? 'Desactivar' : 'Activar'}
                              onClick={(event) => {
                                event.stopPropagation()
                                void toggleUserActive(admin)
                              }}
                              tone={admin.is_active ? 'danger' : 'default'}
                            />
                            <MiniButton
                              label={
                                admin.is_global_admin ? 'Revocar SuperAdmin' : 'Promover SuperAdmin'
                              }
                              onClick={(event) => {
                                event.stopPropagation()
                                void toggleGlobalAdmin(admin)
                              }}
                              tone={admin.is_global_admin ? 'danger' : 'default'}
                              disabled={!admin.is_global_admin && !admin.is_active}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-[1.25rem] p-6 text-center" style={emptyStateStyle}>
                      <Shield className="mx-auto mb-3 h-8 w-8 opacity-25" />
                      <p
                        className="text-sm font-black uppercase tracking-widest"
                        style={{ color: colors2000s.text.primary }}
                      >
                        No hay admins creados
                      </p>
                    </div>
                  )}
                </div>

                <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                  <div className="mb-3 flex items-center gap-2">
                    <Users className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
                    <p
                      className="text-[10px] font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      Usuarios
                    </p>
                  </div>
                  <div className="mb-3 grid grid-cols-3 gap-2 text-center">
                    {[
                      { label: 'Admins', value: overview.users.admins_count },
                      { label: 'Usuarios', value: overview.users.users_count },
                      { label: 'Activos', value: overview.users.active_users_count }
                    ].map((item) => (
                      <div
                        key={item.label}
                        className="rounded-2xl p-3"
                        style={{ background: colors2000s.bg.button }}
                      >
                        <p
                          className="text-lg font-black"
                          style={{ color: colors2000s.text.primary }}
                        >
                          {item.value}
                        </p>
                        <p
                          className="text-[10px] font-black uppercase tracking-widest"
                          style={{ color: colors2000s.text.secondary }}
                        >
                          {item.label}
                        </p>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    {overview.users.users.length ? (
                      overview.users.users.map((tenantUser) => (
                        <div
                          key={tenantUser.public_id}
                          className="rounded-2xl px-3 py-3"
                          style={{ background: colors2000s.bg.button }}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p
                                className="text-sm font-black"
                                style={{ color: colors2000s.text.primary }}
                              >
                                {[tenantUser.first_name, tenantUser.last_name]
                                  .filter(Boolean)
                                  .join(' ') || tenantUser.email}
                              </p>
                              <p
                                className="text-[10px] font-bold uppercase tracking-widest"
                                style={{ color: colors2000s.text.secondary }}
                              >
                                {roleLabel(tenantUser.role, tenantUser.is_global_admin)}
                              </p>
                            </div>
                            {tenantUser.is_global_admin ? (
                              <BadgeCheck className="h-4 w-4" style={{ color: '#be123c' }} />
                            ) : (
                              <span
                                className="text-[10px] font-black uppercase tracking-widest"
                                style={{ color: tenantUser.is_active ? '#15803d' : '#b91c1c' }}
                              >
                                {tenantUser.is_active ? 'Activo' : 'Inactivo'}
                              </span>
                            )}
                          </div>

                          <div className="mt-3 flex flex-wrap gap-2">
                            <MiniButton
                              label="Editar"
                              onClick={(event) => {
                                event.stopPropagation()
                                openEditUserModal(tenantUser)
                              }}
                              tone="primary"
                            />
                            <MiniButton
                              label={tenantUser.is_active ? 'Desactivar' : 'Activar'}
                              onClick={(event) => {
                                event.stopPropagation()
                                void toggleUserActive(tenantUser)
                              }}
                              tone={tenantUser.is_active ? 'danger' : 'default'}
                            />
                            <MiniButton
                              label={
                                tenantUser.is_global_admin
                                  ? 'Revocar SuperAdmin'
                                  : 'Promover SuperAdmin'
                              }
                              onClick={(event) => {
                                event.stopPropagation()
                                void toggleGlobalAdmin(tenantUser)
                              }}
                              tone={tenantUser.is_global_admin ? 'danger' : 'default'}
                            />
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-[1.25rem] p-6 text-center" style={emptyStateStyle}>
                        <Users className="mx-auto mb-3 h-8 w-8 opacity-25" />
                        <p
                          className="text-sm font-black uppercase tracking-widest"
                          style={{ color: colors2000s.text.primary }}
                        >
                          No hay usuarios del tenant
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <Users className="mx-auto mb-3 h-10 w-10 opacity-25" />
                <p
                  className="text-sm font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.primary }}
                >
                  Selecciona una tienda
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <CreditCard className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
                <span
                  className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                  style={scopeBadgeStyle('tenant')}
                >
                  Suscripcion
                </span>
              </div>
              <ActionButton
                label={overview?.subscription ? 'Reasignar plan' : 'Asignar plan'}
                onClick={openAssignPlanModal}
                disabled={!selectedStore || !activePlans.length}
              />
            </div>
            {overview?.subscription ? (
              <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-black" style={{ color: colors2000s.text.primary }}>
                      {overview.subscription.plan_name || 'Plan sin nombre'}
                    </p>
                    <p
                      className="text-[10px] font-bold uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      {overview.subscription.status} · {overview.subscription.billing_interval}
                    </p>
                  </div>
                  <span
                    className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                    style={scopeBadgeStyle('tenant')}
                  >
                    {formatCurrencyEsAr(
                      overview.subscription.total_amount,
                      overview.subscription.currency
                    )}
                  </span>
                </div>
                <div
                  className="mt-4 grid grid-cols-2 gap-3 text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  <div>
                    Base:{' '}
                    <span style={{ color: colors2000s.text.primary }}>
                      {formatCurrencyEsAr(
                        overview.subscription.base_amount,
                        overview.subscription.currency
                      )}
                    </span>
                  </div>
                  <div>
                    Descuento:{' '}
                    <span style={{ color: colors2000s.text.primary }}>
                      {formatCurrencyEsAr(
                        overview.subscription.discount_amount,
                        overview.subscription.currency
                      )}
                    </span>
                  </div>
                  <div>
                    Max staff:{' '}
                    <span style={{ color: colors2000s.text.primary }}>
                      {overview.subscription.max_staff ?? 'Libre'}
                    </span>
                  </div>
                  <div>
                    Max services:{' '}
                    <span style={{ color: colors2000s.text.primary }}>
                      {overview.subscription.max_services ?? 'Libre'}
                    </span>
                  </div>
                  <div>
                    Inicio:{' '}
                    <span style={{ color: colors2000s.text.primary }}>
                      {formatDateEsAr(overview.subscription.current_period_start)}
                    </span>
                  </div>
                  <div>
                    Fin:{' '}
                    <span style={{ color: colors2000s.text.primary }}>
                      {formatDateEsAr(overview.subscription.current_period_end)}
                    </span>
                  </div>
                </div>
                <div className="mt-4 rounded-2xl p-3" style={{ background: colors2000s.bg.button }}>
                  <p
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Cupon aplicado
                  </p>
                  <p className="mt-1 font-black" style={{ color: colors2000s.text.primary }}>
                    {overview.subscription.applied_coupon?.code || 'Sin cupon aplicado'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <CreditCard className="mx-auto mb-3 h-10 w-10 opacity-25" />
                <p
                  className="text-sm font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.primary }}
                >
                  Esta tienda no tiene suscripcion
                </p>
                <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                  Asigna un plan para habilitar billing y canjes sobre el tenant.
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Tag className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
                <span
                  className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                  style={scopeBadgeStyle('tenant')}
                >
                  Canjes
                </span>
              </div>
              <ActionButton
                label="Canjear cupon"
                onClick={openRedeemCouponModal}
                disabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
              />
            </div>
            {overview?.recent_redemptions.length ? (
              <div className="space-y-3">
                {overview.recent_redemptions.map((redemption) => (
                  <div
                    key={redemption.public_id}
                    className="rounded-[1.5rem] p-4"
                    style={innerCardStyle}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-black" style={{ color: colors2000s.text.primary }}>
                          {redemption.code_snapshot}
                        </p>
                        <p
                          className="text-[10px] font-bold uppercase tracking-widest"
                          style={{ color: colors2000s.text.secondary }}
                        >
                          {redemption.coupon_type_snapshot} ·{' '}
                          {formatDateTimeEsAr(redemption.created_at)}
                        </p>
                      </div>
                      <span
                        className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                        style={scopeBadgeStyle('tenant')}
                      >
                        -{formatCurrencyEsAr(redemption.discount_amount, redemption.currency)}
                      </span>
                    </div>
                    <p
                      className="mt-3 text-[10px] font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      Final:{' '}
                      <span style={{ color: colors2000s.text.primary }}>
                        {formatCurrencyEsAr(redemption.final_amount, redemption.currency)}
                      </span>
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <Tag className="mx-auto mb-3 h-10 w-10 opacity-25" />
                <p
                  className="text-sm font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.primary }}
                >
                  No hay canjes recientes
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div
              className="flex items-start gap-3 rounded-[1.5rem] p-4"
              style={{ ...scopeBadgeStyle('danger'), boxShadow: colors2000s.shadows.outer }}
            >
              <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0" />
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest">
                  Estados sensibles
                </p>
                <p className="mt-2 text-xs font-bold">
                  La UI diferencia acciones globales, acciones sobre tienda seleccionada y
                  operaciones delicadas para evitar errores de tenant.
                </p>
              </div>
            </div>
          </section>
        </aside>
      </div>

      <SuperAdminFormModal
        isOpen={modal === 'create-store' || modal === 'edit-store'}
        onClose={closeModal}
        onSubmit={handleStoreSubmit}
        title={modal === 'create-store' ? 'Crear tienda' : 'Editar tienda'}
        subtitle="Define identidad del tenant, reglas de operacion y notificaciones base."
        submitLabel={modal === 'create-store' ? 'Crear tienda' : 'Guardar tienda'}
        loading={createStoreMutation.isPending || updateStoreMutation.isPending}
        error={modalError}
      >
        <div className={formGridClass}>
          <div>
            <FieldLabel>Nombre</FieldLabel>
            <TextInput
              value={storeForm.name}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, name: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Slug</FieldLabel>
            <TextInput
              value={storeForm.slug}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, slug: event.target.value }))
              }
              required
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Color principal</FieldLabel>
            <div className="flex gap-3">
              <TextInput
                type="color"
                value={storeForm.primary_color}
                onChange={(event) =>
                  setStoreForm((current) => ({ ...current, primary_color: event.target.value }))
                }
                className="h-12 w-20 p-2"
              />
              <TextInput
                value={storeForm.primary_color}
                onChange={(event) =>
                  setStoreForm((current) => ({ ...current, primary_color: event.target.value }))
                }
              />
            </div>
          </div>
          <div>
            <FieldLabel>Logo URL</FieldLabel>
            <TextInput
              value={storeForm.logo_url}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, logo_url: event.target.value }))
              }
              placeholder="https://..."
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Horas de cancelacion</FieldLabel>
            <TextInput
              type="number"
              min="0"
              value={storeForm.cancellation_hours}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, cancellation_hours: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Buffer (minutos)</FieldLabel>
            <TextInput
              type="number"
              min="0"
              value={storeForm.buffer_minutes}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, buffer_minutes: event.target.value }))
              }
              required
            />
          </div>
        </div>

        <div className="grid gap-3">
          <ToggleRow
            label="Confirmaciones por email"
            description="Controla si el tenant envia confirmacion de reserva."
            checked={storeForm.send_email_confirmation}
            onToggle={() =>
              setStoreForm((current) => ({
                ...current,
                send_email_confirmation: !current.send_email_confirmation
              }))
            }
          />
          <ToggleRow
            label="Recordatorios por email"
            description="Controla si el tenant envia recordatorios automaticos."
            checked={storeForm.send_email_reminders}
            onToggle={() =>
              setStoreForm((current) => ({
                ...current,
                send_email_reminders: !current.send_email_reminders
              }))
            }
          />
          {modal === 'edit-store' ? (
            <ToggleRow
              label="Tienda activa"
              description="Desactivar bloquea el contexto operativo del tenant."
              checked={storeForm.is_active}
              onToggle={() =>
                setStoreForm((current) => ({ ...current, is_active: !current.is_active }))
              }
            />
          ) : null}
        </div>
      </SuperAdminFormModal>

      <SuperAdminFormModal
        isOpen={modal === 'create-admin'}
        onClose={closeModal}
        onSubmit={handleAdminSubmit}
        title="Crear admin"
        subtitle={
          selectedStore ? `Nuevo admin para ${selectedStore.name}` : 'Nuevo admin de tienda'
        }
        submitLabel="Crear admin"
        loading={createAdminMutation.isPending}
        error={modalError}
      >
        <div className={formGridClass}>
          <div>
            <FieldLabel>Nombre</FieldLabel>
            <TextInput
              value={adminForm.first_name}
              onChange={(event) =>
                setAdminForm((current) => ({ ...current, first_name: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Apellido</FieldLabel>
            <TextInput
              value={adminForm.last_name}
              onChange={(event) =>
                setAdminForm((current) => ({ ...current, last_name: event.target.value }))
              }
              required
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Email</FieldLabel>
            <TextInput
              type="email"
              value={adminForm.email}
              onChange={(event) =>
                setAdminForm((current) => ({ ...current, email: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Telefono</FieldLabel>
            <TextInput
              value={adminForm.phone}
              onChange={(event) =>
                setAdminForm((current) => ({ ...current, phone: event.target.value }))
              }
            />
          </div>
        </div>

        <div>
          <FieldLabel>Password</FieldLabel>
          <TextInput
            type="password"
            value={adminForm.password}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, password: event.target.value }))
            }
            minLength={8}
            required
          />
        </div>
      </SuperAdminFormModal>

      <SuperAdminFormModal
        isOpen={modal === 'edit-user'}
        onClose={closeModal}
        onSubmit={handleUserSubmit}
        title="Editar usuario"
        subtitle="Actualiza rol, datos de contacto y estado del usuario seleccionado."
        submitLabel="Guardar usuario"
        loading={updateUserMutation.isPending}
        error={modalError}
      >
        <div
          className="rounded-2xl px-4 py-3 text-xs font-bold"
          style={{ ...innerCardStyle, color: colors2000s.text.secondary }}
        >
          Email de acceso:{' '}
          <span style={{ color: colors2000s.text.primary }}>{userForm.email || 'Sin email'}</span>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Nombre</FieldLabel>
            <TextInput
              value={userForm.first_name}
              onChange={(event) =>
                setUserForm((current) => ({ ...current, first_name: event.target.value }))
              }
            />
          </div>
          <div>
            <FieldLabel>Apellido</FieldLabel>
            <TextInput
              value={userForm.last_name}
              onChange={(event) =>
                setUserForm((current) => ({ ...current, last_name: event.target.value }))
              }
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Rol</FieldLabel>
            <SelectInput
              value={userForm.role}
              onChange={(event) =>
                setUserForm((current) => ({
                  ...current,
                  role: event.target.value as UserFormState['role']
                }))
              }
            >
              <option value="admin">Admin</option>
              <option value="staff">Profesional</option>
              <option value="receptionist">Recepcion</option>
              <option value="client">Cliente</option>
            </SelectInput>
          </div>
          <div>
            <FieldLabel>Telefono</FieldLabel>
            <TextInput
              value={userForm.phone}
              onChange={(event) =>
                setUserForm((current) => ({ ...current, phone: event.target.value }))
              }
            />
          </div>
        </div>

        <div>
          <FieldLabel>Nueva password (opcional)</FieldLabel>
          <TextInput
            type="password"
            value={userForm.password}
            onChange={(event) =>
              setUserForm((current) => ({ ...current, password: event.target.value }))
            }
            minLength={8}
          />
        </div>

        <ToggleRow
          label="Usuario activo"
          description="Mantiene o revoca su acceso dentro del tenant."
          checked={userForm.is_active}
          onToggle={() => setUserForm((current) => ({ ...current, is_active: !current.is_active }))}
        />
      </SuperAdminFormModal>

      <SuperAdminFormModal
        isOpen={modal === 'create-plan' || modal === 'edit-plan'}
        onClose={closeModal}
        onSubmit={handlePlanSubmit}
        title={modal === 'create-plan' ? 'Crear plan' : 'Editar plan'}
        subtitle="Gestiona nombre, precio, limites operativos y estado comercial."
        submitLabel={modal === 'create-plan' ? 'Crear plan' : 'Guardar plan'}
        loading={createPlanMutation.isPending || updatePlanMutation.isPending}
        error={modalError}
      >
        <div className={formGridClass}>
          <div>
            <FieldLabel>Nombre</FieldLabel>
            <TextInput
              value={planForm.name}
              onChange={(event) =>
                setPlanForm((current) => ({ ...current, name: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Intervalo</FieldLabel>
            <SelectInput
              value={planForm.billing_interval}
              onChange={(event) =>
                setPlanForm((current) => ({ ...current, billing_interval: event.target.value }))
              }
            >
              <option value="monthly">Mensual</option>
              <option value="quarterly">Trimestral</option>
              <option value="yearly">Anual</option>
              <option value="custom">Personalizado</option>
            </SelectInput>
          </div>
        </div>

        <div>
          <FieldLabel>Descripcion</FieldLabel>
          <TextArea
            value={planForm.description}
            onChange={(event) =>
              setPlanForm((current) => ({ ...current, description: event.target.value }))
            }
          />
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Precio</FieldLabel>
            <TextInput
              type="number"
              min="0"
              step="0.01"
              value={planForm.price}
              onChange={(event) =>
                setPlanForm((current) => ({ ...current, price: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Moneda</FieldLabel>
            <TextInput
              value={planForm.currency}
              onChange={(event) =>
                setPlanForm((current) => ({
                  ...current,
                  currency: event.target.value.toUpperCase()
                }))
              }
              required
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Max staff</FieldLabel>
            <TextInput
              type="number"
              min="0"
              value={planForm.max_staff}
              onChange={(event) =>
                setPlanForm((current) => ({ ...current, max_staff: event.target.value }))
              }
              placeholder="Libre"
            />
          </div>
          <div>
            <FieldLabel>Max services</FieldLabel>
            <TextInput
              type="number"
              min="0"
              value={planForm.max_services}
              onChange={(event) =>
                setPlanForm((current) => ({ ...current, max_services: event.target.value }))
              }
              placeholder="Libre"
            />
          </div>
        </div>

        {modal === 'edit-plan' ? (
          <ToggleRow
            label="Plan activo"
            description="Define si puede asignarse a nuevas tiendas."
            checked={planForm.is_active}
            onToggle={() =>
              setPlanForm((current) => ({ ...current, is_active: !current.is_active }))
            }
          />
        ) : null}
      </SuperAdminFormModal>

      <SuperAdminFormModal
        isOpen={modal === 'assign-plan'}
        onClose={closeModal}
        onSubmit={handleSubscriptionSubmit}
        title="Asignar plan"
        subtitle={selectedStore ? `Suscripcion de ${selectedStore.name}` : 'Suscripcion por tienda'}
        submitLabel="Guardar suscripcion"
        loading={assignSubscriptionMutation.isPending}
        error={modalError}
        submitDisabled={selectedStoreUnavailable || !activePlans.length}
      >
        {selectedStoreUnavailable ? (
          <div
            className="rounded-2xl px-4 py-3 text-xs font-bold"
            style={scopeBadgeStyle('danger')}
          >
            La tienda esta inactiva. El backend puede rechazar nuevas suscripciones hasta
            reactivarla.
          </div>
        ) : null}

        <div className={formGridClass}>
          <div>
            <FieldLabel>Plan</FieldLabel>
            <SelectInput
              value={subscriptionForm.plan_id}
              onChange={(event) =>
                setSubscriptionForm((current) => ({ ...current, plan_id: event.target.value }))
              }
              required
            >
              <option value="">Selecciona un plan</option>
              {activePlans.map((plan) => (
                <option key={plan.public_id} value={plan.public_id}>
                  {plan.name} · {formatCurrencyEsAr(plan.price, plan.currency)}
                </option>
              ))}
            </SelectInput>
          </div>
          <div>
            <FieldLabel>Status</FieldLabel>
            <SelectInput
              value={subscriptionForm.status}
              onChange={(event) =>
                setSubscriptionForm((current) => ({ ...current, status: event.target.value }))
              }
            >
              <option value="active">Activa</option>
              <option value="trialing">Prueba</option>
              <option value="past_due">Pago vencido</option>
              <option value="cancelled">Cancelada</option>
            </SelectInput>
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Monto base</FieldLabel>
            <TextInput
              type="number"
              min="0"
              step="0.01"
              value={subscriptionForm.base_amount}
              onChange={(event) =>
                setSubscriptionForm((current) => ({ ...current, base_amount: event.target.value }))
              }
              placeholder="Usa precio del plan si queda vacio"
            />
          </div>
          <div>
            <FieldLabel>Moneda</FieldLabel>
            <TextInput
              value={subscriptionForm.currency}
              onChange={(event) =>
                setSubscriptionForm((current) => ({
                  ...current,
                  currency: event.target.value.toUpperCase()
                }))
              }
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Periodo desde</FieldLabel>
            <TextInput
              type="datetime-local"
              value={subscriptionForm.current_period_start}
              onChange={(event) =>
                setSubscriptionForm((current) => ({
                  ...current,
                  current_period_start: event.target.value
                }))
              }
            />
          </div>
          <div>
            <FieldLabel>Periodo hasta</FieldLabel>
            <TextInput
              type="datetime-local"
              value={subscriptionForm.current_period_end}
              onChange={(event) =>
                setSubscriptionForm((current) => ({
                  ...current,
                  current_period_end: event.target.value
                }))
              }
            />
          </div>
        </div>
      </SuperAdminFormModal>

      <SuperAdminFormModal
        isOpen={modal === 'create-coupon' || modal === 'edit-coupon'}
        onClose={closeModal}
        onSubmit={handleCouponSubmit}
        title={modal === 'create-coupon' ? 'Crear cupon' : 'Editar cupon'}
        subtitle="Gestiona valor, vigencia, cupo y reglas de canje global."
        submitLabel={modal === 'create-coupon' ? 'Crear cupon' : 'Guardar cupon'}
        loading={createCouponMutation.isPending || updateCouponMutation.isPending}
        error={modalError}
      >
        <div className={formGridClass}>
          <div>
            <FieldLabel>Codigo</FieldLabel>
            <TextInput
              value={couponForm.code}
              onChange={(event) =>
                setCouponForm((current) => ({ ...current, code: event.target.value.toUpperCase() }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Tipo</FieldLabel>
            <SelectInput
              value={couponForm.coupon_type}
              onChange={(event) =>
                setCouponForm((current) => ({
                  ...current,
                  coupon_type: event.target.value as CouponFormState['coupon_type']
                }))
              }
            >
              <option value="percent">Porcentaje</option>
              <option value="fixed">Monto fijo</option>
            </SelectInput>
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Valor</FieldLabel>
            <TextInput
              type="number"
              min="0"
              step="0.01"
              value={couponForm.value}
              onChange={(event) =>
                setCouponForm((current) => ({ ...current, value: event.target.value }))
              }
              required
            />
          </div>
          <div>
            <FieldLabel>Moneda</FieldLabel>
            <TextInput
              value={couponForm.currency}
              onChange={(event) =>
                setCouponForm((current) => ({
                  ...current,
                  currency: event.target.value.toUpperCase()
                }))
              }
              disabled={couponForm.coupon_type === 'percent'}
            />
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Max usos</FieldLabel>
            <TextInput
              type="number"
              min="1"
              value={couponForm.max_uses}
              onChange={(event) =>
                setCouponForm((current) => ({ ...current, max_uses: event.target.value }))
              }
              placeholder="Sin limite"
            />
          </div>
          <div>
            <FieldLabel>Canje unico por tienda</FieldLabel>
            <SelectInput
              value={couponForm.one_time_per_store ? 'yes' : 'no'}
              onChange={(event) =>
                setCouponForm((current) => ({
                  ...current,
                  one_time_per_store: event.target.value === 'yes'
                }))
              }
            >
              <option value="yes">Si</option>
              <option value="no">No</option>
            </SelectInput>
          </div>
        </div>

        <div className={formGridClass}>
          <div>
            <FieldLabel>Vigente desde</FieldLabel>
            <TextInput
              type="datetime-local"
              value={couponForm.valid_from}
              onChange={(event) =>
                setCouponForm((current) => ({ ...current, valid_from: event.target.value }))
              }
            />
          </div>
          <div>
            <FieldLabel>Vigente hasta</FieldLabel>
            <TextInput
              type="datetime-local"
              value={couponForm.valid_until}
              onChange={(event) =>
                setCouponForm((current) => ({ ...current, valid_until: event.target.value }))
              }
            />
          </div>
        </div>

        <div>
          <FieldLabel>Descripcion</FieldLabel>
          <TextArea
            value={couponForm.description}
            onChange={(event) =>
              setCouponForm((current) => ({ ...current, description: event.target.value }))
            }
          />
        </div>

        {modal === 'edit-coupon' ? (
          <ToggleRow
            label="Cupon activo"
            description="Define si puede seguir canjeandose."
            checked={couponForm.is_active}
            onToggle={() =>
              setCouponForm((current) => ({ ...current, is_active: !current.is_active }))
            }
          />
        ) : null}
      </SuperAdminFormModal>

      <SuperAdminFormModal
        isOpen={modal === 'redeem-coupon'}
        onClose={closeModal}
        onSubmit={handleRedeemSubmit}
        title="Canjear cupon"
        subtitle={
          selectedStore ? `Aplicar descuento a ${selectedStore.name}` : 'Canje sobre tienda'
        }
        submitLabel="Canjear cupon"
        loading={redeemCouponMutation.isPending}
        error={modalError}
        submitDisabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
      >
        {!hasSelectedStoreSubscription ? (
          <div
            className="rounded-2xl px-4 py-3 text-xs font-bold"
            style={scopeBadgeStyle('danger')}
          >
            Esta tienda no tiene suscripcion activa. No se puede canjear un cupon todavia.
          </div>
        ) : null}

        <div>
          <FieldLabel>Cupon</FieldLabel>
          <SelectInput
            value={redeemForm.coupon_code}
            onChange={(event) => setRedeemForm({ coupon_code: event.target.value })}
            required
          >
            <option value="">Selecciona un cupon</option>
            {activeCoupons.map((coupon) => (
              <option key={coupon.public_id} value={coupon.code}>
                {coupon.code} ·{' '}
                {coupon.coupon_type === 'percent'
                  ? `${coupon.value}%`
                  : formatCurrencyEsAr(coupon.value, coupon.currency || 'ARS')}
              </option>
            ))}
          </SelectInput>
        </div>

        <div
          className="rounded-2xl px-4 py-3 text-xs font-bold"
          style={{ ...innerCardStyle, color: colors2000s.text.secondary }}
        >
          El backend valida tienda activa, suscripcion vigente, expiracion del cupon y maximo de
          usos antes de confirmar el canje.
        </div>
      </SuperAdminFormModal>
    </div>
  )
}

export default SuperAdminPage
