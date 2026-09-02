import { fireEvent, screen, render, waitFor, within } from '@testing-library/react'

import type {
  SuperAdminCoupon,
  SuperAdminPlan,
  SuperAdminStoreOverview,
  SuperAdminStoreRow,
  SuperAdminUser
} from '@application/services/SuperAdminService'

import SuperAdminPage from './SuperAdmin'

/**
 * Tests de caracterizacion del panel SuperAdmin.
 *
 * Fijan el comportamiento actual (que renderiza cada seccion y que payload
 * dispara cada formulario) para poder descomponer el componente gigante sin
 * cambiarlo por accidente. Si un flujo se descablea en el split, esto lo grita.
 */

const mockMutations = {
  createStore: jest.fn(),
  updateStore: jest.fn(),
  createAdmin: jest.fn(),
  updateUser: jest.fn(),
  setGlobalAdmin: jest.fn(),
  createPlan: jest.fn(),
  updatePlan: jest.fn(),
  assignSubscription: jest.fn(),
  createCoupon: jest.fn(),
  updateCoupon: jest.fn(),
  redeemCoupon: jest.fn()
}

const mockStoreUno: SuperAdminStoreRow = {
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
  created_at: '2026-01-10T12:00:00Z',
  updated_at: '2026-01-10T12:00:00Z',
  admins_count: 1,
  users_count: 2,
  active_users_count: 2,
  has_subscription: true,
  subscription_status: 'active',
  current_plan_name: 'Plan Oro',
  current_period_end: null,
  last_redemption_at: null
}

const mockAdminUser: SuperAdminUser = {
  public_id: 'user-admin-1',
  email: 'root@barberuno.com',
  first_name: 'Root',
  last_name: 'Admin',
  phone: null,
  role: 'admin',
  store_id: 'store-1',
  is_active: true,
  is_global_admin: false,
  created_at: '2026-01-10T12:00:00Z',
  updated_at: '2026-01-10T12:00:00Z'
}

const mockPlanOro: SuperAdminPlan = {
  public_id: 'plan-1',
  name: 'Plan Oro',
  description: null,
  price: '15000',
  currency: 'ARS',
  billing_interval: 'monthly',
  max_staff: null,
  max_services: null,
  is_active: true,
  created_at: '2026-01-10T12:00:00Z',
  updated_at: '2026-01-10T12:00:00Z'
}

const mockCupon: SuperAdminCoupon = {
  public_id: 'coupon-1',
  code: 'WELCOME10',
  coupon_type: 'percent',
  value: '10',
  currency: null,
  max_uses: null,
  current_uses: 0,
  valid_from: null,
  valid_until: null,
  one_time_per_store: false,
  description: null,
  is_active: true,
  created_at: '2026-01-10T12:00:00Z',
  updated_at: '2026-01-10T12:00:00Z'
}

const mockOverview: SuperAdminStoreOverview = {
  store: {
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
    created_at: '2026-01-10T12:00:00Z',
    updated_at: '2026-01-10T12:00:00Z'
  },
  users: {
    admins: [mockAdminUser],
    users: [mockAdminUser],
    admins_count: 1,
    users_count: 1,
    active_users_count: 1
  },
  subscription: {
    public_id: 'sub-1',
    store_id: 'store-1',
    plan_id: 'plan-1',
    status: 'active',
    base_amount: '15000',
    discount_amount: '0.00',
    total_amount: '15000',
    currency: 'ARS',
    current_period_start: null,
    current_period_end: null,
    coupon_id: null,
    is_active: true,
    created_at: '2026-01-10T12:00:00Z',
    updated_at: '2026-01-10T12:00:00Z',
    plan_name: 'Plan Oro',
    billing_interval: 'monthly',
    max_staff: null,
    max_services: null,
    applied_coupon: null
  },
  recent_redemptions: []
}

