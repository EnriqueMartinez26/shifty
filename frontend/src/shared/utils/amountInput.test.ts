import { formatAmountInput, parseAmountInput } from './amountInput'

// Revision de la PR #131 (W4, 2026-10-08): el importe se tipeaba en un
// `type="number"` y "3.200" llegaba como 3.2: se registraban $3,20. El campo
// lee el formato es-AR: punto de miles y coma decimal.
describe('parseAmountInput', () => {
  it.each([
    ['3200', 3200],
    ['3.200', 3200],
    ['1.234.567', 1234567],
    ['3.200,50', 3200.5],
    ['3200,5', 3200.5],
    ['0,99', 0.99],
    ['  $ 3.200  ', 3200],
    ['$960', 960]
  ])('lee "%s" como %d', (texto, esperado) => {
    expect(parseAmountInput(texto)).toEqual({ ok: true, value: esperado })
  })

  it.each([
    // Un punto que no separa miles es ambiguo: se pide la coma.
    ['3.2'],
    ['3.20'],
    ['3.2000'],
    ['32.00.000'],
    // Una coma seguida de tres cifras puede ser miles en otro formato.
    ['3,200'],
    ['3,2,0'],
    ['3.200,5,0'],
    ['3,200.50']
  ])('rechaza el ambiguo "%s" pidiendo la coma decimal', (texto) => {
    expect(parseAmountInput(texto)).toEqual({
      ok: false,
      error: 'Escribí el importe con punto de miles y coma decimal, por ejemplo 3.200,50.'
    })
  })

  it.each([['abc'], ['12a'], ['-500'], ['1e3'], [',5']])('rechaza "%s" por invalido', (texto) => {
    expect(parseAmountInput(texto)).toEqual({
      ok: false,
      error: 'Escribí el importe con punto de miles y coma decimal, por ejemplo 3.200,50.'
    })
  })

  it('pide el importe si esta vacio', () => {
    expect(parseAmountInput('   ')).toEqual({ ok: false, error: 'Ingresá el importe.' })
  })

  it.each([['0'], ['0,00'], ['0.000']])('rechaza "%s" porque no es mayor a cero', (texto) => {
    expect(parseAmountInput(texto)).toEqual({
      ok: false,
      error: 'El importe tiene que ser mayor a cero.'
    })
  })
})

describe('formatAmountInput', () => {
  it.each([
    [3200, '3.200'],
    [960, '960'],
    [1234567, '1.234.567'],
    [3200.5, '3.200,50'],
    [0.99, '0,99']
  ])('escribe %d como "%s"', (importe, esperado) => {
    expect(formatAmountInput(importe)).toBe(esperado)
  })

  it('lo que escribe se vuelve a leer igual', () => {
    for (const importe of [1, 960, 3200, 3200.5, 1234567.89]) {
      expect(parseAmountInput(formatAmountInput(importe))).toEqual({ ok: true, value: importe })
    }
  })
})
