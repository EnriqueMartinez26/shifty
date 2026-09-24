import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import type { StoreSettings } from '@application/services/StoreSettingsService'

import SettingsPage from './Settings'

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
let storeQuery: { data?: StoreSettings; isLoading: boolean; error: unknown } = {
  data: store,
  isLoading: false,
  error: null
}
const idleMutation = { mutateAsync: jest.fn(), isPending: false }

jest.mock('../hooks/useStores', () => ({
  useStoreSettings: () => storeQuery,
  useStoreFeatureFlags: () => ({ data: undefined }),
  useUpdateStoreSettings: () => ({ mutateAsync: updateStore, isPending: false }),
  useUpdateStoreFeatureFlags: () => idleMutation,
  useUploadStoreLogo: () => idleMutation
}))

jest.mock('../hooks/usePayments', () => ({
  useGatewayConfig: () => ({ data: undefined, isLoading: false }),
  useStartMercadoPagoOAuth: () => idleMutation,
  useRefreshMercadoPagoOAuth: () => idleMutation,
  useDisconnectMercadoPagoOAuth: () => idleMutation
}))

jest.mock('../hooks/useChangePassword', () => ({
  useChangePassword: () => idleMutation
}))

jest.mock('../hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: [] })
}))

const renderSettings = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/settings']}>
      <SettingsPage />
    </MemoryRouter>
  )

describe('SettingsPage - Guardar Cambios (N3)', () => {
  beforeEach(() => {
    updateStore.mockReset()
    storeQuery = { data: store, isLoading: false, error: null }
  })

  it('sin nada editado el boton esta apagado y no llama a ningun endpoint', () => {
    renderSettings()

    const guardar = screen.getByRole('button', { name: 'Guardar Cambios' })
    expect(guardar).toBeDisabled()

    fireEvent.click(guardar)
    expect(updateStore).not.toHaveBeenCalled()
  })

  it('con un cambio el boton se habilita y guarda solo lo editado', () => {
    updateStore.mockResolvedValue(store)
    renderSettings()

    fireEvent.change(screen.getByDisplayValue('Peluqueria Tucuman'), {
      target: { value: 'Otro nombre' }
    })
    const guardar = screen.getByRole('button', { name: 'Guardar Cambios' })
    expect(guardar).not.toBeDisabled()

    fireEvent.click(guardar)
    expect(updateStore).toHaveBeenCalledWith({ name: 'Otro nombre' })
  })
})

describe('SettingsPage - botones (F11b-26)', () => {
  beforeEach(() => {
    storeQuery = { data: store, isLoading: false, error: null }
  })

  // Un <button> sin type es submit: movido dentro de un <form> lo envia.
  it('ningun boton de ninguna pestana queda con el type implicito', () => {
    const { container } = renderSettings()
    const tabs = [
      'Identidad',
      'Horarios',
      'Políticas',
      'Notificaciones',
      'Funciones',
      'Mercado Pago',
      'Seguridad'
    ]

    for (const tab of tabs) {
      fireEvent.click(screen.getByRole('button', { name: tab }))
      expect(container.querySelectorAll('button:not([type])')).toHaveLength(0)
    }
  })
})

describe('SettingsPage - error de carga (N2)', () => {
  it('si falla la configuracion lo dice, en vez de quedarse cargando para siempre', () => {
    storeQuery = { data: undefined, isLoading: false, error: new Error('500') }
    renderSettings()

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar la configuración.')
    expect(screen.queryByText('Cargando configuración...')).not.toBeInTheDocument()
  })
})
