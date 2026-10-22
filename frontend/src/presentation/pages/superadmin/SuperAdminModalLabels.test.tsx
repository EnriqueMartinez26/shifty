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

const pending = { isPending: false }
const closeModal = () => undefined
const submit = async () => undefined
const setForm = () => undefined

const expectLabeledFields = (labels: string[]) => {
  labels.forEach((label) => {
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  })
}

describe('campos de los modales SuperAdmin', () => {
  it('asocia etiquetas a cada campo de cupones y canjes', () => {
    const { rerender } = render(
      <CouponModals
        modal="create-coupon"
        closeModal={closeModal}
        modalError={null}
        selectedStore={null}
        hasSelectedStoreSubscription
        activeCoupons={[]}
        couponForm={createEmptyCouponForm()}
        setCouponForm={setForm}
        handleCouponSubmit={submit}
        createCouponMutation={pending}
        updateCouponMutation={pending}
        redeemForm={createEmptyRedeemForm()}
        setRedeemForm={setForm}
        handleRedeemSubmit={submit}
        redeemCouponMutation={pending}
      />
    )

    expectLabeledFields([
      'Código',
      'Tipo',
      'Valor',
      'Moneda',
      'Max usos',
      'Canje único por tienda',
      'Vigente desde',
      'Vigente hasta',
      'Descripción'
    ])

    rerender(
      <CouponModals
        modal="redeem-coupon"
        closeModal={closeModal}
        modalError={null}
        selectedStore={null}
        hasSelectedStoreSubscription
        activeCoupons={[]}
        couponForm={createEmptyCouponForm()}
        setCouponForm={setForm}
        handleCouponSubmit={submit}
        createCouponMutation={pending}
        updateCouponMutation={pending}
        redeemForm={createEmptyRedeemForm()}
        setRedeemForm={setForm}
        handleRedeemSubmit={submit}
        redeemCouponMutation={pending}
      />
    )

    expectLabeledFields(['Cupón'])
  })

  it('asocia etiquetas a los campos de planes y suscripciones', () => {
    const { rerender } = render(
      <PlanModals
        modal="create-plan"
        closeModal={closeModal}
        modalError={null}
        selectedStore={null}
        selectedStoreUnavailable={false}
        activePlans={[]}
        planForm={createEmptyPlanForm()}
        setPlanForm={setForm}
        handlePlanSubmit={submit}
        createPlanMutation={pending}
        updatePlanMutation={pending}
        subscriptionForm={createEmptySubscriptionForm()}
        setSubscriptionForm={setForm}
        handleSubscriptionSubmit={submit}
        assignSubscriptionMutation={pending}
      />
    )

    expectLabeledFields([
      'Nombre',
      'Intervalo',
      'Descripción',
      'Precio',
      'Moneda',
      'Max staff',
      'Max services'
    ])

    rerender(
      <PlanModals
        modal="assign-plan"
        closeModal={closeModal}
        modalError={null}
        selectedStore={null}
        selectedStoreUnavailable={false}
        activePlans={[]}
        planForm={createEmptyPlanForm()}
        setPlanForm={setForm}
        handlePlanSubmit={submit}
        createPlanMutation={pending}
        updatePlanMutation={pending}
        subscriptionForm={createEmptySubscriptionForm()}
        setSubscriptionForm={setForm}
        handleSubscriptionSubmit={submit}
        assignSubscriptionMutation={pending}
      />
    )

    expectLabeledFields([
      'Plan',
      'Status',
      'Monto base',
      'Moneda',
      'Período desde',
      'Período hasta'
    ])
  })

  it('asocia etiquetas a los campos de tiendas y administradores', () => {
    const { rerender } = render(
      <StoreModals
        modal="create-store"
        closeModal={closeModal}
        modalError={null}
        selectedStore={null}
        storeForm={createEmptyStoreForm()}
        setStoreForm={setForm}
        handleStoreSubmit={submit}
        createStoreMutation={pending}
        updateStoreMutation={pending}
        adminForm={createEmptyAdminForm()}
        setAdminForm={setForm}
        handleAdminSubmit={submit}
        createAdminMutation={pending}
      />
    )

    expectLabeledFields([
      'Nombre',
      'Slug',
      'Color principal',
      'Código hexadecimal del color principal',
      'Horas de cancelación',
      'Buffer (minutos)'
    ])
    // 2026-10-21 (S2b): el logo lo sube la tienda; la CSP no carga URLs externas.
    expect(screen.queryByLabelText('Logo URL')).not.toBeInTheDocument()

    rerender(
      <StoreModals
        modal="create-admin"
        closeModal={closeModal}
        modalError={null}
        selectedStore={null}
        storeForm={createEmptyStoreForm()}
        setStoreForm={setForm}
        handleStoreSubmit={submit}
        createStoreMutation={pending}
        updateStoreMutation={pending}
        adminForm={createEmptyAdminForm()}
        setAdminForm={setForm}
        handleAdminSubmit={submit}
        createAdminMutation={pending}
      />
    )

    expectLabeledFields(['Nombre', 'Apellido', 'Email', 'Teléfono', 'Password'])
  })

  it('asocia etiquetas a los campos de usuarios', () => {
    render(
      <UserModals
        modal="edit-user"
        closeModal={closeModal}
        modalError={null}
        userForm={createEmptyUserForm()}
        setUserForm={setForm}
        handleUserSubmit={submit}
        updateUserMutation={pending}
      />
    )

    expectLabeledFields(['Nombre', 'Apellido', 'Rol', 'Teléfono', 'Nueva password (opcional)'])
  })
})
