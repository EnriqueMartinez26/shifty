type Analytics = typeof import('./bookingAnalytics')
type TestWindow = Window & { dataLayer?: Array<ArrayLike<unknown>>; gtag?: jest.Mock }
const target = window as TestWindow
let analytics: Analytics

const commands = () => target.dataLayer?.map((entry) => Array.from(entry)) ?? []
const events = () => commands().filter((entry) => entry[0] === 'event')
const load = () => {
  const tag = document.querySelector<HTMLScriptElement>('script[src*="googletagmanager"]')
  if (!tag) throw new Error('No se cargo el tag')
  tag.dispatchEvent(new Event('load'))
  return tag
}

beforeEach(async () => {
  jest.resetModules()
  analytics = await import('./bookingAnalytics')
  const env = await import('@shared/utils/env')
  jest.mocked(env.getGa4MeasurementId).mockReturnValue('G-ABCD1234')
  localStorage.clear()
  document.head.querySelectorAll('script[src*="googletagmanager"]').forEach((tag) => tag.remove())
  target.dataLayer = undefined
  target.gtag = undefined
  window.history.replaceState(null, '', '/booking/tienda?token=secret&email=ana@example.com#otp')
})

it.each([undefined, '', 'GTM-ABCDE', 'G-<script>'])(
  'queda apagado sin un ID valido: %s',
  async (id) => {
    const env = await import('@shared/utils/env')
    jest.mocked(env.getGa4MeasurementId).mockReturnValue(id)
    analytics.enterBookingAnalytics()
    analytics.setAnalyticsConsent('accepted')
    analytics.trackBookingEvent('service_selected')
    expect(document.querySelector('script[src*="googletagmanager"]')).toBeNull()
    expect(events()).toEqual([])
    expect(analytics.isAnalyticsConfigured()).toBe(false)
  }
)

it('no crea scripts ni cola antes de aceptar; rechazar tampoco contacta a Google', () => {
  analytics.enterBookingAnalytics()
  analytics.trackBookingEvent('service_selected')
  analytics.setAnalyticsConsent('rejected')
  expect(document.querySelector('script[src*="googletagmanager"]')).toBeNull()
  expect(target.dataLayer).toBeUndefined()
})

it('solo transmite nombres permitidos y pagina fija, sin URL real ni datos de reserva', () => {
  document.title = 'Ana 5491111111111'
  analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  const tag = load()
  expect(tag.referrerPolicy).toBe('no-referrer')
  analytics.trackBookingEvent('service_selected')
  analytics.trackBookingEvent('slot_selected')
  analytics.trackBookingCreated('appt-secret')
  // Un caller JS hostil no puede agregar propiedades ni un evento arbitrario.
  const untyped = analytics.trackBookingEvent as (name: string, data: object) => void
  untyped('service_selected', { email: 'ana@example.com', phone: '5491111111111' })
  untyped('form_submit', { otp: '123456' })
  const serialized = JSON.stringify(commands())
  for (const forbidden of ['secret', 'ana@example.com', '5491111111111', '123456', 'form_submit']) {
    expect(serialized).not.toContain(forbidden)
  }
  expect(commands()).toContainEqual([
    'config',
    'G-ABCD1234',
    expect.objectContaining({
      send_page_view: false,
      allow_google_signals: false,
      page_location: `${window.location.origin}/booking`,
      page_referrer: '',
      page_title: 'Reserva de turno'
    })
  ])
})

it('deduplica el mismo exito backend sin transmitir ni persistir su id', () => {
  analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  load()
  analytics.trackBookingCreated('appt-1')
  analytics.trackBookingCreated('appt-1')
  analytics.trackBookingCreated('appt-2')
  expect(events().filter((entry) => entry[1] === 'booking_created')).toHaveLength(2)
  expect(JSON.stringify(commands())).not.toContain('appt-')
  expect(localStorage.length).toBe(1)
})

it('revocar bloquea eventos y elimina solo cookies de esta integracion', () => {
  analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  load()
  document.cookie = 'shifty_ga=identifier; path=/'
  document.cookie = 'shifty_ga_ABCD1234=session; path=/'
  document.cookie = 'necessary=retained; path=/'
  const before = events().length
  analytics.setAnalyticsConsent('rejected')
  analytics.trackBookingEvent('slot_selected')
  expect(events()).toHaveLength(before)
  expect(Reflect.get(window, 'ga-disable-G-ABCD1234')).toBe(true)
  expect(document.cookie).not.toContain('shifty_ga')
  expect(document.cookie).toContain('necessary=retained')
  expect(analytics.readAnalyticsConsent()).toBe('rejected')
  document.cookie = 'necessary=; Max-Age=0; path=/'
})

it('al salir hacia login, panel o mis turnos bloquea el tag cargado y no manda eventos', () => {
  const leave = analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  load()
  leave()
  const before = events().length
  for (const path of ['/login', '/dashboard', '/reset-password', '/booking/tienda/mis-turnos']) {
    window.history.replaceState(null, '', `${path}?token=secret`)
    expect(analytics.isBookingAnalyticsPath(path)).toBe(false)
    analytics.trackBookingEvent('booking_error')
  }
  expect(events()).toHaveLength(before)
  expect(Reflect.get(window, 'ga-disable-G-ABCD1234')).toBe(true)
})

it('una revocacion mientras carga no habilita el tag cuando llega la respuesta', () => {
  analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  const tag = document.querySelector<HTMLScriptElement>('script[src*="googletagmanager"]')
  analytics.setAnalyticsConsent('rejected')
  tag?.dispatchEvent(new Event('load'))
  expect(events()).toEqual([])
  expect(Reflect.get(window, 'ga-disable-G-ABCD1234')).toBe(true)
})

it('respeta una revocacion de otra pestaña al volver al portal', () => {
  const leave = analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  load()
  leave()
  localStorage.setItem(analytics.ANALYTICS_CONSENT_KEY, 'rejected')
  const before = events().length
  analytics.enterBookingAnalytics()
  analytics.trackBookingEvent('slot_selected')
  expect(events()).toHaveLength(before)
  expect(Reflect.get(window, 'ga-disable-G-ABCD1234')).toBe(true)
})

it('ignora la respuesta de un script retirado aunque se vuelva a aceptar', () => {
  analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  const old = document.querySelector<HTMLScriptElement>('script[src*="googletagmanager"]')
  analytics.setAnalyticsConsent('rejected')
  analytics.setAnalyticsConsent('accepted')
  old?.dispatchEvent(new Event('load'))
  expect(events()).toEqual([])
  load()
  expect(events().map((entry) => entry[1])).toEqual(['booking_started'])
})

it('un script bloqueado o gtag fallando nunca interrumpe la reserva', () => {
  analytics.enterBookingAnalytics()
  analytics.setAnalyticsConsent('accepted')
  document.querySelector('script[src*="googletagmanager"]')?.dispatchEvent(new Event('error'))
  expect(() => analytics.trackBookingCreated('appt-failed')).not.toThrow()
  analytics.setAnalyticsConsent('accepted')
  load()
  target.gtag = jest.fn(() => {
    throw new Error('blocked')
  })
  expect(() => analytics.trackBookingEvent('slot_selected')).not.toThrow()
})

it('con storage bloqueado mantiene la eleccion durante la visita', () => {
  analytics.enterBookingAnalytics()
  const get = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  const set = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  try {
    expect(() => analytics.setAnalyticsConsent('accepted')).not.toThrow()
    load()
    expect(events().map((entry) => entry[1])).toEqual(['booking_started'])
  } finally {
    get.mockRestore()
    set.mockRestore()
  }
})
