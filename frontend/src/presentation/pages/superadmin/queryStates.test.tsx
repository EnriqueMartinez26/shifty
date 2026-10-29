import React from 'react'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type {
  SuperAdminCoupon,
  SuperAdminPlan,
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { CouponsSection } from './CouponsSection'
import { PlansSection } from './PlansSection'
import { RedemptionsSection } from './RedemptionsSection'
import type { QueryState } from './shared'
import { StoresSection } from './StoresSection'
import { SubscriptionSection } from './SubscriptionSection'
import { TenantUsersSection } from './TenantUsersSection'
import { SuperAdminAuditTimeline } from '../../components/organisms/SuperAdminAuditTimeline'

const makeQuery = <T,>(overrides: Partial<QueryState<T>> = {}): QueryState<T> => ({
  data: undefined,
  isLoading: false,
  isFetching: false,
  error: null,
  refetch: jest.fn().mockResolvedValue(undefined),
  ...overrides
})

const store: SuperAdminStoreRow = {
  public_id: 'store-1',
  name: 'Barber Uno',
  slug: 'barber-uno',
  logo_url: null,
  primary_color: '#ff8c42',
  cancellation_hours: 24,
  buffer_minutes: 0,
  send_email_confirmation: true,
  send_email_reminders: true,
  is_active: true,
  is_internal: false,
  created_at: '2026-01-10T12:00:00Z',
  updated_at: '2026-01-10T12:00:00Z',
  admins_count: 0,
  users_count: 0,
  active_users_count: 0,
  has_subscription: false,
  subscription_status: null,
  current_plan_name: null,
  current_period_end: null,
  last_redemption_at: null
}

const emptyOverview: SuperAdminStoreOverview = {
  store: {
    public_id: store.public_id,
    name: store.name,
    slug: store.slug,
    logo_url: store.logo_url,
    primary_color: store.primary_color,
    cancellation_hours: store.cancellation_hours,
    buffer_minutes: store.buffer_minutes,
    send_email_confirmation: store.send_email_confirmation,
    send_email_reminders: store.send_email_reminders,
    is_active: store.is_active,
    is_internal: store.is_internal,
    created_at: store.created_at,
    updated_at: store.updated_at
  },
  users: { admins: [], users: [], admins_count: 0, users_count: 0, active_users_count: 0 },
  subscription: null,
  recent_redemptions: []
}

const renderStores = (
  storesQuery: QueryState<SuperAdminStoreRow[]> & {
    total: number | null
    hasNextPage: boolean
    isFetchingNextPage: boolean
    fetchNextPage: () => unknown
  }
) =>
  render(
    <StoresSection
      search=""
      onSearchChange={jest.fn()}
      activityFilter="all"
      setActivityFilter={jest.fn() as never}
      subscriptionFilter="all"
      setSubscriptionFilter={jest.fn() as never}
      selectedStoreId={null}
      setSelectedStoreId={jest.fn() as never}
      onViewStore={jest.fn()}
      storesQuery={storesQuery}
      openEditStoreFor={jest.fn()}
      toggleStoreActive={jest.fn().mockResolvedValue(undefined)}
    />
  )

const renderPlans = (plansQuery: QueryState<SuperAdminPlan[]>) =>
  render(
    <PlansSection
      plansQuery={plansQuery}
      openCreatePlanModal={jest.fn()}
      openEditPlanModal={jest.fn()}
      togglePlanActive={jest.fn().mockResolvedValue(undefined)}
    />
  )

const renderCoupons = (couponsQuery: QueryState<SuperAdminCoupon[]>) =>
  render(
    <CouponsSection
      couponsQuery={couponsQuery}
      openCreateCouponModal={jest.fn()}
      openEditCouponModal={jest.fn()}
      toggleCouponActive={jest.fn().mockResolvedValue(undefined)}
    />
  )

const renderTenantUsers = (overviewQuery: QueryState<SuperAdminStoreOverview>) =>
  render(
    <TenantUsersSection
      selectedStore={store}
      headingRef={React.createRef<HTMLHeadingElement>()}
      overview={overviewQuery.data}
      overviewQuery={overviewQuery}
      openEditUserModal={jest.fn()}
      toggleUserActive={jest.fn().mockResolvedValue(undefined)}
      toggleGlobalAdmin={jest.fn().mockResolvedValue(undefined)}
    />
  )

const renderSubscription = (overviewQuery: QueryState<SuperAdminStoreOverview>) =>
  render(
    <SubscriptionSection
      selectedStore={store}
      overview={overviewQuery.data}
      overviewQuery={overviewQuery}
      activePlans={[]}
      openAssignPlanModal={jest.fn()}
    />
  )

const renderRedemptions = (overviewQuery: QueryState<SuperAdminStoreOverview>) =>
  render(
    <RedemptionsSection
      selectedStore={store}
      hasSelectedStoreSubscription={Boolean(overviewQuery.data?.subscription)}
      overview={overviewQuery.data}
      overviewQuery={overviewQuery}
      activeCoupons={[]}
      openRedeemCouponModal={jest.fn()}
    />
  )

describe('estados de consulta del control global', () => {
  it('no muestra el listado de tiendas como vacío mientras carga', () => {
    renderStores({
      ...makeQuery<SuperAdminStoreRow[]>({ isLoading: true }),
      total: null,
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: jest.fn()
    })

    expect(screen.getByRole('status')).toHaveTextContent('Cargando tiendas')
    expect(screen.queryByText('No hay tiendas para este filtro')).not.toBeInTheDocument()
  })

  it('permite reintentar la carga fallida de tiendas y no muestra un vacío', () => {
    const refetch = jest.fn()
    renderStores({
      ...makeQuery<SuperAdminStoreRow[]>({ error: new Error('offline'), refetch }),
      total: null,
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: jest.fn()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron cargar las tiendas')
    expect(screen.queryByText('No hay tiendas para este filtro')).not.toBeInTheDocument()
  })

  it('conserva el estado vacío real de tiendas tras una respuesta correcta', () => {
    renderStores({
      ...makeQuery<SuperAdminStoreRow[]>({ data: [] }),
      total: 0,
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: jest.fn()
    })

    expect(screen.getByText('No hay tiendas para este filtro')).toBeInTheDocument()
  })

  it('muestra carga, reintento y catálogo vacío correctamente para los planes', () => {
    const { unmount } = renderPlans(makeQuery<SuperAdminPlan[]>({ isLoading: true }))
    expect(screen.getByRole('status')).toHaveTextContent('Cargando planes')
    expect(screen.queryByText('No hay planes todavía')).not.toBeInTheDocument()

    unmount()
    const refetch = jest.fn()
    renderPlans(makeQuery<SuperAdminPlan[]>({ error: new Error('offline'), refetch }))
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron cargar los planes')
    expect(screen.queryByText('No hay planes todavía')).not.toBeInTheDocument()

    cleanup()
    renderPlans(makeQuery<SuperAdminPlan[]>({ data: [] }))
    expect(screen.getByText('No hay planes todavía')).toBeInTheDocument()
  })

  it('muestra carga, reintento y catálogo vacío correctamente para los cupones', () => {
    const { unmount } = renderCoupons(makeQuery<SuperAdminCoupon[]>({ isLoading: true }))
    expect(screen.getByRole('status')).toHaveTextContent('Cargando cupones')
    expect(screen.queryByText('No hay cupones todavía')).not.toBeInTheDocument()

    unmount()
    const refetch = jest.fn()
    renderCoupons(makeQuery<SuperAdminCoupon[]>({ error: new Error('offline'), refetch }))
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron cargar los cupones')
    expect(screen.queryByText('No hay cupones todavía')).not.toBeInTheDocument()

    cleanup()
    renderCoupons(makeQuery<SuperAdminCoupon[]>({ data: [] }))
    expect(screen.getByText('No hay cupones todavía')).toBeInTheDocument()
  })

  it('ofrece reintento del detalle y distingue usuarios vacíos de un error', () => {
    const { unmount } = renderTenantUsers(makeQuery<SuperAdminStoreOverview>({ isLoading: true }))
    expect(screen.getByRole('status')).toHaveTextContent('Cargando contexto')

    unmount()
    const refetch = jest.fn()
    renderTenantUsers(makeQuery<SuperAdminStoreOverview>({ error: new Error('offline'), refetch }))
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar el detalle')
    expect(screen.queryByText('No hay admins creados')).not.toBeInTheDocument()
    expect(screen.queryByText('No hay usuarios en la tienda')).not.toBeInTheDocument()

    cleanup()
    renderTenantUsers(makeQuery<SuperAdminStoreOverview>({ data: emptyOverview }))
    expect(screen.getByText('No hay admins creados')).toBeInTheDocument()
    expect(screen.getByText('No hay usuarios en la tienda')).toBeInTheDocument()
  })

  it('conserva el último detalle disponible cuando falla una actualización', () => {
    renderTenantUsers(
      makeQuery<SuperAdminStoreOverview>({ data: emptyOverview, error: new Error('offline') })
    )

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo actualizar el detalle')
    expect(screen.getByText('No hay admins creados')).toBeInTheDocument()
    expect(screen.getByText('No hay usuarios en la tienda')).toBeInTheDocument()
  })

  it('no presenta una suscripción fallida como ausente y conserva el vacío confirmado', () => {
    const { unmount } = renderSubscription(makeQuery<SuperAdminStoreOverview>({ isLoading: true }))
    expect(screen.getByRole('status')).toHaveTextContent('Cargando suscripción')
    expect(screen.queryByText('Esta tienda no tiene suscripción')).not.toBeInTheDocument()

    unmount()
    const refetch = jest.fn()
    renderSubscription(makeQuery<SuperAdminStoreOverview>({ error: new Error('offline'), refetch }))
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar suscripción' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status')).toHaveTextContent('No se pudo confirmar la suscripción')
    expect(screen.queryByText('Esta tienda no tiene suscripción')).not.toBeInTheDocument()

    cleanup()
    renderSubscription(makeQuery<SuperAdminStoreOverview>({ data: emptyOverview }))
    expect(screen.getByText('Esta tienda no tiene suscripción')).toBeInTheDocument()
  })

  it('no presenta canjes fallidos como una lista vacía y conserva el vacío confirmado', () => {
    const { unmount } = renderRedemptions(makeQuery<SuperAdminStoreOverview>({ isLoading: true }))
    expect(screen.getByRole('status')).toHaveTextContent('Cargando canjes')
    expect(screen.queryByText('No hay canjes recientes')).not.toBeInTheDocument()

    unmount()
    const refetch = jest.fn()
    renderRedemptions(makeQuery<SuperAdminStoreOverview>({ error: new Error('offline'), refetch }))
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar canjes' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status')).toHaveTextContent('No se pudieron confirmar los canjes')
    expect(screen.queryByText('No hay canjes recientes')).not.toBeInTheDocument()

    cleanup()
    renderRedemptions(makeQuery<SuperAdminStoreOverview>({ data: emptyOverview }))
    expect(screen.getByText('No hay canjes recientes')).toBeInTheDocument()
  })

  it('muestra carga, reintento y vacío correcto en la auditoría reciente', () => {
    render(
      <SuperAdminAuditTimeline
        hasSelectedStore
        entries={undefined}
        isLoading
        isFetching
        error={null}
        onRetry={jest.fn()}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent('Cargando auditoría')
    expect(screen.queryByText('Sin eventos recientes')).not.toBeInTheDocument()

    cleanup()
    const refetch = jest.fn()
    render(
      <SuperAdminAuditTimeline
        hasSelectedStore
        entries={undefined}
        isLoading={false}
        isFetching={false}
        error={new Error('offline')}
        onRetry={refetch}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar la auditoría')
    expect(screen.queryByText('Sin eventos recientes')).not.toBeInTheDocument()

    cleanup()
    render(
      <SuperAdminAuditTimeline
        hasSelectedStore
        entries={[]}
        isLoading={false}
        isFetching={false}
        error={null}
        onRetry={jest.fn()}
      />
    )
    expect(screen.getByText('Sin eventos recientes')).toBeInTheDocument()
  })

  it('no queda cargando auditoría cuando todavía no hay tienda seleccionada', () => {
    render(
      <SuperAdminAuditTimeline
        hasSelectedStore={false}
        entries={[]}
        isLoading={false}
        isFetching={false}
        error={null}
        onRetry={jest.fn()}
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent(
      'Seleccioná una tienda para consultar la auditoría'
    )
    expect(screen.queryByText('Cargando auditoría')).not.toBeInTheDocument()
    expect(screen.queryByText('Sin eventos recientes')).not.toBeInTheDocument()
  })
})
