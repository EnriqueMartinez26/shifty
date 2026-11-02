import React from 'react'

import { render, screen } from '@testing-library/react'

import { CouponModals } from './CouponModals'
import { PlanModals } from './PlanModals'
import {
  createEmptyAdminForm,
  createEmptyCouponForm,
  createEmptyPlanForm,
  createEmptyRedeemForm,
  createEmptyStoreForm,
  createEmptySubscriptionForm,
  createEmptyUserForm
} from './shared'
import { StoreModals } from './StoreModals'
import { UserModals } from './UserModals'

const expectVisibleLabelsToNameControls = (container: HTMLElement) => {
  const labels = Array.from(container.querySelectorAll('label'))
  expect(labels.length).toBeGreaterThan(0)

  for (const label of labels) {
    expect(label.htmlFor).toBeTruthy()
    const control = screen.getByLabelText(label.textContent?.trim() ?? '')
    expect(label.control).toBe(control)
    expect(document.getElementById(label.htmlFor)).toBe(control)
  }
}

const storeProps = (modal: 'create-store' | 'create-admin') =>
  ({
    modal,
    closeModal: jest.fn(),
    modalError: null,
    selectedStore: null,
    storeForm: createEmptyStoreForm(),
    setStoreForm: jest.fn(),
    handleStoreSubmit: jest.fn(),
    createStoreMutation: { isPending: false },
    updateStoreMutation: { isPending: false },
    adminForm: createEmptyAdminForm(),
    setAdminForm: jest.fn(),
    handleAdminSubmit: jest.fn(),
    createAdminMutation: { isPending: false }
  }) as React.ComponentProps<typeof StoreModals>

const planProps = (modal: 'create-plan' | 'assign-plan') =>
  ({
    modal,
    closeModal: jest.fn(),
    modalError: null,
    selectedStore: null,
    selectedStoreUnavailable: false,
    activePlans: [],
    planForm: createEmptyPlanForm(),
    setPlanForm: jest.fn(),
    handlePlanSubmit: jest.fn(),
    createPlanMutation: { isPending: false },
    updatePlanMutation: { isPending: false },
    subscriptionForm: createEmptySubscriptionForm(),
    setSubscriptionForm: jest.fn(),
    handleSubscriptionSubmit: jest.fn(),
    assignSubscriptionMutation: { isPending: false }
  }) as React.ComponentProps<typeof PlanModals>

const couponProps = (modal: 'edit-coupon' | 'redeem-coupon') =>
  ({
    modal,
    closeModal: jest.fn(),
    modalError: null,
    selectedStore: null,
    hasSelectedStoreSubscription: true,
    activeCoupons: [],
    couponForm: createEmptyCouponForm(),
    setCouponForm: jest.fn(),
    handleCouponSubmit: jest.fn(),
    createCouponMutation: { isPending: false },
    updateCouponMutation: { isPending: false },
    redeemForm: createEmptyRedeemForm(),
    setRedeemForm: jest.fn(),
    handleRedeemSubmit: jest.fn(),
    redeemCouponMutation: { isPending: false }
  }) as React.ComponentProps<typeof CouponModals>

const userProps = () =>
  ({
    modal: 'edit-user',
    closeModal: jest.fn(),
    modalError: null,
    userForm: createEmptyUserForm(),
    setUserForm: jest.fn(),
    handleUserSubmit: jest.fn(),
    updateUserMutation: { isPending: false }
  }) as React.ComponentProps<typeof UserModals>

describe('etiquetas de los formularios del panel global', () => {
  it('asocia los campos de tienda con sus controles, incluido el color alternativo', () => {
    const { container } = render(<StoreModals {...storeProps('create-store')} />)

    expectVisibleLabelsToNameControls(container)
    expect(screen.getByLabelText('Código hexadecimal del color principal')).toBeInTheDocument()
  })

  it('asocia los campos del alta de administradores', () => {
    const { container } = render(<StoreModals {...storeProps('create-admin')} />)

    expectVisibleLabelsToNameControls(container)
  })

  it('asocia los campos de planes y suscripción', () => {
    const plan = render(<PlanModals {...planProps('create-plan')} />)
    expectVisibleLabelsToNameControls(plan.container)
    plan.unmount()

    const subscription = render(<PlanModals {...planProps('assign-plan')} />)
    expectVisibleLabelsToNameControls(subscription.container)
  })

  it('asocia los campos de cupones y canjes', () => {
    const coupon = render(<CouponModals {...couponProps('edit-coupon')} />)
    expectVisibleLabelsToNameControls(coupon.container)
    coupon.unmount()

    const redemption = render(<CouponModals {...couponProps('redeem-coupon')} />)
    expectVisibleLabelsToNameControls(redemption.container)
  })

  it('asocia los campos del editor de usuarios', () => {
    const { container } = render(<UserModals {...userProps()} />)

    expectVisibleLabelsToNameControls(container)
  })
})
