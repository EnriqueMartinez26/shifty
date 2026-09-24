import {
  argentinaLocalToUtcIso,
  argentinaMinutesOfDay,
  formatArgentinaDate,
  formatArgentinaDateDisplay,
  formatArgentinaDayMonth,
  formatArgentinaTime,
  fromDateTimeInput,
  toDateTimeInput
} from './argentinaTime'

describe('argentinaTime', () => {
  it('muestra la hora argentina de un instante UTC (09:00 ART = 12:00Z)', () => {
    expect(formatArgentinaTime('2026-09-15T12:00:00+00:00')).toBe('09:00')
    expect(formatArgentinaTime('2026-09-15T12:00:00Z')).toBe('09:00')
  })

  it('un slot de 00:00Z es 21:00 del dia anterior en Argentina', () => {
    expect(formatArgentinaTime('2026-09-16T00:00:00+00:00')).toBe('21:00')
    expect(formatArgentinaDate('2026-09-16T00:00:00+00:00')).toBe('2026-09-15')
    expect(formatArgentinaDateDisplay('2026-09-16T00:00:00+00:00')).toBe('15/09/2026')
  })

  it('devuelve vacio ante un ISO invalido en vez de romper el render', () => {
    expect(formatArgentinaTime('no-es-una-fecha')).toBe('')
    expect(formatArgentinaDate('')).toBe('')
  })

  it('convierte fecha y hora tipeadas en Argentina al instante UTC', () => {
    expect(argentinaLocalToUtcIso('2026-09-15', '09:00')).toBe('2026-09-15T12:00:00.000Z')
    // 22:00 local cae en el dia UTC siguiente.
    expect(argentinaLocalToUtcIso('2026-09-15', '22:00')).toBe('2026-09-16T01:00:00.000Z')
  })

  it('formatear y convertir son inversas', () => {
    const iso = argentinaLocalToUtcIso('2026-12-31', '23:30')
    expect(formatArgentinaDate(iso)).toBe('2026-12-31')
    expect(formatArgentinaTime(iso)).toBe('23:30')
  })

  it('rechaza entradas malformadas', () => {
    expect(() => argentinaLocalToUtcIso('2026-13', '09:00')).toThrow()
    expect(() => argentinaLocalToUtcIso('2026-09-15', 'nueve')).toThrow()
  })
})

describe('formatArgentinaDayMonth', () => {
  it('imprime dd/MM en hora argentina, sin el anio', () => {
    expect(formatArgentinaDayMonth('2026-09-15T12:00:00Z')).toBe('15/09')
  })

  it('un instante de 00:00Z pertenece al dia anterior', () => {
    expect(formatArgentinaDayMonth('2026-09-16T00:00:00Z')).toBe('15/09')
  })

  it('devuelve vacio ante un ISO ilegible', () => {
    expect(formatArgentinaDayMonth('no-es-una-fecha')).toBe('')
  })
})

describe('argentinaMinutesOfDay', () => {
  it('cuenta los minutos desde la medianoche argentina, no la UTC', () => {
    expect(argentinaMinutesOfDay('2026-09-15T12:00:00Z')).toBe(9 * 60)
    expect(argentinaMinutesOfDay('2026-09-15T12:30:00Z')).toBe(9 * 60 + 30)
  })

  it('un instante de 00:00Z son las 21:00 del dia anterior', () => {
    expect(argentinaMinutesOfDay('2026-09-16T00:00:00Z')).toBe(21 * 60)
  })

  it('devuelve null ante un ISO ilegible, para que el llamador decida', () => {
    expect(argentinaMinutesOfDay('no-es-una-fecha')).toBeNull()
    expect(argentinaMinutesOfDay('')).toBeNull()
  })

  it('una fecha sin hora vale medianoche, igual que los demas formateadores', () => {
    expect(argentinaMinutesOfDay('2026-09-27')).toBe(0)
  })
})

describe('inputs datetime-local', () => {
  it('el input va y vuelve en hora argentina sin deriva', () => {
    // 2026-09-20 15:30 en Buenos Aires = 18:30 UTC.
    expect(toDateTimeInput('2026-09-20T18:30:00+00:00')).toBe('2026-09-20T15:30')
    expect(fromDateTimeInput('2026-09-20T15:30')).toBe('2026-09-20T18:30:00.000Z')
    expect(fromDateTimeInput('')).toBeNull()
    expect(toDateTimeInput(null)).toBe('')
    expect(toDateTimeInput(undefined)).toBe('')
  })

  it('la vigencia que tipea el dueno no se adelanta tres horas', () => {
    // El bug de las promociones: "vence 31/12 23:59" salia sin offset y el
    // backend lo leia como UTC, o sea 20:59 ART (2026-09-20).
    const vence = fromDateTimeInput('2026-12-31T23:59')
    expect(vence).toBe('2027-01-01T02:59:00.000Z')
    expect(toDateTimeInput(vence)).toBe('2026-12-31T23:59')
  })

  it('un valor con segundos se recorta a HH:mm', () => {
    expect(fromDateTimeInput('2026-12-31T23:59:30')).toBe('2027-01-01T02:59:00.000Z')
  })

  it('devuelve null si el valor no tiene hora', () => {
    expect(fromDateTimeInput('2026-12-31')).toBeNull()
  })
})

describe('fechas de calendario sin hora', () => {
  it('no se corren un dia al formatearse', () => {
    // Medianoche UTC son las 21:00 del dia anterior en Argentina: tratar
    // "2026-09-27" como instante mostraba 26/09 (banner de suscripcion).
    expect(formatArgentinaDateDisplay('2026-09-27')).toBe('27/09/2026')
    expect(formatArgentinaDate('2026-09-27')).toBe('2026-09-27')
    expect(formatArgentinaTime('2026-09-27')).toBe('00:00')
  })
})
