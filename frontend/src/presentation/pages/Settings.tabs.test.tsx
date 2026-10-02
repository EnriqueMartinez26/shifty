import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import type { GatewayConfig } from '@application/services/PaymentsService'
import type { StoreSettings } from '@application/services/StoreSettingsService'

import { ForbiddenError } from '@shared/errors/ForbiddenError'

import SettingsPage from './Settings'

// 2026-10-02 (F11b-08): caracterizacion de las siete pestanas antes de partir
// Settings.tsx en organismos. Describe lo que la pagina hace HOY; los cortes
// tienen que dejarla verde sin tocar ninguna asercion.

const store: StoreSettings = {
  public_id: 'st_1',
  name: 'Peluqueria Tucuman',
  slug: 'peluqueria-tucuman',
  business_type: 'generic',
  logo_url: null,
  primary_color: '#ff6600',
  cover_url: null,
  description: null,
  whatsapp_number: null,
  instagram_url: null,
  facebook_url: null,
  website_url: null,
  custom_client_fields: [],
  cancellation_hours: 24,
  min_booking_notice_hours: 2,
  buffer_minutes: 10,
  allow_manual_coordination: true,
  deposit_policy: null,
  deposit_far_notice_days: 0,
  deposit_far_notice_extra_percent: 0,
  deposit_new_client_extra_percent: 0,
  deposit_absent_client_extra_percent: 0,
  business_hours: { mon: [{ open: '09:00', close: '13:00' }] },
  send_email_confirmation: true,
  send_email_reminders: false,
  feature_flags: {
    payments: false,
    ledger: false,
    advanced_reports: false,
    new_calendar: false,
    otp_booking: false
  }
}

const updateStore = jest.fn()
const updateFeatureFlags = jest.fn()
const changePassword = jest.fn()
const startOAuth = jest.fn()
const refreshOAuth = jest.fn()
const disconnectOAuth = jest.fn()
const uploadLogo = jest.fn()
const navigateExternal = jest.fn()
let gateway: GatewayConfig | undefined
let gatewayError: unknown = null

jest.mock('../hooks/useStores', () => ({
  useStoreSettings: () => ({ data: store, isLoading: false, error: null }),
  useStoreFeatureFlags: () => ({ data: undefined }),
  useUpdateStoreSettings: () => ({ mutateAsync: updateStore, isPending: false }),
  useUpdateStoreFeatureFlags: () => ({ mutateAsync: updateFeatureFlags, isPending: false }),
  useUploadStoreLogo: () => ({ mutateAsync: uploadLogo, isPending: false })
}))

jest.mock('../hooks/usePayments', () => ({
  useGatewayConfig: () => ({ data: gateway, isLoading: false, error: gatewayError }),
  useStartMercadoPagoOAuth: () => ({ mutateAsync: startOAuth, isPending: false }),
  useRefreshMercadoPagoOAuth: () => ({ mutateAsync: refreshOAuth, isPending: false }),
  useDisconnectMercadoPagoOAuth: () => ({ mutateAsync: disconnectOAuth, isPending: false })
}))

jest.mock('../hooks/useChangePassword', () => ({
  useChangePassword: () => ({ mutateAsync: changePassword, isPending: false })
}))

jest.mock('../hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: [] })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

// jsdom no navega: se mira a donde iria el navegador.
jest.mock('@shared/utils/safeUrl', () => ({
  ...jest.requireActual<object>('@shared/utils/safeUrl'),
  navigateExternal: (raw: string) => navigateExternal(raw)
}))

const renderSettings = (path = '/dashboard/settings') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <SettingsPage />
    </MemoryRouter>
  )

const openTab = (name: string) => fireEvent.click(screen.getByRole('button', { name }))

const saveChanges = () => fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

beforeEach(() => {
  jest.resetAllMocks()
  updateStore.mockResolvedValue(store)
  updateFeatureFlags.mockResolvedValue({ flags: store.feature_flags })
  gateway = undefined
  gatewayError = null
  mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
})

describe('Settings - politicas', () => {
  it('cancelacion y una regla de sena viajan como el parcial editado', async () => {
    renderSettings()
    openTab('Políticas')

    fireEvent.change(screen.getByPlaceholderText('24'), { target: { value: '48' } })
    fireEvent.change(screen.getByLabelText('Recargo cliente nuevo (%)'), {
      target: { value: '15' }
    })
    saveChanges()

    expect(await screen.findByRole('button', { name: 'Guardado' })).toBeInTheDocument()
    expect(updateStore).toHaveBeenCalledWith({
      cancellation_hours: 48,
      deposit_new_client_extra_percent: 15
    })
  })

  it('una regla de sena se recorta a su tope', () => {
    renderSettings()
    openTab('Políticas')

    const dias = screen.getByLabelText<HTMLInputElement>('Reservas con mucha antelación (días)')
    fireEvent.change(dias, { target: { value: '900' } })

    expect(dias.value).toBe('365')
  })
})

