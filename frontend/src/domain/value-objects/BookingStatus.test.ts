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
  const all = { hasStarted: true, canRelease: true, canManage: true }

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
})
