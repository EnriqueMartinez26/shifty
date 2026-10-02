/**
 * Telefonos para links de wa.me.
 *
 * wa.me exige el numero internacional, solo digitos y sin "+". Un celular
 * argentino es 54 + 9 + codigo de area + abonado, que suman 10 digitos sin el
 * 0 de larga distancia ni el 15 de celular. Los telefonos llegan como texto
 * libre (el WhatsApp de la tienda, el de un cliente o de la lista de espera) y
 * antes solo se les sacaban los simbolos: "11 5555 0303" armaba
 * wa.me/1155550303, un numero de Estados Unidos (QA 2026-10-02).
 *
 * Cuando el numero no se puede leer con confianza devuelve null: la pantalla
 * no muestra el link antes que mandar el mensaje a otra persona.
 */

const ARGENTINA_CODE = '54'
const ARGENTINA_MOBILE = '549'
const NATIONAL_LENGTH = 10
const NATIONAL_WITH_15_LENGTH = 12
// E.164: hasta 15 digitos con el codigo de pais; menos de 8 no es un telefono.
const MIN_INTERNATIONAL_LENGTH = 8
const MAX_INTERNATIONAL_LENGTH = 15

// Lo unico que se acepta alrededor de los digitos: separadores y un "+" al
// principio. Cualquier otra cosa (letras, un "+" en el medio) es texto que no
// se sabe leer.
const ALLOWED_SHAPE = /^\+?[\d\s\-().]+$/

/**
 * Codigo de area argentino valido como primer tramo: 11 (AMBA) es el unico de
 * dos digitos; el resto empieza con 2 o 3 y tiene tres o cuatro.
 */
const startsLikeArea = (national: string): boolean => /^(11|[23])/.test(national)

/**
 * Numero nacional (sin 0) a sus 10 digitos. Con el 15 de celular metido
 * despues del area (12 digitos), lo saca. El area de 2 digitos es solo 11, y
 * para areas de 3 y 4 la prueba en ese orden no es ambigua: si el area es de
 * 4 digitos y termina en 1, en la posicion 3 aparece "11", nunca "15".
 */
const toTenDigits = (national: string): string | null => {
  if (!startsLikeArea(national)) return null
  if (national.length === NATIONAL_LENGTH) return national
  if (national.length !== NATIONAL_WITH_15_LENGTH) return null
  const areaLengths = national.startsWith('11') ? [2] : [3, 4]
  for (const areaLength of areaLengths) {
    if (national.slice(areaLength, areaLength + 2) === '15') {
      return national.slice(0, areaLength) + national.slice(areaLength + 2)
    }
  }
  return null
}

/**
 * Lo que sigue al 54. Con el 9 (o con el 15 metido despues del area) es un
 * celular: 549 + los 10 digitos. Sin ninguno de los dos se respeta tal cual
 * (54 + 10 digitos): quien escribio el codigo de pais pudo cargar a proposito
 * una linea fija con WhatsApp Business, y agregarle un 9 la mandaria a otro
 * numero.
 */
const fromArgentineInternational = (afterCountry: string): string | null => {
  const isMobile = afterCountry.startsWith('9')
  let rest = isMobile ? afterCountry.slice(1) : afterCountry
  if (rest.startsWith('0')) rest = rest.slice(1)
  const national = toTenDigits(rest)
  if (!national) return null
  const hadMobilePrefix = isMobile || rest.length === NATIONAL_WITH_15_LENGTH
  return (hadMobilePrefix ? ARGENTINA_MOBILE : ARGENTINA_CODE) + national
}

const fromInternational = (digits: string): string | null => {
  if (digits.startsWith(ARGENTINA_CODE)) {
    return fromArgentineInternational(digits.slice(ARGENTINA_CODE.length))
  }
  const plausible =
    !digits.startsWith('0') &&
    digits.length >= MIN_INTERNATIONAL_LENGTH &&
    digits.length <= MAX_INTERNATIONAL_LENGTH
  return plausible ? digits : null
}

/**
 * Telefono de texto libre -> numero para wa.me, o null si no se puede leer
 * con confianza. Sin "+" ni "00" se asume Argentina, salvo que ya empiece con
 * 54 y tenga el largo de un numero internacional.
 */
export const normalizePhoneForWhatsApp = (raw: string | null | undefined): string | null => {
  const trimmed = (raw ?? '').trim()
  if (!trimmed || !ALLOWED_SHAPE.test(trimmed)) return null
  const digits = trimmed.replace(/\D/g, '')
  if (trimmed.startsWith('+')) return fromInternational(digits)
  if (digits.startsWith('00')) return fromInternational(digits.slice(2))
  if (digits.startsWith(ARGENTINA_CODE) && digits.length >= NATIONAL_WITH_15_LENGTH) {
    return fromArgentineInternational(digits.slice(ARGENTINA_CODE.length))
  }
  const national = digits.startsWith('0') ? digits.slice(1) : digits
  const tenDigits = toTenDigits(national)
  return tenDigits ? ARGENTINA_MOBILE + tenDigits : null
}

/** Link wa.me con el texto prearmado, o null si el telefono no es confiable. */
export const buildWaMeUrl = (phone: string | null | undefined, text: string): string | null => {
  const number = normalizePhoneForWhatsApp(phone)
  return number ? `https://wa.me/${number}?text=${encodeURIComponent(text)}` : null
}
