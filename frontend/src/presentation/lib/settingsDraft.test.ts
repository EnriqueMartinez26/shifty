import type { StoreSettings } from '@application/services/StoreSettingsService'

import { buildSettingsBase, mergeDraft, narrowDraft, planSave } from './settingsDraft'

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
  custom_client_fields: [{ key: 'dni', label: 'DNI', type: 'text', required: true, options: [] }],
  cancellation_hours: 24,
  min_booking_notice_hours: 2,
  buffer_minutes: 10,
  allow_manual_coordination: true,
  deposit_policy: null,
  deposit_far_notice_days: 0,
  deposit_far_notice_extra_percent: 0,
  deposit_new_client_extra_percent: 0,
  deposit_absent_client_extra_percent: 0,
  business_hours: {
    mon: [
      { open: '09:00', close: '13:00' },
      { open: '17:00', close: '21:00' }
    ]
  },
  send_email_confirmation: true,
  send_email_reminders: false,
  feature_flags: {
    payments: true,
    ledger: false,
    advanced_reports: false,
    new_calendar: true,
    otp_booking: false
  }
}

const base = buildSettingsBase(store, undefined)

describe('base que arma el formulario desde el servidor', () => {
  it('reemplaza los nulos por vacios para que los inputs sigan controlados', () => {
    expect(base.logo_url).toBe('')
    expect(base.description).toBe('')
    expect(base.deposit_policy).toBe('')
  })

  it('prefiere los flags del endpoint dedicado sobre los que trae la tienda', () => {
    const conFlags = buildSettingsBase(store, {
      payments: false,
      ledger: true,
      advanced_reports: false,
      new_calendar: false,
      otp_booking: false
    })
    expect(conFlags.feature_flags.ledger).toBe(true)
    expect(conFlags.feature_flags.payments).toBe(false)
  })

  it('cae en todos los flags apagados cuando no hay ninguno', () => {
    const sinFlags = buildSettingsBase({ ...store, feature_flags: undefined }, undefined)
    expect(sinFlags.feature_flags).toEqual({
      payments: false,
      ledger: false,
      advanced_reports: false,
      new_calendar: false,
      otp_booking: false
    })
  })
})

describe('borrador: se queda solo con lo que el admin toco', () => {
  it('un formulario identico al servidor no ensucia nada', () => {
    expect(narrowDraft(base, { ...base })).toEqual({})
  })

  it('guarda la clave editada y ninguna otra', () => {
    expect(narrowDraft(base, { ...base, name: 'Otro nombre' })).toEqual({ name: 'Otro nombre' })
  })

  it('un array de campos personalizados igual pero recreado no cuenta como cambio', () => {
    const next = {
      ...base,
      custom_client_fields: base.custom_client_fields.map((field) => ({ ...field }))
    }
    expect(narrowDraft(base, next)).toEqual({})
  })

  it('un horario igual pero recreado tampoco cuenta como cambio', () => {
    const next = {
      ...base,
      business_hours: {
        mon: (base.business_hours.mon ?? []).map((period) => ({ ...period }))
      }
    }
    expect(narrowDraft(base, next)).toEqual({})
  })

  it('detecta el cambio adentro de un horario, no solo la referencia', () => {
    const next = {
      ...base,
      business_hours: {
        mon: [
          { open: '10:00', close: '13:00' },
          { open: '17:00', close: '21:00' }
        ]
      }
    }
    expect(narrowDraft(base, next).business_hours).toEqual(next.business_hours)
  })

  it('detecta un tramo de horario de menos', () => {
    const next = { ...base, business_hours: { mon: [{ open: '09:00', close: '13:00' }] } }
    expect(Object.keys(narrowDraft(base, next))).toEqual(['business_hours'])
  })

  it('un flag dado vuelta ensucia feature_flags', () => {
    const next = { ...base, feature_flags: { ...base.feature_flags, ledger: true } }
    expect(Object.keys(narrowDraft(base, next))).toEqual(['feature_flags'])
  })
})

describe('plan de guardado: que endpoints se llaman y con que cuerpo', () => {
  it('sin nada sucio no llama a ningun endpoint', () => {
    expect(planSave(base, {})).toEqual({ order: 'store-first' })
  })

  it('con el nombre editado manda solo el nombre y no toca los flags', () => {
    const plan = planSave(base, { name: 'Otro nombre' })
    expect(plan.store).toEqual({ name: 'Otro nombre' })
    expect('flags' in plan).toBe(false)
  })

  it('con un flag dado vuelta manda ese flag solo, nunca los cinco', () => {
    const plan = planSave(base, { feature_flags: { ...base.feature_flags, ledger: true } })
    expect(plan.flags).toEqual({ ledger: true })
    expect('store' in plan).toBe(false)
  })

  it('con las dos mitades sucias arma las dos, cada una con lo suyo', () => {
    const plan = planSave(base, {
      name: 'Otro nombre',
      feature_flags: { ...base.feature_flags, otp_booking: true }
    })
    expect(plan.store).toEqual({ name: 'Otro nombre' })
    expect(plan.flags).toEqual({ otp_booking: true })
  })

  it('un feature_flags sucio que en realidad no cambio ningun flag no llama al endpoint', () => {
    const plan = planSave(base, { feature_flags: { ...base.feature_flags } })
    expect('flags' in plan).toBe(false)
  })
})