jest.mock('../hooks/useSuperAdmin', () => ({
  useSuperAdminStores: () => ({
    data: [mockStoreUno],
    isLoading: false,
    isFetching: false
  }),
  useSuperAdminOverview: () => ({
    data: mockOverview,
    isLoading: false,
    isFetching: false
  }),
  useSuperAdminStoreAudit: () => ({ data: [], isLoading: false, isFetching: false }),
  useSuperAdminPlans: () => ({ data: [mockPlanOro], isLoading: false, isFetching: false }),
  useSuperAdminCoupons: () => ({ data: [mockCupon], isLoading: false, isFetching: false }),
  useCreateSuperAdminStore: () => ({ mutateAsync: mockMutations.createStore, isPending: false }),
  useUpdateSuperAdminStore: () => ({ mutateAsync: mockMutations.updateStore, isPending: false }),
  useCreateSuperAdminStoreAdmin: () => ({
    mutateAsync: mockMutations.createAdmin,
    isPending: false
  }),
  useUpdateSuperAdminUser: () => ({ mutateAsync: mockMutations.updateUser, isPending: false }),
  useSetSuperAdminGlobalAdmin: () => ({
    mutateAsync: mockMutations.setGlobalAdmin,
    isPending: false
  }),
  useCreateSuperAdminPlan: () => ({ mutateAsync: mockMutations.createPlan, isPending: false }),
  useUpdateSuperAdminPlan: () => ({ mutateAsync: mockMutations.updatePlan, isPending: false }),
  useAssignSuperAdminSubscription: () => ({
    mutateAsync: mockMutations.assignSubscription,
    isPending: false
  }),
  useCreateSuperAdminCoupon: () => ({ mutateAsync: mockMutations.createCoupon, isPending: false }),
  useUpdateSuperAdminCoupon: () => ({ mutateAsync: mockMutations.updateCoupon, isPending: false }),
  useRedeemSuperAdminCoupon: () => ({ mutateAsync: mockMutations.redeemCoupon, isPending: false })
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { public_id: 'root-user' } })
}))

jest.mock('../components/organisms/SuperAdminHealthPanel', () => ({
  SuperAdminHealthPanel: () => null
}))

jest.mock('../components/organisms/SuperAdminAuditTimeline', () => ({
  SuperAdminAuditTimeline: () => null
}))

const sectionOf = (headingName: string) => {
  const heading = screen.getByRole('heading', { name: headingName })
  const section = heading.closest('section')
  if (!section) throw new Error(`No encontre la seccion de "${headingName}"`)
  return within(section)
}

const first = <T,>(items: T[]): T => {
  const [item] = items
  if (item === undefined) throw new Error('Esperaba al menos un elemento')
  return item
}

const openModalForm = (): HTMLFormElement => {
  const form = document.querySelector('form')
  if (!form) throw new Error('No hay ningun modal abierto con formulario')
  return form
}

