import {
  bookingActionsFor,
  isBookingStatus,
  isCollectibleStatus,
  type BookingAction
} from './BookingStatus'

describe('predicados de estado del turno', () => {
  it.each([
    ['pending', true, true],
    ['pending_payment', true, true],
    ['confirmed', true, true],
    ['completed', true, false],
    ['cancelled', true, false],
    ['absent', true, false],
    ['expired', true, false],
    ['on_hold', false, false],
    ['', false, false],
    ['CONFIRMED', false, false]
  ])('%s: conocido=%s, cobrable=%s', (status, known, collectible) => {
    expect(isBookingStatus(status)).toBe(known)
    expect(isCollectibleStatus(status)).toBe(collectible)
  })
})

describe('bookingActionsFor', () => {
  const all = {
    hasStarted: true,
    canRelease: true,
    canManage: true,
    canCancelOrReschedule: false
  }

  it.each<[string, Partial<typeof all>, BookingAction[]]>([
    ['pending', { hasStarted: false }, ['confirm', 'release']],
    ['pending', { canRelease: false }, ['confirm']],
    ['pending', { canManage: false }, ['release']],
    ['pending_payment', {}, ['release']],
    ['pending_payment', { canRelease: false }, []],
    ['confirmed', {}, ['complete', 'absent']],
    ['confirmed', { hasStarted: false }, []],
    ['confirmed', { canManage: false }, []],
    ['completed', {}, []],
    ['cancelled', {}, []],
    ['absent', {}, []],
    ['expired', {}, []],
    ['on_hold', {}, []]
  ])('%s %o -> %o', (status, overrides, expected) => {
    expect(bookingActionsFor(status, { ...all, ...overrides })).toEqual(expected)
  })

  // FF-31, D-20260929-05/06: cancelar y reprogramar desde la agenda.
  const owner = {
    hasStarted: false,
    canRelease: false,
    canManage: true,
    canCancelOrReschedule: true
  }

  it.each<[string, Partial<typeof owner>, BookingAction[]]>([
    // Confirmado: cancela cualquiera que pueda, mientras no empezo.
    ['confirmed', {}, ['cancel', 'reschedule']],
    ['confirmed', { canRelease: true }, ['cancel', 'reschedule']],
    // Ya empezado: se completa o se marca ausente, no se cancela.
    ['confirmed', { hasStarted: true }, ['complete', 'absent', 'reschedule']],
    // Pendiente: el admin libera, el resto cancela.
    ['pending', {}, ['confirm', 'cancel', 'reschedule']],
    ['pending', { canRelease: true }, ['confirm', 'release', 'reschedule']],
    ['pending', { hasStarted: true }, ['confirm', 'reschedule']],
    // Pendiente de pago: no se reprograma (409 DEPOSIT_PENDING_RESCHEDULE_DENIED).
    ['pending_payment', {}, ['cancel']],
    ['pending_payment', { canRelease: true }, ['release']],
    // Turno de otro profesional: ni cancelar ni reprogramar.
    ['confirmed', { canCancelOrReschedule: false }, []],
    ['pending', { canCancelOrReschedule: false }, ['confirm']],
    ['cancelled', {}, []],
    ['completed', {}, []],
    ['on_hold', {}, []]
  ])('con permiso de cancelar: %s %o -> %o', (status, overrides, expected) => {
    expect(bookingActionsFor(status, { ...owner, ...overrides })).toEqual(expected)
  })
})
