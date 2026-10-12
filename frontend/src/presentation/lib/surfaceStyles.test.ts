import { create2000sModalInputStyle, createBookingClientInputStyle } from './surfaceStyles'

describe('input surface focus styles', () => {
  it('deja visible el foco global en inputs de modal', () => {
    expect(create2000sModalInputStyle()).not.toHaveProperty('outline')
  })

  it('deja visible el foco global en inputs del flujo de reserva', () => {
    expect(createBookingClientInputStyle()).not.toHaveProperty('outline')
  })
})
