import { getGa4MeasurementId } from '@shared/utils/env'

export type AnalyticsConsent = 'accepted' | 'rejected' | null
type BookingEvent =
  'booking_started' | 'service_selected' | 'slot_selected' | 'availability_empty' | 'booking_error'
type Gtag = (...args: unknown[]) => void
type AnalyticsWindow = Window & {
  dataLayer?: unknown[]
  gtag?: Gtag
}

export const ANALYTICS_CONSENT_KEY = 'shifty:analytics-consent:v1'
const EVENTS = new Set<BookingEvent>([
  'booking_started',
  'service_selected',
  'slot_selected',
  'availability_empty',
  'booking_error'
])
let consent: AnalyticsConsent = null
let active = false
let ready = false
let loaded = false
let configured = false
let started = false
let script: HTMLScriptElement | null = null
const reportedBookings = new Set<string>()

const analyticsWindow = (): AnalyticsWindow => window as AnalyticsWindow
const measurementId = (): string | null => {
  const id = getGa4MeasurementId()?.trim()
  return id && /^G-[A-Z0-9]{4,20}$/.test(id) ? id : null
}

export const isAnalyticsConfigured = (): boolean => measurementId() !== null
export const isBookingAnalyticsPath = (pathname: string): boolean =>
  /^\/(?:booking|b)\/[^/]+\/?$/.test(pathname)

export const readAnalyticsConsent = (): AnalyticsConsent => {
  try {
    const value = localStorage.getItem(ANALYTICS_CONSENT_KEY)
    return value === 'accepted' || value === 'rejected' ? value : null
  } catch {
    return consent
  }
}

// No se usa la URL, el titulo ni el referrer del navegador: pueden tener
// tokens o datos de cliente. Tampoco se aceptan propiedades del formulario.
const safePage = () => ({
  page_location: `${window.location.origin}/booking`,
  page_referrer: '',
  page_title: 'Reserva de turno'
})

const send = (event: BookingEvent | 'booking_created'): void => {
  if (!ready || !active || consent !== 'accepted') return
  if (!isBookingAnalyticsPath(window.location.pathname)) return
  const id = measurementId()
  if (!id) return
  try {
    analyticsWindow().gtag?.('event', event, { send_to: id, ...safePage() })
  } catch {
    // La medicion nunca puede interrumpir una reserva.
  }
}

export const trackBookingEvent = (event: BookingEvent): void => {
  if (EVENTS.has(event)) send(event)
}

/** El id solo deduplica en memoria; nunca sale hacia Google ni se persiste. */
export const trackBookingCreated = (publicId: string): void => {
  if (!publicId || reportedBookings.has(publicId)) return
  reportedBookings.add(publicId)
  send('booking_created')
}

const stop = (): void => {
  ready = false
  const id = measurementId()
  if (id) Reflect.set(window, `ga-disable-${id}`, true)
  if (!loaded) {
    script?.remove()
    script = null
    // No se reproduce el comportamiento previo al consentimiento.
    if (analyticsWindow().dataLayer) analyticsWindow().dataLayer = []
  }
}

const configure = (target: AnalyticsWindow, id: string): void => {
  if (configured) return
  target.gtag?.('consent', 'default', {
    analytics_storage: 'granted',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied'
  })
  target.gtag?.('js', new Date())
  target.gtag?.('config', id, {
    ...safePage(),
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    ignore_referrer: true,
    cookie_prefix: 'shifty',
    cookie_domain: 'none',
    cookie_expires: 30 * 24 * 60 * 60,
    campaign_id: '',
    campaign_name: '',
    campaign_source: '',
    campaign_medium: '',
    campaign_term: '',
    campaign_content: ''
  })
  configured = true
}

const begin = (target: AnalyticsWindow, id: string): void => {
  configure(target, id)
  Reflect.set(target, `ga-disable-${id}`, false)
  ready = true
  if (!started) {
    started = true
    send('booking_started')
  }
}

const start = (): void => {
  const id = measurementId()
  if (!id || !active || consent !== 'accepted') return
  try {
    const target = analyticsWindow()
    if (loaded) {
      begin(target, id)
      return
    }
    if (script) return
    Reflect.set(target, `ga-disable-${id}`, true)
    target.dataLayer = []
    // gtag usa arguments (no un array) en su protocolo de cola.
    target.gtag = function (...args: unknown[]) {
      // arguments requiere funcion regular; args mantiene la firma tipada.
      if (args.length) target.dataLayer?.push(arguments)
    }
    script = document.createElement('script')
    script.async = true
    script.referrerPolicy = 'no-referrer'
    script.src = `https://www.googletagmanager.com/gtag/js?id=${id}`
    const pendingScript = script
    script.onload = () => {
      if (script !== pendingScript) return
      loaded = true
      if (!active || consent !== 'accepted') return
      try {
        begin(target, id)
      } catch {
        stop()
      }
    }
    script.onerror = () => {
      if (script === pendingScript) stop()
    }
    document.head.appendChild(script)
  } catch {
    stop()
  }
}

export const setAnalyticsConsent = (value: AnalyticsConsent, persist = true): void => {
  consent = value
  try {
    if (persist) {
      if (value) localStorage.setItem(ANALYTICS_CONSENT_KEY, value)
      else localStorage.removeItem(ANALYTICS_CONSENT_KEY)
    }
  } catch {
    // En storage bloqueado la eleccion dura solo durante esta visita.
  }
  if (value === 'accepted') start()
  else {
    stop()
    // Solo las cookies creadas por esta integracion (host actual, path /).
    try {
      for (const item of document.cookie.split(';')) {
        const name = item.trim().split('=')[0]
        if (name && /^shifty_ga(?:_|$)/.test(name)) {
          document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`
        }
      }
    } catch {
      // Sin cookies accesibles, sigue deshabilitada la recoleccion.
    }
  }
}

/** Se monta solo en el portal de reserva; la salida bloquea el tag cargado. */
export const enterBookingAnalytics = (): (() => void) => {
  active = true
  // Otra pestaña puede haber revocado mientras esta estaba fuera del portal.
  consent = readAnalyticsConsent()
  start()
  return () => {
    active = false
    stop()
  }
}
