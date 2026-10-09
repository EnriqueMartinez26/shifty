import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import type { StoreSettings } from '@application/services/StoreSettingsService'

import { ConflictError } from '@shared/errors/ConflictError'
import { ValidationError } from '@shared/errors/ValidationError'

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
const updateFeatureFlags = jest.fn()
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
  useUpdateStoreFeatureFlags: () => ({ mutateAsync: updateFeatureFlags, isPending: false }),
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

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
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

describe('SettingsPage - horarios (FF-08)', () => {
  beforeEach(() => {
    storeQuery = { data: store, isLoading: false, error: null }
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Horarios' }))
  })

  it('no hay "+ Bloque": un dia cerrado se abre con un solo periodo', () => {
    expect(screen.queryByText('Bloque')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Abrir Martes' }))

    expect(screen.getByLabelText<HTMLInputElement>('Apertura Martes').value).toBe('09:00')
    expect(screen.getByLabelText<HTMLInputElement>('Cierre Martes').value).toBe('18:00')
    expect(screen.queryByRole('button', { name: 'Abrir Martes' })).not.toBeInTheDocument()
  })

  it('tipear una hora no remonta el input (no se pierde el foco)', () => {
    const apertura = screen.getByLabelText<HTMLInputElement>('Apertura Lunes')

    fireEvent.change(apertura, { target: { value: '08:00' } })

    expect(screen.getByLabelText('Apertura Lunes')).toBe(apertura)
    expect(apertura.value).toBe('08:00')
  })

  it('apertura igual o posterior al cierre apaga Guardar y dice por que', () => {
    fireEvent.change(screen.getByLabelText('Cierre Lunes'), { target: { value: '09:00' } })

    expect(screen.getByRole('button', { name: 'Guardar Cambios' })).toBeDisabled()
    expect(screen.getByText(/No se puede guardar/)).toBeInTheDocument()
  })
})

describe('SettingsPage - logo', () => {
  it('rechaza en el cliente un PNG de 1,5 MB (el backend admite 1 MB)', () => {
    storeQuery = { data: store, isLoading: false, error: null }
    idleMutation.mutateAsync.mockReset()
    const { container } = renderSettings()
    const png = new File([new Uint8Array(1.5 * 1024 * 1024)], 'logo.png', { type: 'image/png' })

    fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [png] }
    })

    expect(screen.getByRole('alert')).toHaveTextContent('La imagen supera el máximo de 1 MB.')
    expect(idleMutation.mutateAsync).not.toHaveBeenCalled()
  })
})

