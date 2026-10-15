import { forgetOtpVerification, isOtpStillValid, rememberOtpVerification } from './otpSession'

describe('otpSession', () => {
  beforeEach(() => {
    forgetOtpVerification('mi-tienda')
    forgetOtpVerification('otra-tienda')
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

  it('olvida y tolera una fecha corrupta', () => {
    rememberOtpVerification('mi-tienda', '5491155550042', new Date().toISOString())
    forgetOtpVerification('mi-tienda')
    expect(isOtpStillValid('mi-tienda', '5491155550042')).toBe(false)

    rememberOtpVerification('mi-tienda', '5491155550042', 'no es una fecha')
    expect(isOtpStillValid('mi-tienda', '5491155550042')).toBe(false)
  })

  it('vive solo en memoria: no escribe sessionStorage ni localStorage (2026-10-14)', () => {
    // La verificacion sin el token del cliente (que vive en memoria) no
    // alcanza en el backend: recordarla en el storage hacia entrar por el
    // atajo despues de recargar y rebotar con 403.
    const setItem = jest.spyOn(Storage.prototype, 'setItem')
    try {
      rememberOtpVerification('mi-tienda', '5491155550042', new Date().toISOString())

      expect(setItem).not.toHaveBeenCalled()
      expect(window.sessionStorage.length).toBe(0)
      expect(window.localStorage.length).toBe(0)
      expect(isOtpStillValid('mi-tienda', '5491155550042')).toBe(true)
    } finally {
      setItem.mockRestore()
    }
  })
})
