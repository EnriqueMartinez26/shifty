import { DomainError, InvalidValueError } from './DomainError'
import { BookingTimeSpan } from '../value-objects/BookingTimeSpan'
import { Duration } from '../value-objects/Duration'
import { Email } from '../value-objects/Email'
import { Price } from '../value-objects/Price'
import { ServiceColor } from '../value-objects/ServiceColor'
import { UserId } from '../value-objects/UserId'
import { UserRole } from '../value-objects/UserRole'

const catchError = (build: () => unknown): unknown => {
  try {
    build()
  } catch (error) {
    return error
  }
  throw new Error('se esperaba un error')
}

describe('value objects lanzan InvalidValueError con code', () => {
  it.each([
    ['INVALID_ROLE', () => UserRole.create('root')],
    ['INVALID_COLOR', () => ServiceColor.create('rojo')],
    ['INVALID_DURATION', () => Duration.create(0)],
    ['INVALID_DURATION', () => Duration.create(481)],
    ['INVALID_EMAIL', () => Email.create('no-es-mail')],
    ['INVALID_TIME_SPAN', () => BookingTimeSpan.create('x', 'y')],
    [
      'INVALID_TIME_SPAN',
      () => BookingTimeSpan.create('2026-09-10T12:00:00Z', '2026-09-10T11:00:00Z')
    ],
    ['INVALID_PRICE', () => Price.create(-1)],
    ['INVALID_USER_ID', () => UserId.create('')]
  ])('%s', (code, build) => {
    const error = catchError(build)

    expect(error).toBeInstanceOf(InvalidValueError)
    expect(error).toBeInstanceOf(DomainError)
    expect(error).toMatchObject({ code, name: 'InvalidValueError' })
  })
})
