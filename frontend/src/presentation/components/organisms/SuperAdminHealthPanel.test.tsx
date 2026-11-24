import { fireEvent, render, screen } from '@testing-library/react'

import type {
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { SuperAdminHealthPanel } from './SuperAdminHealthPanel'

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
  admins_count: 1,
  users_count: 2,
  active_users_count: 2,
  has_subscription: false,
  subscription_status: null,
  current_plan_name: null,
  current_period_end: null,
  last_redemption_at: null
}

const overviewWithNoSubscription: SuperAdminStoreOverview = {
  store,
  users: {
    admins: [],
    users: [],
    admins_count: 0,
    users_count: 0,
    active_users_count: 0
  },
  subscription: null,
  recent_redemptions: []
}

const overviewWithSubscription = (currentPeriodEnd: string | null): SuperAdminStoreOverview => ({
  ...overviewWithNoSubscription,
  subscription: {
    public_id: 'subscription-1',
    store_id: store.public_id,
    plan_id: 'plan-1',
    status: 'active',
    base_amount: '1000',
    discount_amount: '0',
    total_amount: '1000',
    currency: 'ARS',
    current_period_start: '2026-11-01T00:00:00Z',
    current_period_end: currentPeriodEnd,
    coupon_id: null,
    is_active: true,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    plan_name: 'Inicial',
    billing_interval: 'monthly',
    max_staff: null,
    max_services: null,
    applied_coupon: null
  }
})

const renderPanel = (
  selectedStore: SuperAdminStoreRow | null,
  options: {
    overview?: SuperAdminStoreOverview
    overviewLoading?: boolean
    overviewError?: boolean
    overviewFetching?: boolean
    onRetryOverview?: () => void
    onAssignPlan?: () => void
  } = {}
) =>
  render(
    <SuperAdminHealthPanel
      selectedStore={selectedStore}
      overview={options.overview}
      overviewLoading={options.overviewLoading ?? false}
      overviewError={options.overviewError ?? false}
      overviewFetching={options.overviewFetching ?? false}
      onRetryOverview={options.onRetryOverview ?? jest.fn()}
      onCreateAdmin={jest.fn()}
      onAssignPlan={options.onAssignPlan ?? jest.fn()}
      onRedeemCoupon={jest.fn()}
      onEditStore={jest.fn()}
      activePlansCount={1}
      activeCouponsCount={1}
    />
  )

// 2026-10-10: la tienda interna solo aloja cuentas SuperAdmin. El atajo de
// "Crear admin" del resumen se apaga igual que el de la cabecera.
describe('SuperAdminHealthPanel', () => {
  it('ofrece "Crear admin" en una tienda comun', () => {
    renderPanel(store)

    expect(screen.getByRole('button', { name: 'Crear admin' })).not.toBeDisabled()
  })

  it('apaga "Crear admin" en la tienda interna', () => {
    renderPanel({ ...store, is_internal: true })

    expect(screen.getByRole('button', { name: 'Crear admin' })).toBeDisabled()
  })

  it('muestra carga sin convertir una consulta pendiente en alertas de cero', () => {
    renderPanel(store, { overviewLoading: true })

    expect(screen.getByRole('status')).toHaveTextContent('Cargando estado operativo')
    expect(screen.queryByText('Sin suscripción')).not.toBeInTheDocument()
    expect(screen.queryByText('Sin admins activos')).not.toBeInTheDocument()
    expect(screen.getAllByText('—')).toHaveLength(3)
  })

  it('permite reintentar el fallo sin presentar datos desconocidos como cero', () => {
    const onRetryOverview = jest.fn()
    renderPanel(store, { overviewError: true, onRetryOverview })

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar el estado operativo')
    expect(screen.queryByText('Sin suscripción')).not.toBeInTheDocument()
    expect(screen.queryByText('Sin admins activos')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar resumen' }))

    expect(onRetryOverview).toHaveBeenCalledTimes(1)
  })

  it('muestra cero y la ausencia de suscripción solo cuando el resumen cargó', () => {
    renderPanel(store, { overview: overviewWithNoSubscription })

    expect(screen.getByText('Sin suscripción')).toBeInTheDocument()
    expect(screen.getByText('Sin admins activos')).toBeInTheDocument()
    expect(screen.getAllByText('0')).toHaveLength(3)
  })

  it('advierte si la suscripción no tiene fecha de fin y permite revisarla', () => {
    const onAssignPlan = jest.fn()
    renderPanel(store, { overview: overviewWithSubscription(null), onAssignPlan })

    expect(screen.getByText('Período sin fecha de fin')).toBeInTheDocument()
    expect(screen.getByText(/No hay una fecha de fin registrada/)).toBeInTheDocument()
    expect(screen.queryByText('Suscripción al día')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Revisar período' }))

    expect(onAssignPlan).toHaveBeenCalledTimes(1)
  })

  it('muestra la fecha de renovación cuando el período sí tiene fecha de fin', () => {
    renderPanel(store, { overview: overviewWithSubscription('2026-12-01T00:00:00Z') })

    expect(screen.getByText('Suscripción al día')).toBeInTheDocument()
    expect(screen.getByText(/Renueva/)).toBeInTheDocument()
    expect(screen.queryByText('Período sin fecha de fin')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revisar período' })).not.toBeInTheDocument()
  })

  it('explica cuando todavía no hay una tienda seleccionada', () => {
    renderPanel(null)

    expect(screen.getByRole('status')).toHaveTextContent('Seleccioná una tienda')
    expect(screen.queryByText('Sin suscripción')).not.toBeInTheDocument()
  })
})
