import React, { useEffect, useMemo, useState } from 'react'

import { AlertTriangle } from 'lucide-react'

import {
  type SuperAdminCoupon,
  type SuperAdminPlan,
  type SuperAdminStoreRow,
  type SuperAdminUser
} from '@application/services/SuperAdminService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { colors2000s } from '../../theme/colors'
import { SuperAdminAuditTimeline } from '../components/organisms/SuperAdminAuditTimeline'
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
import { CouponModals } from './superadmin/CouponModals'
import { CouponsSection } from './superadmin/CouponsSection'
import { PlanModals } from './superadmin/PlanModals'
import { PlansSection } from './superadmin/PlansSection'
import { RedemptionsSection } from './superadmin/RedemptionsSection'
import {
  type ActivityFilter,
  type FeedbackMessage,
  type SubscriptionFilter,
  type SuperAdminModalKey,
  createEmptyAdminForm,
  createEmptyCouponForm,
  createEmptyPlanForm,
  createEmptyRedeemForm,
  createEmptyStoreForm,
  createEmptySubscriptionForm,
  createEmptyUserForm,
  panelStyle,
  parseOptionalInt,
  scopeBadgeStyle,
  toDateTimeInput,
  type AdminFormState,
  type CouponFormState,
  type PlanFormState,
  type RedeemFormState,
  type StoreFormState,
  type SubscriptionFormState,
  type UserFormState
} from './superadmin/shared'
import { StoreModals } from './superadmin/StoreModals'
import { StoresSection } from './superadmin/StoresSection'
import { SubscriptionSection } from './superadmin/SubscriptionSection'
import { SuperAdminHeader } from './superadmin/SuperAdminHeader'
import { TenantUsersSection } from './superadmin/TenantUsersSection'
import { UserModals } from './superadmin/UserModals'

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
    const selectedExists = storesQuery.data?.some((store) => store.public_id === selectedStoreId)
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

      <SuperAdminHeader
        selectedStore={selectedStore}
        hasSelectedStoreSubscription={hasSelectedStoreSubscription}
        overview={overview}
        activePlans={activePlans}
        activeCoupons={activeCoupons}
        openCreateStoreModal={openCreateStoreModal}
        openEditStoreModal={openEditStoreModal}
        openCreateAdminModal={openCreateAdminModal}
        openAssignPlanModal={openAssignPlanModal}
        openRedeemCouponModal={openRedeemCouponModal}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_420px]">
        <div className="space-y-6">
          <StoresSection
            search={search}
            setSearch={setSearch}
            activityFilter={activityFilter}
            setActivityFilter={setActivityFilter}
            subscriptionFilter={subscriptionFilter}
            setSubscriptionFilter={setSubscriptionFilter}
            selectedStoreId={selectedStoreId}
            setSelectedStoreId={setSelectedStoreId}
            storesQuery={storesQuery}
            openEditStoreFor={openEditStoreFor}
            toggleStoreActive={toggleStoreActive}
          />

          <div className="grid gap-6 xl:grid-cols-2">
            <PlansSection
              plansQuery={plansQuery}
              openCreatePlanModal={openCreatePlanModal}
              openEditPlanModal={openEditPlanModal}
              togglePlanActive={togglePlanActive}
            />

            <CouponsSection
              couponsQuery={couponsQuery}
              openCreateCouponModal={openCreateCouponModal}
              openEditCouponModal={openEditCouponModal}
              toggleCouponActive={toggleCouponActive}
            />
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

          <TenantUsersSection
            selectedStore={selectedStore}
            overview={overview}
            overviewQuery={overviewQuery}
            openEditUserModal={openEditUserModal}
            toggleUserActive={toggleUserActive}
            toggleGlobalAdmin={toggleGlobalAdmin}
          />

          <SubscriptionSection
            selectedStore={selectedStore}
            overview={overview}
            activePlans={activePlans}
            openAssignPlanModal={openAssignPlanModal}
          />

          <RedemptionsSection
            selectedStore={selectedStore}
            hasSelectedStoreSubscription={hasSelectedStoreSubscription}
            overview={overview}
            activeCoupons={activeCoupons}
            openRedeemCouponModal={openRedeemCouponModal}
          />

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

      <StoreModals
        modal={modal}
        closeModal={closeModal}
        modalError={modalError}
        selectedStore={selectedStore}
        storeForm={storeForm}
        setStoreForm={setStoreForm}
        handleStoreSubmit={handleStoreSubmit}
        createStoreMutation={createStoreMutation}
        updateStoreMutation={updateStoreMutation}
        adminForm={adminForm}
        setAdminForm={setAdminForm}
        handleAdminSubmit={handleAdminSubmit}
        createAdminMutation={createAdminMutation}
      />
      <UserModals
        modal={modal}
        closeModal={closeModal}
        modalError={modalError}
        userForm={userForm}
        setUserForm={setUserForm}
        handleUserSubmit={handleUserSubmit}
        updateUserMutation={updateUserMutation}
      />
      <PlanModals
        modal={modal}
        closeModal={closeModal}
        modalError={modalError}
        selectedStore={selectedStore}
        selectedStoreUnavailable={selectedStoreUnavailable}
        activePlans={activePlans}
        planForm={planForm}
        setPlanForm={setPlanForm}
        handlePlanSubmit={handlePlanSubmit}
        createPlanMutation={createPlanMutation}
        updatePlanMutation={updatePlanMutation}
        subscriptionForm={subscriptionForm}
        setSubscriptionForm={setSubscriptionForm}
        handleSubscriptionSubmit={handleSubscriptionSubmit}
        assignSubscriptionMutation={assignSubscriptionMutation}
      />
      <CouponModals
        modal={modal}
        closeModal={closeModal}
        modalError={modalError}
        selectedStore={selectedStore}
        hasSelectedStoreSubscription={hasSelectedStoreSubscription}
        activeCoupons={activeCoupons}
        couponForm={couponForm}
        setCouponForm={setCouponForm}
        handleCouponSubmit={handleCouponSubmit}
        createCouponMutation={createCouponMutation}
        updateCouponMutation={updateCouponMutation}
        redeemForm={redeemForm}
        setRedeemForm={setRedeemForm}
        handleRedeemSubmit={handleRedeemSubmit}
        redeemCouponMutation={redeemCouponMutation}
      />
    </div>
  )
}

export default SuperAdminPage
