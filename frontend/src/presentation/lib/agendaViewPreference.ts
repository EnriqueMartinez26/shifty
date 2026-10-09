import type { CalendarView } from '../components/organisms/calendar/AgendaToolbar'

/**
 * Vista de la agenda que eligio cada usuario. Antes volvia a "Día" en cada
 * navegacion, y "Día" en un telefono es una grilla de 800 px (QA movil
 * 2026-10-08). Es una comodidad por navegador: si el almacenamiento no esta
 * (modo privado, datos bloqueados) la agenda arranca en la vista por defecto.
 */

const STORAGE_PREFIX = 'shifty.agenda.view'

/** Por debajo de `md` (768 px) la grilla del dia y la del mes no entran. */
const PHONE_QUERY = '(max-width: 767px)'

const VIEWS: readonly CalendarView[] = ['day', 'week', 'month', 'list']

const isCalendarView = (value: unknown): value is CalendarView =>
  typeof value === 'string' && (VIEWS as readonly string[]).includes(value)

const keyFor = (userId: string | undefined) => `${STORAGE_PREFIX}:${userId ?? 'anon'}`

const isPhoneViewport = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia(PHONE_QUERY).matches

/** La guardada del usuario o, sin ninguna, Lista en el telefono y Día si no. */
export const initialAgendaView = (userId: string | undefined): CalendarView => {
  try {
    const saved = window.localStorage.getItem(keyFor(userId))
    if (isCalendarView(saved)) return saved
  } catch {
    // Sin almacenamiento: vale la vista por defecto.
  }
  return isPhoneViewport() ? 'list' : 'day'
}

export const saveAgendaView = (userId: string | undefined, view: CalendarView): void => {
  try {
    window.localStorage.setItem(keyFor(userId), view)
  } catch {
    // Sin almacenamiento la eleccion dura lo que la pantalla.
  }
}
