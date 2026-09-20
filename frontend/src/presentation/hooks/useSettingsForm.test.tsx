import { act, renderHook } from '@testing-library/react'

import type { StoreSettings } from '@application/services/StoreSettingsService'

import { useSettingsForm } from './useSettingsForm'

/**
 * El hook no usa react-query: recibe `store` y `flags` como argumentos planos,
 * asi que se renderiza sin provider ni mocks. Lo que se prueba es el shim de
 * `setFormData`, que emula la firma de `useState` (objeto y funcion) encima de
 * un borrador de solo-lo-cambiado.
 */
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

const renderForm = (initialStore: StoreSettings | undefined) =>
  renderHook(({ current }) => useSettingsForm(current, undefined), {
    initialProps: { current: initialStore }
  })

describe('setFormData en su forma de objeto', () => {
  it('deja en el borrador solo la clave editada', () => {
    const { result } = renderForm(store)

    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: 'Otro nombre' })
    })

    expect(result.current.draft).toEqual({ name: 'Otro nombre' })
    expect(result.current.formData?.name).toBe('Otro nombre')
    expect(result.current.hasChanges).toBe(true)
  })
})

describe('setFormData en su forma de funcion', () => {
  it('toma el formulario actual, como hace handleMediaUpload despues del await', () => {
    const { result } = renderForm(store)

    act(() => {
      result.current.setFormData((prev) => (prev ? { ...prev, logo_url: 'u' } : prev))
    })

    expect(result.current.draft).toEqual({ logo_url: 'u' })
  })

  it('un null devuelto por el guard no toca el borrador', () => {
    const { result } = renderForm(store)

    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: 'Otro nombre' })
    })
    act(() => {
      result.current.setFormData(() => null)
    })

    expect(result.current.draft).toEqual({ name: 'Otro nombre' })
  })
})

describe('el borrador acumula ediciones y se vacia solo cuando corresponde', () => {
  it('dos ediciones seguidas se suman en vez de pisarse', () => {
    const { result } = renderForm(store)

    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: 'Otro nombre' })
    })
    act(() => {
      result.current.setFormData({ ...result.current.formData!, buffer_minutes: 45 })
    })

    expect(result.current.draft).toEqual({ name: 'Otro nombre', buffer_minutes: 45 })
  })

  it('volver a tipear el valor del servidor vacia el borrador', () => {
    const { result } = renderForm(store)

    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: 'Otro nombre' })
    })
    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: store.name })
    })

    expect(result.current.draft).toEqual({})
    expect(result.current.hasChanges).toBe(false)
  })

  it('resetDraft lo limpia', () => {
    const { result } = renderForm(store)

    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: 'Otro nombre' })
    })
    act(() => {
      result.current.resetDraft()
    })

    expect(result.current.draft).toEqual({})
    expect(result.current.hasChanges).toBe(false)
  })
})

describe('un refetch de fondo no pisa lo que el admin esta editando', () => {
  it('la clave del borrador gana y la que no esta en el borrador toma el servidor', () => {
    const { result, rerender } = renderForm(store)

    act(() => {
      result.current.setFormData({ ...result.current.formData!, name: 'Lo que estoy tipeando' })
    })

    rerender({
      current: { ...store, name: 'Nombre del servidor', buffer_minutes: 45 }
    })

    expect(result.current.formData?.name).toBe('Lo que estoy tipeando')
    expect(result.current.formData?.buffer_minutes).toBe(45)
  })
})

describe('sin tienda todavia', () => {
  it('no hay formulario y setFormData no rompe', () => {
    const { result } = renderForm(undefined)

    expect(result.current.formData).toBeNull()
    act(() => {
      result.current.setFormData(null)
    })
    expect(result.current.draft).toEqual({})
  })
})
