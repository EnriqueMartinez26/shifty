/**
 * Borrador de la configuracion de la tienda: que edito el admin y que hay que
 * mandarle al backend.
 *
 * La pagina de Configuracion tiene siete pestanas, un solo formulario y un
 * solo boton de guardar. Hasta 2026-09-18 ese formulario vivia en un
 * `useState` que un `useEffect` repoblaba entero desde el servidor. Eso daba
 * dos agujeros:
 *
 * 1. Guardar mandaba SOLO la mitad de la pestana abierta, asi que lo editado
 *    en las otras se descartaba en silencio con el boton diciendo "Guardado".
 * 2. Cualquier refetch (por ejemplo el que dispara la invalidacion de
 *    ['store-settings'] al guardar los flags) volvia a correr el efecto y
 *    pisaba lo que el admin estaba tipeando.
 *
 * El arreglo anterior (de4563d) se revirtio (08f7016) porque mandaba los
 * cinco feature flags en cada guardado: el merge del backend solo saltea los
 * campos `None` (`backend/core/feature_flags.py`), asi que pisaba lo que
 * hubiera cambiado otro admin.
 *
 * Por eso el estado ahora se parte en dos:
 *
 * - `base`: lo que dice el servidor (`buildSettingsBase`).
 * - `draft`: SOLO las claves que el admin toco de verdad.
 *
 * El formulario es `base + draft` calculado en el render, no un estado que
 * alguien repuebla. El servidor solo puede ganar en las claves que NO estan
 * en el borrador, y el guardado manda exactamente el borrador.
 */

import type {
  StoreCustomField,
  StoreFeatureFlags,
  StoreSettings,
  StoreUpdatePayload
} from '@application/services/StoreSettingsService'

import type { BusinessType } from '@shared/types/business'

export type BusinessHoursPeriod = {
  open: string
  close: string
}

export type SettingsFormData = {
  name: string
  slug: string
  business_type: BusinessType
  logo_url: string
  cover_url: string
  description: string
  whatsapp_number: string
  instagram_url: string
  facebook_url: string
  website_url: string
  custom_client_fields: StoreCustomField[]
  primary_color: string
  cancellation_hours: number
  min_booking_notice_hours: number
  buffer_minutes: number
  allow_manual_coordination: boolean
  deposit_policy: string
  deposit_far_notice_days: number
  deposit_far_notice_extra_percent: number
  deposit_new_client_extra_percent: number
  deposit_absent_client_extra_percent: number
  business_hours: Record<string, BusinessHoursPeriod[]>
  send_email_confirmation: boolean
  send_email_reminders: boolean
  feature_flags: StoreFeatureFlags
}

/** Una tienda vieja puede no traer flags todavia; apagados es el default. */
const DEFAULT_FEATURE_FLAGS: StoreFeatureFlags = {
  payments: false,
  ledger: false,
  advanced_reports: false,
  new_calendar: false,
  otp_booking: false
}

/**
 * Lo que dice el servidor, en la forma que consume el formulario. Los `|| ''`
 * y los `??` estan porque el formulario es controlado: un `null` del backend
 * convertiria el input en no controlado y React lo avisa en consola.
 */
export const buildSettingsBase = (
  store: StoreSettings,
  flags: StoreFeatureFlags | undefined
): SettingsFormData => ({
  name: store.name,
  slug: store.slug,
  business_type: store.business_type || 'generic',
  logo_url: store.logo_url || '',
  cover_url: store.cover_url || '',
  description: store.description || '',
  whatsapp_number: store.whatsapp_number || '',
  instagram_url: store.instagram_url || '',
  facebook_url: store.facebook_url || '',
  website_url: store.website_url || '',
  custom_client_fields: store.custom_client_fields || [],
  primary_color: store.primary_color,
  cancellation_hours: store.cancellation_hours,
  min_booking_notice_hours: store.min_booking_notice_hours ?? 2,
  buffer_minutes: store.buffer_minutes,
  allow_manual_coordination: store.allow_manual_coordination ?? true,
  deposit_policy: store.deposit_policy || '',
  deposit_far_notice_days: store.deposit_far_notice_days ?? 0,
  deposit_far_notice_extra_percent: store.deposit_far_notice_extra_percent ?? 0,
  deposit_new_client_extra_percent: store.deposit_new_client_extra_percent ?? 0,
  deposit_absent_client_extra_percent: store.deposit_absent_client_extra_percent ?? 0,
  business_hours: store.business_hours,
  send_email_confirmation: store.send_email_confirmation,
  send_email_reminders: store.send_email_reminders,
  feature_flags: flags || store.feature_flags || DEFAULT_FEATURE_FLAGS
})

/** Lo que ve el admin: el servidor, con sus ediciones sin guardar encima. */
export const mergeDraft = (
  base: SettingsFormData,
  draft: Partial<SettingsFormData>
): SettingsFormData => ({ ...base, ...draft })

/**
 * Comparacion estructural. Los handlers del formulario reconstruyen el objeto
 * entero en cada tecla (`{ ...formData, name }`), asi que `business_hours` y
 * `custom_client_fields` llegan siempre como referencias nuevas aunque su
 * contenido sea identico. Comparar por referencia marcaria todo como sucio y
 * el borrador dejaria de significar "lo que el admin toco".
 *
 * Se compara a mano en vez de sumar una dependencia: las formas son datos
 * planos de la API (primitivos, arrays y objetos simples), sin fechas, sets ni
 * ciclos.
 */