describe('SuperAdminPage', () => {
  beforeEach(() => {
    Object.values(mockMutations).forEach((mutation) => mutation.mockReset())
    mockMutations.createStore.mockResolvedValue({
      ...mockStoreUno,
      public_id: 'store-2',
      name: 'Barber Dos'
    })
    mockMutations.updateStore.mockResolvedValue(mockStoreUno)
    mockMutations.createAdmin.mockResolvedValue(mockAdminUser)
    mockMutations.updateUser.mockResolvedValue(mockAdminUser)
    mockMutations.createPlan.mockResolvedValue(mockPlanOro)
    mockMutations.updatePlan.mockResolvedValue(mockPlanOro)
    mockMutations.assignSubscription.mockResolvedValue(mockOverview.subscription)
    mockMutations.createCoupon.mockResolvedValue(mockCupon)
    mockMutations.updateCoupon.mockResolvedValue(mockCupon)
    mockMutations.redeemCoupon.mockResolvedValue({
      public_id: 'red-1',
      code_snapshot: 'WELCOME10'
    })
  })

  it('renderiza las secciones con los datos de tiendas, planes y cupones', () => {
    render(<SuperAdminPage />)

    expect(screen.getByRole('heading', { name: 'Control Global' })).toBeInTheDocument()
    expect(screen.getAllByText('Barber Uno').length).toBeGreaterThan(0)
    expect(sectionOf('Catalogo global').getByText('Plan Oro')).toBeInTheDocument()
    expect(sectionOf('Maestro editable').getByText('WELCOME10')).toBeInTheDocument()
    expect(
      sectionOf('Detalle del tenant').getAllByText('root@barberuno.com').length
    ).toBeGreaterThan(0)
  })

  it('crea una tienda con el payload del formulario', async () => {
    render(<SuperAdminPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Crear tienda' }))
    const form = openModalForm()
    const textboxes = within(form).getAllByRole('textbox')
    fireEvent.change(first(textboxes), { target: { value: 'Barber Dos' } })
    fireEvent.change(first(textboxes.slice(1)), { target: { value: 'barber-dos' } })
    fireEvent.submit(form)

    await waitFor(() => {
      expect(mockMutations.createStore).toHaveBeenCalledWith({
        name: 'Barber Dos',
        slug: 'barber-dos',
        logo_url: null,
        primary_color: '#ff8c42',
        cancellation_hours: 24,
        buffer_minutes: 0,
        send_email_confirmation: true,
        send_email_reminders: true
      })
    })
    expect(await screen.findByText('Tienda creada: Barber Dos')).toBeInTheDocument()
  })

  it('edita un plan reenviando sus valores actuales', async () => {
    render(<SuperAdminPage />)

    fireEvent.click(first(sectionOf('Catalogo global').getAllByRole('button', { name: 'Editar' })))
    fireEvent.submit(openModalForm())

    await waitFor(() => {
      expect(mockMutations.updatePlan).toHaveBeenCalledWith({
        planPublicId: 'plan-1',
        payload: {
          name: 'Plan Oro',
          description: null,
          price: '15000',
          currency: 'ARS',
          billing_interval: 'monthly',
          max_staff: null,
          max_services: null,
          is_active: true
        }
      })
    })
  })

  it('edita un cupon reenviando sus valores actuales', async () => {
    render(<SuperAdminPage />)

    fireEvent.click(first(sectionOf('Maestro editable').getAllByRole('button', { name: 'Editar' })))
    fireEvent.submit(openModalForm())

    await waitFor(() => {
      expect(mockMutations.updateCoupon).toHaveBeenCalledWith({
        couponPublicId: 'coupon-1',
        payload: {
          code: 'WELCOME10',
          coupon_type: 'percent',
          value: '10',
          currency: null,
          max_uses: null,
          valid_from: null,
          valid_until: null,
          one_time_per_store: false,
          description: null,
          is_active: true
        }
      })
    })
  })

  it('edita un usuario del tenant seleccionado', async () => {
    render(<SuperAdminPage />)

    fireEvent.click(
      first(sectionOf('Detalle del tenant').getAllByRole('button', { name: 'Editar' }))
    )
    fireEvent.submit(openModalForm())

    await waitFor(() => {
      expect(mockMutations.updateUser).toHaveBeenCalledWith({
        userPublicId: 'user-admin-1',
        payload: {
          first_name: 'Root',
          last_name: 'Admin',
          phone: null,
          role: 'admin',
          password: undefined,
          is_active: true
        }
      })
    })
  })

  it('asigna un plan a la tienda seleccionada', async () => {
    render(<SuperAdminPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))
    fireEvent.submit(openModalForm())

    await waitFor(() => {
      expect(mockMutations.assignSubscription).toHaveBeenCalledWith({
        storePublicId: 'store-1',
        payload: {
          plan_id: 'plan-1',
          status: 'active',
          base_amount: '15000',
          currency: 'ARS',
          current_period_start: null,
          current_period_end: null
        }
      })
    })
  })

  it('canjea un cupon sobre la tienda seleccionada', async () => {
    render(<SuperAdminPage />)

    fireEvent.click(first(screen.getAllByRole('button', { name: 'Canjear cupon' })))
    fireEvent.submit(openModalForm())

    await waitFor(() => {
      expect(mockMutations.redeemCoupon).toHaveBeenCalledWith({
        storePublicId: 'store-1',
        couponCode: 'WELCOME10'
      })
    })
    expect(await screen.findByText('Cupon WELCOME10 canjeado en Barber Uno')).toBeInTheDocument()
  })
})