describe('el plan se re-angosta contra la base actual antes de mandar nada', () => {
  it('descarta una clave del borrador que ya coincide con el servidor', () => {
    const plan = planSave(base, { name: base.name, buffer_minutes: 45 })
    expect(plan.store).toEqual({ buffer_minutes: 45 })
  })

  it('un borrador entero que ya coincide con el servidor no llama a ningun endpoint', () => {
    const plan = planSave(base, { name: base.name })
    expect('store' in plan).toBe(false)
  })

  it('al reintentar tras una falla parcial no vuelve a mandar lo ya guardado', () => {
    // El PATCH de tienda anduvo y el PUT de flags exploto: el borrador se
    // conserva a proposito, pero la invalidacion de ['store-settings'] ya
    // refresco la base con el nombre nuevo. El reintento no debe pisarlo.
    const draft = narrowDraft(base, {
      ...base,
      name: 'Nombre nuevo',
      feature_flags: { ...base.feature_flags, ledger: true }
    })
    const baseRefrescada = buildSettingsBase({ ...store, name: 'Nombre nuevo' }, undefined)

    const plan = planSave(baseRefrescada, draft)

    expect('store' in plan).toBe(false)
    expect(plan.flags).toEqual({ ledger: true })
  })

  it('no manda el nombre viejo cuando otro admin ya lo cambio en el servidor', () => {
    const draft = narrowDraft(base, { ...base, name: 'Nombre nuevo' })
    const baseDeOtroAdmin = buildSettingsBase({ ...store, name: 'Nombre nuevo' }, undefined)
    expect(planSave(baseDeOtroAdmin, draft)).toEqual({ order: 'store-first' })
  })
})

describe('orden de guardado: cada endpoint valida contra el estado del otro', () => {
  const sinCobros = buildSettingsBase(store, {
    payments: false,
    ledger: false,
    advanced_reports: false,
    new_calendar: false,
    otp_booking: false
  })

  it('prender los cobros manda la tienda primero, asi la politica ya esta en la base', () => {
    const plan = planSave(sinCobros, {
      deposit_policy: 'Se cobra el 50%',
      feature_flags: { ...sinCobros.feature_flags, payments: true }
    })
    expect(plan.order).toBe('store-first')
  })

  it('apagar los cobros manda los flags primero, asi el PATCH ya no los ve activos', () => {
    // Tienda con cobros activos y politica publicada: apagar las dos cosas de
    // un saque es el caso que fallaba siempre con DEPOSIT_POLICY_REQUIRED.
    const conCobros = buildSettingsBase({ ...store, deposit_policy: 'Se cobra el 50%' }, undefined)
    const plan = planSave(conCobros, {
      deposit_policy: '',
      feature_flags: { ...conCobros.feature_flags, payments: false }
    })
    expect(plan.order).toBe('flags-first')
    expect(plan.store).toEqual({ deposit_policy: '' })
    expect(plan.flags).toEqual({ payments: false })
  })

  it('un borrador que no toca payments queda en store-first, donde el orden da igual', () => {
    const plan = planSave(base, {
      name: 'Otro nombre',
      feature_flags: { ...base.feature_flags, ledger: true }
    })
    expect(plan.order).toBe('store-first')
  })
})

describe('el refetch del servidor no puede pisar una edicion sin guardar', () => {
  it('la clave editada sobrevive aunque el servidor devuelva otra cosa', () => {
    const draft = narrowDraft(base, { ...base, name: 'Lo que estoy tipeando' })
    const baseNueva = buildSettingsBase({ ...store, name: 'Nombre viejo del servidor' }, undefined)
    expect(mergeDraft(baseNueva, draft).name).toBe('Lo que estoy tipeando')
  })

  it('una clave que el admin no toco sí toma el valor nuevo del servidor', () => {
    const draft = narrowDraft(base, { ...base, name: 'Lo que estoy tipeando' })
    const baseNueva = buildSettingsBase({ ...store, buffer_minutes: 45 }, undefined)
    expect(mergeDraft(baseNueva, draft).buffer_minutes).toBe(45)
  })
})
