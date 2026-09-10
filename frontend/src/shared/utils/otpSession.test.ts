import { forgetOtpVerification, isOtpStillValid, rememberOtpVerification } from './otpSession'

describe('otpSession', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('recuerda el telefono verificado dentro de la ventana de 30 minutos', () => {
    const verificado = new Date('2026-09-15T12:00:00Z')
    rememberOtpVerification('mi-tienda', '+54 9 11 5555-0042', verificado.toISOString())

    expect(isOtpStillValid('mi-tienda', '5491155550042', new Date('2026-09-15T12:29:00Z'))).toBe(
      true
    )
    expect(isOtpStillValid('mi-tienda', '5491155550042', new Date('2026-09-15T12:31:00Z'))).toBe(
      false
    )
  })

  it('no vale para otro telefono ni para otra tienda', () => {
    const verificado = new Date('2026-09-15T12:00:00Z')
    rememberOtpVerification('mi-tienda', '5491155550042', verificado.toISOString())
    const ahora = new Date('2026-09-15T12:05:00Z')

    expect(isOtpStillValid('mi-tienda', '5491155550099', ahora)).toBe(false)
    expect(isOtpStillValid('otra-tienda', '5491155550042', ahora)).toBe(false)
  })

  it('olvida y tolera datos corruptos', () => {
    rememberOtpVerification('mi-tienda', '5491155550042', new Date().toISOString())
    forgetOtpVerification('mi-tienda')
    expect(isOtpStillValid('mi-tienda', '5491155550042')).toBe(false)

    window.sessionStorage.setItem('shifty:otp:mi-tienda', '{no es json')
    expect(isOtpStillValid('mi-tienda', '5491155550042')).toBe(false)
  })
})
