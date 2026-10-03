import {
  LOGIN_PASSWORD_MAX_LENGTH,
  PASSWORD_MAX_BYTES,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  validateNewPassword
} from './PasswordRules'

// 2026-10-01, D-20261001-01: 6 a 64 caracteres (code points), maximo 72 bytes
// en UTF-8, una letra y un numero. Los valores esperados son literales a
// proposito: si alguien cambia una constante, estos casos tienen que fallar.

const MUY_CORTA = 'La contraseña debe tener al menos 6 caracteres'
const MUY_LARGA = 'La contraseña no puede tener más de 64 caracteres'
const MAS_DE_72_BYTES =
  'La contraseña ocupa más de 72 bytes (los acentos, la ñ, los símbolos y los emojis ocupan más de uno)'
const SIN_LETRA = 'La contraseña debe incluir al menos una letra'
const SIN_NUMERO = 'La contraseña debe incluir al menos un número'

describe('constantes de contraseña', () => {
  it('fijan los topes de la decision', () => {
    expect(PASSWORD_MIN_LENGTH).toBe(6)
    expect(PASSWORD_MAX_LENGTH).toBe(64)
    expect(PASSWORD_MAX_BYTES).toBe(72)
    expect(LOGIN_PASSWORD_MAX_LENGTH).toBe(128)
  })
})

describe('validateNewPassword: largo en caracteres', () => {
  it.each([
    ['5 caracteres', 'abcd1', MUY_CORTA],
    ['vacia', '', MUY_CORTA],
    ['6 caracteres', 'abcde1', null],
    ['64 caracteres', `${'a'.repeat(63)}1`, null],
    ['65 caracteres', `${'a'.repeat(64)}1`, MUY_LARGA]
  ])('%s', (_caso, clave, esperado) => {
    expect(validateNewPassword(clave)).toBe(esperado)
  })

  it('cuenta code points, no unidades UTF-16: un emoji es un caracter', () => {
    // 'a1' + 4 emojis = 6 code points (10 unidades UTF-16): pasa el piso de 6.
    expect(validateNewPassword(`a1${'😀'.repeat(4)}`)).toBeNull()
    // 4 caracteres de largo, aunque sean 8 unidades UTF-16.
    expect(validateNewPassword('😀😀a1')).toBe(MUY_CORTA)
  })

  it('65 emojis son 65 caracteres: gana el tope de largo sobre el de bytes', () => {
    expect(validateNewPassword('😀'.repeat(65))).toBe(MUY_LARGA)
  })
})

describe('validateNewPassword: tope de 72 bytes en UTF-8', () => {
  it('letras con tilde (2 bytes): 72 bytes pasan, 74 no', () => {
    // 35 x 'é' (70 bytes) + '12' = 72 bytes, 37 caracteres.
    expect(validateNewPassword(`${'é'.repeat(35)}12`)).toBeNull()
    // 36 x 'é' (72 bytes) + '12' = 74 bytes, 38 caracteres.
    expect(validateNewPassword(`${'é'.repeat(36)}12`)).toBe(MAS_DE_72_BYTES)
  })

  it('73 bytes ya no pasan (el límite es 72, no 73)', () => {
    // 36 x 'é' (72 bytes) + '1' = 73 bytes, 37 caracteres.
    expect(validateNewPassword(`${'é'.repeat(36)}1`)).toBe(MAS_DE_72_BYTES)
  })

  it('36 letras con tilde son exactamente 72 bytes y no rompen el tope; 37 si', () => {
    // Sin numero: llega a la regla del numero, o sea que pasó la de bytes.
    expect(validateNewPassword('é'.repeat(36))).toBe(SIN_NUMERO)
    expect(validateNewPassword('é'.repeat(37))).toBe(MAS_DE_72_BYTES)
  })

  it('euros (3 bytes): 24 son 72 bytes, 25 son 75', () => {
    expect(validateNewPassword('€'.repeat(24))).toBe(SIN_LETRA)
    expect(validateNewPassword('€'.repeat(25))).toBe(MAS_DE_72_BYTES)
  })

  it('emojis (4 bytes): 18 son 72 bytes, 19 son 76', () => {
    expect(validateNewPassword('😀'.repeat(18))).toBe(SIN_LETRA)
    expect(validateNewPassword('😀'.repeat(19))).toBe(MAS_DE_72_BYTES)
  })

  it('ASCII: 64 caracteres son 64 bytes y pasan', () => {
    expect(validateNewPassword(`${'a'.repeat(63)}1`)).toBeNull()
  })
})

describe('validateNewPassword: letra y numero', () => {
  it.each([
    ['solo letras', 'abcdef', SIN_NUMERO],
    ['solo numeros', '123456', SIN_LETRA],
    ['solo simbolos', '!!!!!!', SIN_LETRA],
    ['letra y numero', 'abc123', null],
    ['letra unicode (ñ)', 'ñandú1', null],
    ['letra no latina', '日本語123', null],
    ['espacios no cuentan como letra ni numero', '      ', SIN_LETRA]
  ])('%s', (_caso, clave, esperado) => {
    expect(validateNewPassword(clave)).toBe(esperado)
  })

  it('un digito arabe-indico cuenta como numero, igual que str.isdigit del backend', () => {
    expect(validateNewPassword('abc٣٣٣')).toBeNull()
  })

  it('acepta dígitos superíndice y encerrados igual que Python str.isdigit', () => {
    expect(validateNewPassword('abcde²')).toBeNull()
    expect(validateNewPassword('abcde①')).toBeNull()
    expect(validateNewPassword('abcdeⅧ')).toBe(SIN_NUMERO)
  })

  it('no recorta ni normaliza: los espacios de los extremos cuentan', () => {
    // 'a1' + 4 espacios = 6 caracteres; recortada serian 2.
    expect(validateNewPassword('  a1  ')).toBeNull()
  })

  it('el primer incumplimiento gana: corta antes que sin letra', () => {
    expect(validateNewPassword('12345')).toBe(MUY_CORTA)
  })
})