describe('Settings - notificaciones', () => {
  it('el interruptor de recordatorios manda solo ese campo', async () => {
    renderSettings()
    openTab('Notificaciones')

    fireEvent.click(screen.getByRole('switch', { name: 'Recordatorios 24hs' }))
    expect(screen.getByRole('switch', { name: 'Recordatorios 24hs' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    saveChanges()

    expect(await screen.findByRole('button', { name: 'Guardado' })).toBeInTheDocument()
    expect(updateStore).toHaveBeenCalledWith({ send_email_reminders: true })
  })
})

describe('Settings - funciones', () => {
  it('prender cobros llega a updateFeatureFlags y no al PATCH de la tienda', async () => {
    renderSettings()
    openTab('Funciones')

    fireEvent.click(screen.getByRole('switch', { name: 'Cobros online y senas' }))
    saveChanges()

    expect(await screen.findByRole('button', { name: 'Guardado' })).toBeInTheDocument()
    expect(updateFeatureFlags).toHaveBeenCalledWith({ payments: true })
    expect(updateStore).not.toHaveBeenCalled()
  })
})

describe('Settings - identidad y campos extra', () => {
  it('"Agregar campo" agrega campo_1 vacio', async () => {
    renderSettings()

    expect(screen.getByText(/No hay campos extra configurados/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Agregar campo' }))

    expect(screen.getByText('Campo #1')).toBeInTheDocument()
    expect(screen.getByDisplayValue('campo_1')).toBeInTheDocument()
    saveChanges()

    expect(await screen.findByRole('button', { name: 'Guardado' })).toBeInTheDocument()
    expect(updateStore).toHaveBeenCalledWith({
      custom_client_fields: [
        {
          key: 'campo_1',
          label: '',
          type: 'text',
          required: false,
          placeholder: '',
          help_text: '',
          options: []
        }
      ]
    })
  })

  it('las opciones de una lista se parsean como Etiqueta|valor', async () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Agregar campo' }))

    fireEvent.change(screen.getByDisplayValue('Texto corto'), { target: { value: 'select' } })
    fireEvent.change(screen.getByPlaceholderText(/Una opcion por linea/), {
      target: { value: 'Primera vez|primera_vez\n  Control  \n\n' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Opcional' }))
    saveChanges()

    expect(await screen.findByRole('button', { name: 'Guardado' })).toBeInTheDocument()
    expect(updateStore).toHaveBeenCalledWith({
      custom_client_fields: [
        expect.objectContaining({
          key: 'campo_1',
          type: 'select',
          required: true,
          options: [
            { label: 'Primera vez', value: 'primera_vez' },
            { label: 'Control', value: 'Control' }
          ]
        })
      ]
    })
  })

  it('la clave se normaliza a minusculas y guiones bajos', () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Agregar campo' }))

    fireEvent.change(screen.getByDisplayValue('campo_1'), {
      target: { value: 'Motivo Consulta!' }
    })

    expect(screen.getByDisplayValue('motivo_consulta_')).toBeInTheDocument()
  })
})

describe('Settings - seguridad', () => {
  const passwordInputs = (container: HTMLElement) => {
    const [current, next, confirm] = Array.from(
      container.querySelectorAll<HTMLInputElement>('input[type="password"]')
    )
    if (!current || !next || !confirm) throw new Error('Faltan los campos de la clave')
    return { current, next, confirm }
  }

  it('contrasenas distintas lo dicen y no llaman a changePassword', () => {
    const { container } = renderSettings()
    openTab('Seguridad')
    const { current, next, confirm } = passwordInputs(container)

    fireEvent.change(current, { target: { value: 'vieja-clave-123' } })
    fireEvent.change(next, { target: { value: 'nueva-clave-456' } })
    fireEvent.change(confirm, { target: { value: 'otra-clave-789' } })
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar Acceso' }))

    expect(screen.getByText('Las contraseñas no coinciden')).toBeInTheDocument()
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('el caso ok llama con current_password y new_password y limpia el formulario', async () => {
    changePassword.mockResolvedValue(undefined)
    const { container } = renderSettings()
    openTab('Seguridad')
    const { current, next, confirm } = passwordInputs(container)

    fireEvent.change(current, { target: { value: 'vieja-clave-123' } })
    fireEvent.change(next, { target: { value: 'nueva-clave-456' } })
    fireEvent.change(confirm, { target: { value: 'nueva-clave-456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar Acceso' }))

    expect(changePassword).toHaveBeenCalledWith({
      current_password: 'vieja-clave-123',
      new_password: 'nueva-clave-456'
    })
    expect(await screen.findByRole('button', { name: 'Actualizar Acceso' })).toBeInTheDocument()
    const cleared = passwordInputs(container)
    expect([cleared.current.value, cleared.next.value, cleared.confirm.value]).toEqual(['', '', ''])
  })

  it('lo tipeado sobrevive a cambiar de pestana', () => {
    const { container } = renderSettings()
    openTab('Seguridad')
    fireEvent.change(passwordInputs(container).current, {
      target: { value: 'vieja-clave-123' }
    })

    openTab('Identidad')
    openTab('Seguridad')

    expect(passwordInputs(container).current.value).toBe('vieja-clave-123')
  })

  it('?tab=security abre esa pestana y esconde Guardar Cambios', () => {
    renderSettings('/dashboard/settings?tab=security')

    expect(screen.getByRole('heading', { name: 'Seguridad' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Actualizar Acceso' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Guardar Cambios' })).not.toBeInTheDocument()
  })
})

describe('Settings - Mercado Pago', () => {
  it('sin conectar, "Conectar" pide el enlace y navega a el', async () => {
    gateway = { provider: 'mercadopago', configured: false, oauth_supported: true }
    startOAuth.mockResolvedValue({
      auth_url: 'https://auth.mercadopago.com/authorization?x=1',
      qr_url: '',
      expires_at: ''
    })
    navigateExternal.mockReturnValue(true)
    renderSettings()
    openTab('Mercado Pago')

    expect(screen.getByText('Cuenta no conectada')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Conectar con Mercado Pago' }))

    expect(startOAuth).toHaveBeenCalledTimes(1)
    await screen.findByText('Cuenta no conectada')
    expect(navigateExternal).toHaveBeenCalledWith('https://auth.mercadopago.com/authorization?x=1')
    expect(screen.queryByRole('button', { name: 'Renovar acceso' })).not.toBeInTheDocument()
  })

  it('un enlace invalido no navega y avisa en el cartel compartido', async () => {
    gateway = { provider: 'mercadopago', configured: false, oauth_supported: true }
    startOAuth.mockResolvedValue({ auth_url: 'javascript:alert(1)', qr_url: '', expires_at: '' })
    navigateExternal.mockReturnValue(false)
    renderSettings()
    openTab('Mercado Pago')

    fireEvent.click(screen.getByRole('button', { name: 'Conectar con Mercado Pago' }))

    // 2026-10-02: antes fijaba el generico "No se pudo iniciar la conexion..."
    // porque getErrorMessage descartaba el mensaje del Error plano que tiraba
    // el handler. El motivo propio (un texto nuestro, regla 20) ahora llega.
    expect(
      await screen.findByText('Mercado Pago devolvió un enlace de conexión inválido.')
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No se pudo iniciar la conexión con Mercado Pago')
    ).not.toBeInTheDocument()
  })

  it('si pedir el enlace falla, avisa con el generico y no navega', async () => {
    // 2026-10-02: separar el enlace invalido no puede filtrar el texto crudo
    // de una excepcion al cartel (regla 20).
    gateway = { provider: 'mercadopago', configured: false, oauth_supported: true }
    startOAuth.mockRejectedValue(new Error('Traceback: KeyError client_secret'))
    renderSettings()
    openTab('Mercado Pago')

    fireEvent.click(screen.getByRole('button', { name: 'Conectar con Mercado Pago' }))

    expect(
      await screen.findByText('No se pudo iniciar la conexión con Mercado Pago')
    ).toBeInTheDocument()
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument()
    expect(navigateExternal).not.toHaveBeenCalled()
  })

  it('sin credenciales OAuth en el servidor, "Conectar" esta apagado y lo dice', () => {
    gateway = { provider: 'mercadopago', configured: false, oauth_supported: false }
    renderSettings()
    openTab('Mercado Pago')

    expect(screen.getByRole('button', { name: 'Conectar con Mercado Pago' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(/credenciales OAuth/)
  })

  it('conectada, renovar y desconectar llaman a sus mutaciones', async () => {
    gateway = {
      provider: 'mercadopago',
      configured: true,
      oauth_user_id: '123456',
      oauth_supported: true
    }
    refreshOAuth.mockResolvedValue(gateway)
    disconnectOAuth.mockResolvedValue(undefined)
    renderSettings()
    openTab('Mercado Pago')

    expect(screen.getByText('Cuenta conectada')).toBeInTheDocument()
    expect(screen.getByText('Cuenta Mercado Pago 123456')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Renovar acceso' }))
    fireEvent.click(screen.getByRole('button', { name: 'Desconectar' }))

    expect(refreshOAuth).toHaveBeenCalledTimes(1)
    expect(disconnectOAuth).toHaveBeenCalledTimes(1)
    expect(
      screen.queryByRole('button', { name: 'Conectar con Mercado Pago' })
    ).not.toBeInTheDocument()
    await screen.findByText('Cuenta conectada')
  })

  it('un fallo al renovar se ve en el cartel compartido', async () => {
    gateway = { provider: 'mercadopago', configured: true, oauth_supported: true }
    refreshOAuth.mockRejectedValue(new Error('boom'))
    renderSettings()
    openTab('Mercado Pago')

    fireEvent.click(screen.getByRole('button', { name: 'Renovar acceso' }))

    expect(
      await screen.findByText('No se pudo renovar el acceso de Mercado Pago')
    ).toBeInTheDocument()
  })

  it('"Guardar condiciones" guarda la politica de sena por el PATCH de la tienda', async () => {
    gateway = { provider: 'mercadopago', configured: true, oauth_supported: true }
    renderSettings()
    openTab('Mercado Pago')

    fireEvent.change(screen.getByPlaceholderText(/La seña equivale al 30%/), {
      target: { value: 'Se devuelve con 24 horas.' }
    })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Guardar condiciones/ }))

    expect(await screen.findByRole('button', { name: /Guardado/ })).toBeInTheDocument()
    expect(updateStore).toHaveBeenCalledWith({
      deposit_policy: 'Se devuelve con 24 horas.',
      allow_manual_coordination: false
    })
  })
})

// Lo que cada pestana bloquea con la tienda suspendida (FF-15) y lo que no:
// editar sigue, lo que se apaga es lo que escribe (Guardar, el logo, los flags).
describe('Settings - solo lectura por pestana', () => {
  const expectBlocked = (element: HTMLElement) => {
    expect(element).toBeDisabled()
    expect(element).toHaveAttribute('title', 'Tienda suspendida')
  }

  beforeEach(() => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    gateway = { provider: 'mercadopago', configured: false, oauth_supported: true }
  })

  it.each(['Identidad', 'Horarios', 'Políticas', 'Notificaciones', 'Funciones'])(
    '%s: Guardar Cambios queda apagado con el motivo',
    (tab) => {
      renderSettings()
      openTab(tab)

      expectBlocked(screen.getByRole('button', { name: 'Guardar Cambios' }))
    }
  )

  it('Notificaciones y Horarios se pueden editar aunque no guardar', () => {
    renderSettings()
    openTab('Notificaciones')
    for (const toggle of screen.getAllByRole('switch')) {
      expect(toggle).not.toBeDisabled()
    }
    openTab('Horarios')
    expect(screen.getByRole('button', { name: 'Abrir Martes' })).not.toBeDisabled()
  })

  it('Mercado Pago: conectar sigue permitido y "Guardar condiciones" no', () => {
    renderSettings()
    openTab('Mercado Pago')

    expect(screen.getByRole('button', { name: 'Conectar con Mercado Pago' })).not.toBeDisabled()
    expectBlocked(screen.getByRole('button', { name: /Guardar condiciones/ }))
  })
})

// 2026-10-02, QA en navegador (S\52): con los cobros apagados, el 403 de
// /payments/gateway-config pintaba "Esta función no está habilitada" en rojo
// arriba de TODAS las pestanas, y la de Seguridad quedaba cortada.
describe('Settings - cobros apagados', () => {
  const featureDisabled = () =>
    new ForbiddenError('Funcion deshabilitada', { errorCode: 'FEATURE_DISABLED', statusCode: 403 })

  it('el aviso no aparece fuera de la pestana Mercado Pago', () => {
    gatewayError = featureDisabled()
    renderSettings()

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(/no está habilitada/)).not.toBeInTheDocument()
  })

  it('en Mercado Pago es un estado informativo, no un error', () => {
    gatewayError = featureDisabled()
    renderSettings()
    openTab('Mercado Pago')

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/cobros online están apagados/i)
    expect(screen.getByRole('button', { name: 'Conectar con Mercado Pago' })).toBeDisabled()
  })

  it('otro error de la cuenta de Mercado Pago se avisa en su pestana', () => {
    gatewayError = new ForbiddenError('x', { errorCode: 'HTTP_ERROR', statusCode: 500 })
    renderSettings()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    openTab('Mercado Pago')

    expect(screen.getByRole('alert')).toHaveTextContent(
      'No se pudo cargar la cuenta de Mercado Pago.'
    )
  })

  it('las pestanas pasan de linea en vez de cortar Seguridad', () => {
    renderSettings()

    const barra = screen.getByRole('button', { name: /Seguridad/ }).parentElement as HTMLElement
    expect(barra.className).toContain('flex-wrap')
    expect(barra.className).not.toContain('overflow-x-auto')
  })
})
