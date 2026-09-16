import { depositBreakdownText, depositReasonsText } from './depositReasons'

const pesos = (n: number): string => `$${n}`

describe('depositBreakdownText', () => {
  it('base mas recargo suman el total mostrado', () => {
    expect(
      depositBreakdownText(
        {
          amount: 1500,
          base_amount: 1000,
          extra_percent: 10,
          price: 5000,
          reasons: ['base', 'new_client']
        },
        pesos
      )
    ).toBe('Incluye $1000 de seña base mas $500 por ser tu primera visita (10% del precio).')
  })

  it('cuando la seña se topea al precio, el recargo es el que queda y lo dice', () => {
    // 20% de 5000 serian 1000 sobre una base de 4500: el backend topea a 5000.
    expect(
      depositBreakdownText(
        {
          amount: 5000,
          base_amount: 4500,
          extra_percent: 20,
          price: 5000,
          reasons: ['base', 'absences']
        },
        pesos
      )
    ).toBe(
      'Incluye $4500 de seña base mas $500 por ausencias anteriores (la seña se topea al precio del servicio).'
    )
  })
})

describe('depositReasonsText', () => {
  it('explica los recargos en castellano y omite la base', () => {
    expect(depositReasonsText(['base'])).toBe('')
    expect(depositReasonsText(['base', 'new_client'])).toBe('ser tu primera visita')
    expect(depositReasonsText(['base', 'far_notice', 'absences'])).toBe(
      'reservar con mucha antelacion y ausencias anteriores'
    )
    expect(depositReasonsText(['base', 'far_notice', 'new_client', 'absences'])).toBe(
      'reservar con mucha antelacion, ser tu primera visita y ausencias anteriores'
    )
  })
})
