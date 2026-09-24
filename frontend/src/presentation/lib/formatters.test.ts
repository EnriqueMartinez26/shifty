import { formatDateEsAr, formatDateTimeEsAr } from './formatters'
import {
  resetUnreadableInstantReports,
  setUnreadableInstantReporter
} from './reportUnreadableInstant'

const captureMessage = jest.fn()

beforeEach(() => {
  resetUnreadableInstantReports()
  captureMessage.mockClear()
  setUnreadableInstantReporter(captureMessage)
})

describe('formatDateEsAr', () => {
  it('usa la hora argentina, no la del navegador', () => {
    // 02:00Z son las 23:00 del dia anterior en Argentina: el panel de
    // superadmin imprimia "01/09" al lado de un "Vencida hace 1 d" calculado
    // en hora argentina.
    expect(formatDateEsAr('2026-09-01T02:00:00Z')).toBe('31/08/2026')
  })

  it('una fecha de calendario no se corre un dia', () => {
    expect(formatDateEsAr('2026-09-27')).toBe('27/09/2026')
  })

  it('devuelve el texto de respaldo sin valor y sin romper con uno ilegible', () => {
    expect(formatDateEsAr(null)).toBe('Sin fecha')
    expect(formatDateEsAr('')).toBe('Sin fecha')
    // Antes esto lanzaba RangeError desde Intl.format.
    expect(formatDateEsAr('no-es-una-fecha')).toBe('Sin fecha')
  })

  it('reporta el valor ilegible, pero no la ausencia de valor', () => {
    // Degradar en silencio dejaba el dato corrupto sin ninguna senal: antes
    // el RangeError llegaba a Sentry por el ErrorBoundary.
    formatDateEsAr(null)
    formatDateEsAr('')
    expect(captureMessage).not.toHaveBeenCalled()

    formatDateEsAr('no-es-una-fecha')
    expect(captureMessage).toHaveBeenCalledTimes(1)
  })

  it('no inunda la telemetria repitiendo el mismo valor en cada render', () => {
    formatDateEsAr('no-es-una-fecha')
    formatDateEsAr('no-es-una-fecha')
    formatDateEsAr('no-es-una-fecha')
    expect(captureMessage).toHaveBeenCalledTimes(1)
  })
})

describe('formatDateTimeEsAr', () => {
  it('imprime fecha y hora argentinas, con el mismo separador de antes', () => {
    expect(formatDateTimeEsAr('2026-09-15T12:00:00Z')).toBe('15/09/2026, 09:00')
  })

  it('un instante de 00:00Z pertenece al dia anterior', () => {
    expect(formatDateTimeEsAr('2026-09-16T00:00:00Z')).toBe('15/09/2026, 21:00')
  })

  it('devuelve el texto de respaldo sin valor y sin romper con uno ilegible', () => {
    expect(formatDateTimeEsAr(null)).toBe('Sin actividad')
    expect(formatDateTimeEsAr('tampoco-es-fecha')).toBe('Sin actividad')
  })
})
