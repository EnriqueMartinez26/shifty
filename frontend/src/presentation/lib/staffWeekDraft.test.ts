import { ValidationError } from '@shared/errors'

import {
  copyDayToAll,
  draftFromSchedules,
  draftFromStoreHours,
  nextRange,
  scheduleSaveErrorMessage,
  summarizeSchedules,
  validateWeek,
  weekToSchedules,
  type WeekDraft
} from './staffWeekDraft'

const semana = (dias: Partial<Record<number, { start: string; end: string }[]>>): WeekDraft =>
  [0, 1, 2, 3, 4, 5, 6].map((dia) => dias[dia] ?? [])

describe('staffWeekDraft', () => {
  it('arma el borrador desde las franjas guardadas, en HH:MM y ordenado', () => {
    const borrador = draftFromSchedules([
      { dayOfWeek: 1, startTime: '14:00:00', endTime: '18:00:00' },
      { dayOfWeek: 1, startTime: '09:00:00', endTime: '13:00:00' },
      { dayOfWeek: 6, startTime: '10:00:00', endTime: '12:00:00' }
    ])

    expect(borrador[1]).toEqual([
      { start: '09:00', end: '13:00' },
      { start: '14:00', end: '18:00' }
    ])
    expect(borrador[6]).toEqual([{ start: '10:00', end: '12:00' }])
    expect(borrador[0]).toEqual([])
  })

  it('el horario de la tienda es el punto de partida del horario propio', () => {
    const borrador = draftFromStoreHours({
      mon: [{ open: '09:00', close: '18:00' }],
      sun: []
    })

    expect(borrador[0]).toEqual([{ start: '09:00', end: '18:00' }])
    expect(borrador.slice(1).every((dia) => dia.length === 0)).toBe(true)
    expect(draftFromStoreHours(undefined).every((dia) => dia.length === 0)).toBe(true)
  })

  it('copiar a todos los dias replica las franjas sin compartir referencias', () => {
    const copia = copyDayToAll(semana({ 2: [{ start: '08:00', end: '12:00' }] }), 2)

    expect(copia.every((dia) => dia.length === 1 && dia[0]?.start === '08:00')).toBe(true)
    expect(copia[0]?.[0]).not.toBe(copia[1]?.[0])
  })

  it('la franja nueva arranca donde termina la ultima, sin pasar la medianoche', () => {
    expect(nextRange([])).toEqual({ start: '09:00', end: '18:00' })
    expect(nextRange([{ start: '09:00', end: '13:00' }])).toEqual({
      start: '13:00',
      end: '17:00'
    })
    expect(nextRange([{ start: '18:00', end: '22:30' }])).toEqual({
      start: '22:30',
      end: '23:59'
    })
  })

  describe('validateWeek', () => {
    it('el modo tienda siempre es valido', () => {
      expect(validateWeek('store', semana({})).isValid).toBe(true)
    })

    it('un horario propio sin ningun dia no se puede guardar (seria el de la tienda)', () => {
      const resultado = validateWeek('own', semana({}))

      expect(resultado.isValid).toBe(false)
      expect(resultado.weekError).toMatch(/al menos un día/)
    })

    it('marca el dia con una franja invertida o incompleta', () => {
      const resultado = validateWeek(
        'own',
        semana({ 0: [{ start: '18:00', end: '09:00' }], 3: [{ start: '', end: '12:00' }] })
      )

      expect(resultado.isValid).toBe(false)
      expect(resultado.dayErrors[0]).toMatch(/inicio antes del fin/)
      expect(resultado.dayErrors[3]).toMatch(/inicio antes del fin/)
      expect(resultado.dayErrors[1]).toBeNull()
    })

    it('marca el dia con franjas superpuestas, pero no las que se tocan en el borde', () => {
      const resultado = validateWeek(
        'own',
        semana({
          1: [
            { start: '12:00', end: '15:00' },
            { start: '09:00', end: '13:00' }
          ],
          2: [
            { start: '09:00', end: '13:00' },
            { start: '13:00', end: '17:00' }
          ]
        })
      )

      expect(resultado.dayErrors[1]).toMatch(/se superponen/)
      expect(resultado.dayErrors[2]).toBeNull()
    })
  })

  it('el modo tienda guarda la lista vacia; el propio, la semana con segundos', () => {
    const borrador = semana({
      4: [
        { start: '14:00', end: '18:00' },
        { start: '09:00', end: '12:00' }
      ]
    })

    expect(weekToSchedules('store', borrador)).toEqual([])
    expect(weekToSchedules('own', borrador)).toEqual([
      { dayOfWeek: 4, startTime: '09:00:00', endTime: '12:00:00' },
      { dayOfWeek: 4, startTime: '14:00:00', endTime: '18:00:00' }
    ])
  })

  it('resume la semana para la tarjeta', () => {
    expect(summarizeSchedules([])).toBe('Horario de la tienda')
    expect(
      summarizeSchedules([
        { dayOfWeek: 6, startTime: '09:00:00', endTime: '12:00:00' },
        { dayOfWeek: 0, startTime: '09:00:00', endTime: '12:00:00' },
        { dayOfWeek: 0, startTime: '13:00:00', endTime: '17:00:00' }
      ])
    ).toBe('Lun, Dom')
  })

  describe('scheduleSaveErrorMessage', () => {
    it('una superposicion del backend nombra el dia', () => {
      const error = new ValidationError('Hay franjas que se superponen el mismo día.', {
        errorCode: 'SCHEDULE_OVERLAP',
        statusCode: 422,
        detail: { day_of_week: 2 }
      })

      expect(scheduleSaveErrorMessage(error)).toBe(
        'El Miércoles tiene franjas que se superponen. Corregilas y volvé a guardar.'
      )
    })

    it('sin el dia cae en la tabla de codigos', () => {
      const error = new ValidationError('x', { errorCode: 'SCHEDULE_OVERLAP', statusCode: 422 })

      expect(scheduleSaveErrorMessage(error)).toBe(
        'Hay franjas que se superponen el mismo día. Corregilas y volvé a guardar.'
      )
    })

    it('un 422 de Pydantic no muestra el texto crudo (regla 20)', () => {
      const error = new ValidationError('body -> schedules: value error', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422
      })

      expect(scheduleSaveErrorMessage(error)).toBe('No se pudo guardar el horario. Probá de nuevo.')
    })
  })
})