describe('SettingsPage - slug repetido (409)', () => {
  const SLUG_TOMADO = 'Ese enlace ya lo usa otro negocio. Elegí otro.'
  const conflicto = () => new ConflictError('conflict', { errorCode: 'RESOURCE_CONFLICT' })

  beforeEach(() => {
    storeQuery = { data: store, isLoading: false, error: null }
    updateStore.mockReset()
    updateStore.mockRejectedValue(conflicto())
  })

  it('si solo cambio el slug, el 409 se atribuye al slug y se marca el campo', async () => {
    renderSettings()
    fireEvent.change(screen.getByLabelText('Slug de la URL'), { target: { value: 'otro-local' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

    // Una vez en el cartel de error y otra debajo del campo.
    expect(await screen.findAllByText(SLUG_TOMADO)).toHaveLength(2)
  })

  it('si tambien cambiaron los horarios, el 409 queda con el texto neutro', async () => {
    renderSettings()
    fireEvent.change(screen.getByLabelText('Slug de la URL'), { target: { value: 'otro-local' } })
    fireEvent.click(screen.getByRole('button', { name: 'Horarios' }))
    fireEvent.click(screen.getByRole('button', { name: 'Abrir Martes' }))
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

    expect(
      await screen.findByText(/Los datos chocan con un registro existente/)
    ).toBeInTheDocument()
    expect(screen.queryByText(SLUG_TOMADO)).not.toBeInTheDocument()
  })
})

// 2026-09-30 (FF-28): el panel mostraba interruptores que no hacen nada y decia
// SMS/WhatsApp para un codigo que va por email. `advanced_reports` y
// `new_calendar` no los lee ningun camino del backend; siguen en el contrato
// (`StoreFeatureFlags`), solo dejan de mostrarse.
describe('SettingsPage - funciones (FF-28)', () => {
  // Los dos flags ocultos prendidos en la base: guardar otra cosa no los
  // tiene que reenviar ni apagar.
  const conFlagsOcultos: StoreSettings = {
    ...store,
    feature_flags: {
      payments: false,
      ledger: false,
      advanced_reports: true,
      new_calendar: true,
      otp_booking: false
    }
  }

  beforeEach(() => {
    storeQuery = { data: conFlagsOcultos, isLoading: false, error: null }
    updateStore.mockReset()
    updateFeatureFlags.mockReset()
  })

  it('no muestra los interruptores que ningun camino del backend lee', () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Funciones' }))

    expect(screen.queryByText('Reportes avanzados')).not.toBeInTheDocument()
    expect(screen.queryByText('Agenda nueva')).not.toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: 'Reportes avanzados' })).not.toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: 'Agenda nueva' })).not.toBeInTheDocument()
  })

  it('dice que el codigo de la reserva publica va por email', () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Funciones' }))

    expect(screen.getByText('Código por email en la reserva pública')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Pide un código de verificación, enviado por email, antes de confirmar la reserva.'
      )
    ).toBeInTheDocument()
    expect(screen.queryByText(/SMS o WhatsApp/)).not.toBeInTheDocument()
  })

  it('guardar sin tocar ningun flag no llama a updateFeatureFlags', async () => {
    updateStore.mockResolvedValue(conFlagsOcultos)
    renderSettings()

    fireEvent.change(screen.getByDisplayValue('Peluqueria Tucuman'), {
      target: { value: 'Otro nombre' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Funciones' }))
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

    expect(await screen.findByRole('button', { name: 'Guardado' })).toBeInTheDocument()
    expect(updateStore).toHaveBeenCalledWith({ name: 'Otro nombre' })
    expect(updateFeatureFlags).not.toHaveBeenCalled()
  })
})

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15). PATCH /stores/me, PUT /stores/me/feature-flags y
// POST /stores/me/media no estan en SUSPENSION_ALLOWED_WRITES; cambiar la
// clave (PUT /auth/change-password) va por un router sin la guarda.
describe('SettingsPage - tienda suspendida (FF-15)', () => {
  const expectBlocked = (element: HTMLElement | null) => {
    expect(element).toHaveAttribute('title', 'Tienda suspendida')
  }

  beforeEach(() => {
    storeQuery = { data: store, isLoading: false, error: null }
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
  })

  afterEach(() => {
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('Guardar, Subir imagen y los interruptores de Funciones quedan deshabilitados', () => {
    const { container } = renderSettings()
    fireEvent.change(screen.getByDisplayValue('Peluqueria Tucuman'), {
      target: { value: 'Otro nombre' }
    })

    const guardar = screen.getByRole('button', { name: 'Guardar Cambios' })
    expect(guardar).toBeDisabled()
    expectBlocked(guardar)
    const logo = container.querySelector<HTMLInputElement>('input[type="file"]')
    expect(logo).toBeDisabled()
    expectBlocked(logo?.closest('label') ?? null)

    fireEvent.click(screen.getByRole('button', { name: 'Funciones' }))
    const switches = screen.getAllByRole('switch')
    expect(switches.length).toBeGreaterThan(0)
    for (const toggle of switches) {
      expect(toggle).toBeDisabled()
      expectBlocked(toggle)
    }
  })

  it('Mercado Pago: "Guardar condiciones" es el PATCH /stores/me y tambien se apaga', () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Mercado Pago' }))

    const guardar = screen.getByRole('button', { name: /Guardar condiciones/ })
    expect(guardar).toBeDisabled()
    expectBlocked(guardar)
  })

  it('Seguridad: cambiar la clave sigue habilitado', () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Seguridad' }))

    const actualizar = screen.getByRole('button', { name: 'Actualizar Acceso' })
    expect(actualizar).not.toBeDisabled()
    expect(actualizar).not.toHaveAttribute('title')
  })

  it('sin suspension Guardar se habilita con un cambio y los interruptores tambien', () => {
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
    renderSettings()
    fireEvent.change(screen.getByDisplayValue('Peluqueria Tucuman'), {
      target: { value: 'Otro nombre' }
    })

    expect(screen.getByRole('button', { name: 'Guardar Cambios' })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Funciones' }))
    for (const toggle of screen.getAllByRole('switch')) {
      expect(toggle).not.toBeDisabled()
    }
  })
})

describe('SettingsPage - dia legado con varios periodos', () => {
  const partido = {
    ...store,
    business_hours: {
      mon: [
        { open: '09:00', close: '13:00' },
        { open: '16:00', close: '20:00' }
      ]
    }
  }

  it('muestra los dos, frena el guardado con el motivo y "Conservar este" deja uno', () => {
    storeQuery = { data: partido, isLoading: false, error: null }
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Horarios' }))
    expect(screen.getByText('09:00 A 13:00')).toBeInTheDocument()
    expect(screen.getByText('16:00 A 20:00')).toBeInTheDocument()

    // Tocar OTRO dia reenvia el lunes legado: el guardado se frena.
    fireEvent.click(screen.getByRole('button', { name: 'Abrir Martes' }))
    expect(screen.getByRole('button', { name: 'Guardar Cambios' })).toBeDisabled()
    expect(screen.getByText(/El Lunes tiene 2 horarios guardados/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Conservar 16:00 a 20:00 el Lunes' }))
    expect(screen.getByLabelText<HTMLInputElement>('Apertura Lunes').value).toBe('16:00')
    expect(screen.getByRole('button', { name: 'Guardar Cambios' })).not.toBeDisabled()
  })
})

/**
 * Cambio de clave: valida la nueva antes de enviar; la actual conserva su contrato.
 * La NUEVA se valida con las reglas del backend antes de
 * enviar; la ACTUAL no se valida (1 a 128, la verifica el servidor).
 */
describe('SettingsPage - cambio de contraseña', () => {
  const abrirSeguridad = () => {
    storeQuery = { data: store, isLoading: false, error: null }
    idleMutation.mutateAsync.mockReset()
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Seguridad' }))
  }

  const completar = (actual: string, nueva: string, confirmar: string) => {
    fireEvent.change(screen.getByLabelText('Contraseña Actual'), { target: { value: actual } })
    fireEvent.change(screen.getByLabelText('Nueva Contraseña'), { target: { value: nueva } })
    fireEvent.change(screen.getByLabelText('Confirmar Nueva'), { target: { value: confirmar } })
    fireEvent.submit(screen.getByRole('button', { name: 'Actualizar Acceso' }).closest('form')!)
  }

  it('asocia cada label con su input y fija autocomplete y topes', () => {
    abrirSeguridad()

    const actual = screen.getByLabelText('Contraseña Actual')
    expect(actual).toHaveAttribute('type', 'password')
    expect(actual).toHaveAttribute('autocomplete', 'current-password')
    expect(actual).toHaveAttribute('maxlength', '256')
    expect(actual).not.toHaveAttribute('minlength')

    const nueva = screen.getByLabelText('Nueva Contraseña')
    expect(nueva).toHaveAttribute('type', 'password')
    expect(nueva).toHaveAttribute('autocomplete', 'new-password')
    expect(nueva).toHaveAttribute('minlength', '6')
    expect(nueva).toHaveAttribute('maxlength', '128')

    const confirmar = screen.getByLabelText('Confirmar Nueva')
    expect(confirmar).toHaveAttribute('type', 'password')
    expect(confirmar).toHaveAttribute('autocomplete', 'new-password')
    expect(confirmar).toHaveAttribute('maxlength', '128')
  })

  it('una clave nueva corta se rechaza en el cliente, sin llamar al servidor', async () => {
    abrirSeguridad()

    completar('vieja', 'ab12', 'ab12')

    expect(
      await screen.findByText('La contraseña debe tener al menos 6 caracteres')
    ).toBeInTheDocument()
    expect(idleMutation.mutateAsync).not.toHaveBeenCalled()
  })

  it('una clave nueva de más de 72 bytes se rechaza antes de enviar', async () => {
    abrirSeguridad()
    const nueva = `${'é'.repeat(36)}12`

    completar('vieja', nueva, nueva)

    expect(
      await screen.findByText(
        'La contraseña ocupa más de 72 bytes (los acentos, la ñ, los símbolos y los emojis ocupan más de uno)'
      )
    ).toBeInTheDocument()
    expect(idleMutation.mutateAsync).not.toHaveBeenCalled()
  })

  it('la clave actual no se valida: una vieja de 3 caracteres llega al servidor, sin recortar', async () => {
    abrirSeguridad()
    idleMutation.mutateAsync.mockResolvedValue(undefined)

    completar(' ab ', 'nueva123', 'nueva123')

    await waitFor(() => {
      expect(idleMutation.mutateAsync).toHaveBeenCalledWith({
        current_password: ' ab ',
        new_password: 'nueva123'
      })
    })
  })

  it('un 422 del servidor muestra un texto útil sobre la clave, no el genérico', async () => {
    abrirSeguridad()
    idleMutation.mutateAsync.mockRejectedValue(
      new ValidationError('body -> new_password: value error', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422
      })
    )

    completar('vieja', 'password123', 'password123')

    expect(
      await screen.findByText(
        'La contraseña no es aceptable: es demasiado común o no cumple las reglas. Elegí otra'
      )
    ).toBeInTheDocument()
  })
})