const isSameValue = (left: unknown, right: unknown): boolean => {
  if (left === right) return true
  if (left === null || right === null) return false
  if (typeof left !== 'object' || typeof right !== 'object') return false

  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right)) return false
    if (left.length !== right.length) return false
    return left.every((item, index) => isSameValue(item, right[index]))
  }

  const leftEntries = Object.entries(left as Record<string, unknown>)
  const rightRecord = right as Record<string, unknown>
  if (leftEntries.length !== Object.keys(rightRecord).length) return false
  return leftEntries.every(
    ([key, value]) => key in rightRecord && isSameValue(value, rightRecord[key])
  )
}

/**
 * Existe SOLO para que el asignado generico por `keyof` tipe: escrito inline
 * (`draft[key] = next[key]`) TypeScript no puede probar que el valor de la
 * clave `K` entra en la ranura de la clave `K` del destino y lo rechaza.
 */
const copyKey = <K extends keyof SettingsFormData>(
  target: Partial<SettingsFormData>,
  source: SettingsFormData,
  key: K
): void => {
  target[key] = source[key]
}

/**
 * De un formulario completo al borrador: quedan SOLO las claves cuyo valor
 * difiere del servidor. Es lo que despues se manda, y lo que protege las
 * ediciones de un refetch.
 */
export const narrowDraft = (
  base: SettingsFormData,
  next: SettingsFormData
): Partial<SettingsFormData> => {
  const draft: Partial<SettingsFormData> = {}
  for (const key of Object.keys(base) as (keyof SettingsFormData)[]) {
    if (!isSameValue(base[key], next[key])) copyKey(draft, next, key)
  }
  return draft
}

/**
 * En que orden se llaman las dos mitades. No es cosmetico: cada endpoint del
 * backend valida contra el estado ACTUAL en la base de la OTRA mitad.
 *
 * - `PATCH /stores/me` rechaza vaciar `deposit_policy` si los cobros estan
 *   prendidos en la base (`backend/modules/stores/router.py:111-121`).
 * - `PUT /stores/me/feature-flags` rechaza prender `payments` si la politica
 *   de sena esta vacia en la base (`.../router.py:198-204`).
 *
 * Asi que prender cobros exige la tienda primero (que la politica ya este
 * guardada) y apagarlos exige los flags primero (que la guarda del PATCH ya no
 * vea los cobros activos). Con el orden fijo anterior, "apagar cobros + borrar
 * la politica" en un mismo guardado fallaba SIEMPRE con DEPOSIT_POLICY_REQUIRED
 * y no habia forma de salir con el unico boton de guardar.
 */
export type SettingsSaveOrder = 'store-first' | 'flags-first'

export type SettingsSavePlan = {
  store?: StoreUpdatePayload
  flags?: Partial<StoreFeatureFlags>
  order: SettingsSaveOrder
}

const resolveSaveOrder = (
  base: SettingsFormData,
  fresh: Partial<SettingsFormData>
): SettingsSaveOrder =>
  fresh.feature_flags?.payments === false && base.feature_flags.payments
    ? 'flags-first'
    : 'store-first'

/**
 * Que endpoints hay que llamar, con que cuerpo y en que orden.
 *
 * Las dos mitades viajan como parciales porque el backend lo espera asi:
 * PATCH /stores/me y PUT /stores/me/feature-flags usan
 * `model_dump(exclude_unset=True)` y `merge_store_feature_flags` solo saltea
 * las claves con valor `None`. Mandar los cinco flags -que es lo que hacia el
 * commit revertido 08f7016- no es "mandar de mas": es pisar con lo que este
 * formulario tenia cacheado lo que otro admin haya cambiado mientras tanto.
 *
 * Una mitad sin cambios no aparece en el plan, asi que no se llama a su
 * endpoint.
 */
export const planSave = (
  base: SettingsFormData,
  draft: Partial<SettingsFormData>
): SettingsSavePlan => {
  // Re-angostar el borrador contra la base ACTUAL antes de armar nada. El
  // borrador sobrevive a una falla parcial a proposito (si el PATCH anduvo y
  // el PUT de flags exploto, `handleSave` vuelve sin `resetDraft` para no
  // perder lo editado), pero esa invalidacion de ['store-settings'] refresca
  // `base`: al reintentar, una clave YA guardada -o que otro admin cambio
  // mientras tanto- seguia viajando con el valor viejo y lo pisaba en
  // silencio. Es la misma perdida de actualizacion que hizo revertir de4563d
  // en 08f7016. Tambien cubre al admin que tipea un campo de vuelta al valor
  // del servidor. La mitad de flags ya se diferenciaba contra `base`; esto
  // saca la asimetria con la mitad de tienda.
  const fresh = narrowDraft(base, mergeDraft(base, draft))

  const plan: SettingsSavePlan = { order: resolveSaveOrder(base, fresh) }
  const { feature_flags: draftFlags, ...storeDraft } = fresh

  if (Object.keys(storeDraft).length > 0) plan.store = storeDraft

  if (draftFlags) {
    const flags: Partial<StoreFeatureFlags> = {}
    for (const key of Object.keys(base.feature_flags) as (keyof StoreFeatureFlags)[]) {
      if (draftFlags[key] !== base.feature_flags[key]) flags[key] = draftFlags[key]
    }
    if (Object.keys(flags).length > 0) plan.flags = flags
  }

  return plan
}
