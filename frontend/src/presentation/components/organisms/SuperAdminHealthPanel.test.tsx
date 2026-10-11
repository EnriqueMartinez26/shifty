import { render, screen } from '@testing-library/react'

import type { SuperAdminStoreRow } from '@application/services/SuperAdminService'

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

const renderPanel = (selectedStore: SuperAdminStoreRow) =>
  render(
    <SuperAdminHealthPanel
      selectedStore={selectedStore}
      overview={undefined}
      onCreateAdmin={jest.fn()}
      onAssignPlan={jest.fn()}
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
})
