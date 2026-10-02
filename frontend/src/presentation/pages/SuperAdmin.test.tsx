import { act, fireEvent, screen, render, waitFor, within } from '@testing-library/react'

import type {
  SuperAdminCoupon,
  SuperAdminPlan,
  SuperAdminStoreOverview,
  SuperAdminStoreRow,
  SuperAdminUser
} from '@application/services/SuperAdminService'

import { ValidationError } from '@shared/errors/ValidationError'

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

let mockStores: SuperAdminStoreRow[] = [mockStoreUno]
const mockOverviewFor = jest.fn()
const mockStoresFor = jest.fn()
const mockStoresPage = {
  total: null as number | null,
  hasNextPage: false,
  isFetchingNextPage: false,
  fetchNextPage: jest.fn()
}

jest.mock('../hooks/useSuperAdmin', () => ({
  // Con busqueda el listado trae otra tienda: si la busqueda se aplicara por
  // tecla, el detalle se pediria una vez por cada tienda intermedia.
  useSuperAdminStores: (params: { search?: string }) => {
    mockStoresFor(params)
    return {
      data: params.search ? [{ ...mockStoreUno, public_id: `store-${params.search}` }] : mockStores,
      isLoading: false,
      isFetching: false,
      ...mockStoresPage
    }
  },
  useSuperAdminOverview: (storeId: string | null) => {
    mockOverviewFor(storeId)
    return { data: mockOverview, isLoading: false, isFetching: false }
  },
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

const mockAuthUser = { public_id: 'root-user' }

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockAuthUser })
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
    mockStores = [mockStoreUno]
    mockOverviewFor.mockReset()
    mockStoresFor.mockReset()
    mockStoresPage.total = null
    mockStoresPage.hasNextPage = false
    mockStoresPage.fetchNextPage.mockReset()
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

  // 2026-10-02, QA en navegador: estados de suscripcion e intervalos salian
  // crudos de la API (ACTIVE, MONTHLY con uppercase).
  it('muestra estado de suscripcion, intervalo y rol en castellano', () => {
    render(<SuperAdminPage />)

    expect(screen.queryByText(/\bactive\b/)).not.toBeInTheDocument()
    expect(screen.queryByText(/monthly/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/Mensual/).length).toBeGreaterThan(0)
    expect(sectionOf('Operacion por tenant').getByText('Activa', { selector: 'p' })).toBeTruthy()
    expect(sectionOf('Detalle del tenant').getAllByText('Administrador').length).toBeGreaterThan(0)
  })

  // QA 2026-10-02 (S\55): los filtros de suscripcion quedaban tapados por la
  // columna derecha; ahora pasan de linea bajo el titulo.
  it('los filtros de tiendas pasan de linea en vez de desbordar', () => {
    render(<SuperAdminPage />)

    const grupo = screen.getByRole('button', { name: 'Con suscripcion' })
      .parentElement as HTMLElement
    const filtros = grupo.parentElement as HTMLElement
    expect(grupo.className).toContain('flex-wrap')
    expect(filtros.className).toContain('flex-wrap')
    expect((filtros.parentElement as HTMLElement).className).not.toContain('lg:flex-row')
  })

  it('sin eleccion toma la primera tienda desde el primer render (F11b-21)', () => {
    render(<SuperAdminPage />)

    expect(mockOverviewFor).toHaveBeenCalledWith('store-1')
    expect(mockOverviewFor).not.toHaveBeenCalledWith(null)
  })

  // Antes un efecto reponia la primera tienda en cuanto la recien creada no
  // estaba en el listado, y cuando el listado la traia ya se habia perdido.
  it('la tienda recien creada queda elegida cuando el listado la trae (F11b-21)', async () => {
    const { rerender } = render(<SuperAdminPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Crear tienda' }))
    const form = openModalForm()
    const textboxes = within(form).getAllByRole('textbox')
    fireEvent.change(first(textboxes), { target: { value: 'Barber Dos' } })
    fireEvent.change(first(textboxes.slice(1)), { target: { value: 'barber-dos' } })
    fireEvent.submit(form)
    expect(await screen.findByText('Tienda creada: Barber Dos')).toBeInTheDocument()

    mockStores = [mockStoreUno, { ...mockStoreUno, public_id: 'store-2', name: 'Barber Dos' }]
    mockOverviewFor.mockReset()
    rerender(<SuperAdminPage />)

    expect(mockOverviewFor).toHaveBeenLastCalledWith('store-2')
  })

  // 2026-10-02, QA en navegador (S\56): un slug invalido daba "No se pudo
  // guardar la tienda", sin decir que corregir.
  it('un slug invalido no se envia y explica el formato', () => {
    render(<SuperAdminPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Crear tienda' }))
    const form = openModalForm()
    const textboxes = within(form).getAllByRole('textbox')
    fireEvent.change(first(textboxes), { target: { value: 'Barber Dos' } })
    fireEvent.change(first(textboxes.slice(1)), { target: { value: 'Barber Dos!' } })
    fireEvent.submit(form)

    expect(mockMutations.createStore).not.toHaveBeenCalled()
    expect(within(form).getByRole('alert')).toHaveTextContent(/minúsculas, números y guiones/)
  })

  it('un 422 en el slug dice el formato, nunca el texto crudo', async () => {
    mockMutations.createStore.mockRejectedValueOnce(
      new ValidationError("slug: String should match pattern '^[a-z0-9]'", {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422,
        detail: ["slug: String should match pattern '^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$'"]
      })
    )
    render(<SuperAdminPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Crear tienda' }))
    const form = openModalForm()
    const textboxes = within(form).getAllByRole('textbox')
    fireEvent.change(first(textboxes), { target: { value: 'Barber Dos' } })
    fireEvent.change(first(textboxes.slice(1)), { target: { value: 'barber-dos' } })
    fireEvent.submit(form)

    const alerta = await within(form).findByRole('alert')
    expect(alerta).toHaveTextContent(/minúsculas, números y guiones/)
    expect(alerta).not.toHaveTextContent(/pattern/)
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

  // 2026-09-30 (FF-24, F4-10): "Todas" mostraba solo activas, la lista cortaba
  // en 50 y cada tecla disparaba hasta 3 requests (listado, detalle y auditoria).
  describe('listado de tiendas', () => {
    it('"Todas" pide is_active=all', () => {
      render(<SuperAdminPage />)

      fireEvent.click(
        first(sectionOf('Operacion por tenant').getAllByRole('button', { name: 'Todas' }))
      )

      expect(mockStoresFor).toHaveBeenLastCalledWith(expect.objectContaining({ is_active: 'all' }))
    })

    it('"Cargar mas" pide la pagina siguiente', () => {
      mockStoresPage.hasNextPage = true
      render(<SuperAdminPage />)

      fireEvent.click(screen.getByRole('button', { name: 'Cargar más' }))

      expect(mockStoresPage.fetchNextPage).toHaveBeenCalledTimes(1)
    })

    it('muestra cuantas tiendas hay cargadas sobre el total', () => {
      mockStoresPage.total = 120
      const { rerender } = render(<SuperAdminPage />)
      expect(screen.getByText('Mostrando 1 de 120')).toBeInTheDocument()

      mockStoresPage.total = null
      rerender(<SuperAdminPage />)
      expect(screen.getByText('Mostrando 1')).toBeInTheDocument()
    })

    describe('busqueda con espera', () => {
      beforeEach(() => jest.useFakeTimers())
      afterEach(() => jest.useRealTimers())

      it('cuatro teclas hacen UNA busqueda a los 300 ms y el detalle no se pide por tecla', () => {
        render(<SuperAdminPage />)
        const input = screen.getByPlaceholderText('Buscar por nombre o slug')

        for (const value of ['b', 'ba', 'bar', 'barb']) {
          fireEvent.change(input, { target: { value } })
          act(() => jest.advanceTimersByTime(100))
        }
        expect((input as HTMLInputElement).value).toBe('barb')
        expect(mockStoresFor).not.toHaveBeenCalledWith(expect.objectContaining({ search: 'b' }))

        act(() => jest.advanceTimersByTime(300))

        const searches = mockStoresFor.mock.calls
          .map(([params]: [{ search?: string }]) => params.search)
          .filter(Boolean)
        expect(new Set(searches)).toEqual(new Set(['barb']))
        const overviews = new Set(mockOverviewFor.mock.calls.map(([id]: [string]) => id))
        expect(overviews).toEqual(new Set(['store-1', 'store-barb']))
      })
    })
  })

  // F11b-10: los cinco toggles comparten confirmar -> mutar -> avisar. Antes
  // ningun test ejercia ni uno, ni la guarda de auto-revocacion.
  describe('toggles con confirmacion', () => {
    // La pregunta sale en el ConfirmDialog propio (D1), no en window.confirm.
    const answerDialog = (question: string, button: 'Confirmar' | 'Cancelar') => {
      const dialog = screen.getByRole('alertdialog', { name: question })
      fireEvent.click(within(dialog).getByRole('button', { name: button }))
    }

    it('desactiva una tienda despues de confirmar y avisa en tono de advertencia', async () => {
      render(<SuperAdminPage />)

      fireEvent.click(sectionOf('Operacion por tenant').getByRole('button', { name: 'Desactivar' }))
      answerDialog(
        'Desactivar Barber Uno? Esto puede bloquear nuevas operaciones del tenant.',
        'Confirmar'
      )

      await waitFor(() => {
        expect(mockMutations.updateStore).toHaveBeenCalledWith({
          storePublicId: 'store-1',
          payload: { is_active: false }
        })
      })
      expect(await screen.findByText('Tienda desactivada: Barber Uno')).toBeInTheDocument()
    })

    it('no toca nada si se cancela la confirmacion', async () => {
      render(<SuperAdminPage />)

      fireEvent.click(sectionOf('Catalogo global').getByRole('button', { name: 'Desactivar' }))
      answerDialog('Desactivar plan Plan Oro?', 'Cancelar')

      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
      expect(mockMutations.updatePlan).not.toHaveBeenCalled()
    })

    it('si la mutacion falla muestra el mensaje de respaldo del toggle', async () => {
      mockMutations.updateCoupon.mockRejectedValue({})
      render(<SuperAdminPage />)

      fireEvent.click(sectionOf('Maestro editable').getByRole('button', { name: 'Desactivar' }))
      fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

      expect(await screen.findByText('No se pudo actualizar el cupon')).toBeInTheDocument()
    })

    it('desactiva un usuario del tenant', async () => {
      render(<SuperAdminPage />)

      fireEvent.click(
        first(sectionOf('Detalle del tenant').getAllByRole('button', { name: 'Desactivar' }))
      )
      fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

      await waitFor(() => {
        expect(mockMutations.updateUser).toHaveBeenCalledWith({
          userPublicId: 'user-admin-1',
          payload: { is_active: false }
        })
      })
    })

    it('promueve a Super Admin global despues de confirmar', async () => {
      render(<SuperAdminPage />)

      fireEvent.click(
        first(
          sectionOf('Detalle del tenant').getAllByRole('button', { name: 'Promover SuperAdmin' })
        )
      )
      fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

      await waitFor(() => {
        expect(mockMutations.setGlobalAdmin).toHaveBeenCalledWith({
          userPublicId: 'user-admin-1',
          isGlobalAdmin: true
        })
      })
      expect(await screen.findByText('root@barberuno.com ahora es Super Admin')).toBeInTheDocument()
    })

    // 2026-10-02, QA en navegador (S\62): "Promover SuperAdmin" se ofrecia
    // sobre un cliente final. El backend lo rechaza
    // (CLIENT_GLOBAL_ADMIN_DENIED); el panel ni lo ofrece.
    it('no ofrece promover a SuperAdmin a un cliente', () => {
      const cliente: SuperAdminUser = {
        ...mockAdminUser,
        public_id: 'user-client-1',
        email: 'cliente@example.com',
        first_name: 'Clara',
        last_name: 'Cliente',
        role: 'client'
      }
      const usuarios = mockOverview.users.users
      mockOverview.users.users = [cliente]
      try {
        render(<SuperAdminPage />)

        const detalle = sectionOf('Detalle del tenant')
        // El unico "Promover" que queda es el del admin, en su propia lista.
        expect(detalle.getAllByRole('button', { name: 'Promover SuperAdmin' })).toHaveLength(1)
        const tarjeta = detalle.getByText('Clara Cliente').closest('div.rounded-2xl') as HTMLElement
        expect(within(tarjeta).queryByRole('button', { name: /SuperAdmin/ })).toBeNull()
        expect(within(tarjeta).getByRole('button', { name: 'Editar' })).toBeInTheDocument()
      } finally {
        mockOverview.users.users = usuarios
      }
    })

    it('a un cliente que ya es SuperAdmin se le puede revocar', () => {
      const cliente: SuperAdminUser = {
        ...mockAdminUser,
        public_id: 'user-client-2',
        first_name: 'Carla',
        last_name: 'Global',
        role: 'client',
        is_global_admin: true
      }
      const usuarios = mockOverview.users.users
      mockOverview.users.users = [cliente]
      try {
        render(<SuperAdminPage />)

        const tarjeta = sectionOf('Detalle del tenant')
          .getByText('Carla Global')
          .closest('div.rounded-2xl') as HTMLElement
        expect(
          within(tarjeta).getByRole('button', { name: 'Revocar SuperAdmin' })
        ).toBeInTheDocument()
      } finally {
        mockOverview.users.users = usuarios
      }
    })

    it('no deja revocarse el propio permiso global y ni siquiera pregunta', () => {
      // Guarda espejo de la regla 14; la garantia real vive en el backend.
      mockAuthUser.public_id = 'user-admin-1'
      mockAdminUser.is_global_admin = true
      try {
        render(<SuperAdminPage />)

        fireEvent.click(
          first(
            sectionOf('Detalle del tenant').getAllByRole('button', { name: 'Revocar SuperAdmin' })
          )
        )

        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
        expect(mockMutations.setGlobalAdmin).not.toHaveBeenCalled()
        expect(
          screen.getByText('No podés revocar tu propio permiso de SuperAdmin.')
        ).toBeInTheDocument()
      } finally {
        mockAuthUser.public_id = 'root-user'
        mockAdminUser.is_global_admin = false
      }
    })

    describe('la propia cuenta (D-20260930-05)', () => {
      // D-20260930-05: sobre la propia cuenta "Desactivar" y "Revocar
      // SuperAdmin" no se deshabilitan; al hacer clic avisan y cortan sin
      // pedir confirmacion ni llamar al backend.
      const propiaCuenta = () => {
        mockAuthUser.public_id = 'user-admin-1'
        mockAdminUser.is_global_admin = true
      }

      afterEach(() => {
        mockAuthUser.public_id = 'root-user'
        mockAdminUser.is_global_admin = false
      })

      it('"Desactivar" sobre la propia cuenta avisa y corta sin preguntar', () => {
        // 2026-10-01: desactivar la propia cuenta pedia confirmacion y llamaba
        // al backend, que la rechazaba con 400
        // (SELF_SUPERADMIN_DEACTIVATION_DENIED); la autorrevocacion ya cortaba.
        propiaCuenta()
        render(<SuperAdminPage />)

        const boton = first(
          sectionOf('Detalle del tenant').getAllByRole('button', { name: 'Desactivar' })
        )
        expect(boton).not.toBeDisabled()
        fireEvent.click(boton)

        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
        expect(mockMutations.updateUser).not.toHaveBeenCalled()
        expect(
          screen.getByText('No podés desactivar tu propia cuenta de SuperAdmin.')
        ).toBeInTheDocument()
      })

      it('"Revocar SuperAdmin" sobre la propia cuenta esta habilitado, avisa y corta', () => {
        propiaCuenta()
        render(<SuperAdminPage />)

        const boton = first(
          sectionOf('Detalle del tenant').getAllByRole('button', { name: 'Revocar SuperAdmin' })
        )
        expect(boton).not.toBeDisabled()
        fireEvent.click(boton)

        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
        expect(mockMutations.setGlobalAdmin).not.toHaveBeenCalled()
        expect(
          screen.getByText('No podés revocar tu propio permiso de SuperAdmin.')
        ).toBeInTheDocument()
      })

      it('sobre la cuenta de otro, "Desactivar" y "Revocar SuperAdmin" siguen preguntando', async () => {
        mockAdminUser.is_global_admin = true
        render(<SuperAdminPage />)
        const detalle = sectionOf('Detalle del tenant')

        fireEvent.click(first(detalle.getAllByRole('button', { name: 'Desactivar' })))
        answerDialog('Desactivar root@barberuno.com?', 'Cancelar')
        await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())

        fireEvent.click(first(detalle.getAllByRole('button', { name: 'Revocar SuperAdmin' })))
        answerDialog(
          'Revocar Super Admin global a root@barberuno.com? El backend impedira dejar al sistema sin un admin global activo.',
          'Cancelar'
        )
        await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())

        expect(mockMutations.updateUser).not.toHaveBeenCalled()
        expect(mockMutations.setGlobalAdmin).not.toHaveBeenCalled()
      })
    })

    // D-20260930-05: "ultimo SuperAdmin activo" lo sigue resolviendo el 400
    // del backend (regla 14). Su error_code se traduce a un texto neutro.
    it.each([
      [
        'Desactivar',
        'updateUser',
        'SELF_SUPERADMIN_DEACTIVATION_DENIED',
        'No podés desactivar tu propia cuenta de SuperAdmin.'
      ],
      [
        'Desactivar',
        'updateUser',
        'LAST_SUPERADMIN_DEACTIVATION_DENIED',
        'No se puede desactivar al último SuperAdmin activo.'
      ],
      [
        'Revocar SuperAdmin',
        'setGlobalAdmin',
        'SELF_SUPERADMIN_REVOCATION_DENIED',
        'No podés revocar tu propio permiso de SuperAdmin.'
      ],
      [
        'Revocar SuperAdmin',
        'setGlobalAdmin',
        'LAST_SUPERADMIN_REVOCATION_DENIED',
        'No se puede revocar al último SuperAdmin activo.'
      ]
    ] as const)(
      '"%s" (%s) muestra el texto neutro de %s',
      async (boton, mutacion, errorCode, mensaje) => {
        // 2026-10-01: los cuatro codigos de la regla 14 no estaban en
        // ERROR_CODE_MESSAGES y el panel mostraba el texto crudo del servidor.
        mockMutations[mutacion].mockRejectedValue(
          new ValidationError('texto crudo del servidor', { errorCode, statusCode: 400 })
        )
        mockAdminUser.is_global_admin = true
        try {
          render(<SuperAdminPage />)

          fireEvent.click(
            first(sectionOf('Detalle del tenant').getAllByRole('button', { name: boton }))
          )
          fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

          expect(await screen.findByText(mensaje)).toBeInTheDocument()
          expect(screen.queryByText('texto crudo del servidor')).not.toBeInTheDocument()
        } finally {
          mockAdminUser.is_global_admin = false
        }
      }
    )
  })
})
