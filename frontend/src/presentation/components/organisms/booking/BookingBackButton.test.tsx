import { fireEvent, render, screen } from '@testing-library/react'

import { BookingBackButton } from './BookingBackButton'

describe('BookingBackButton', () => {
  it('vuelve al paso anterior con texto visible y 44 px', () => {
    const onBack = jest.fn()
    render(<BookingBackButton onBack={onBack} />)

    const volver = screen.getByRole('button', { name: 'Volver' })
    fireEvent.click(volver)

    expect(onBack).toHaveBeenCalledTimes(1)
    expect(volver).toHaveClass('min-h-11')
  })

  // QA visual 2026-10-21: pintado con el relleno de marca competia con el
  // unico boton principal del paso. Es secundario: superficie neutra.
  // S9 (2026-10-22): texto y borde neutros, nunca un tono de marca.
  it('es un boton secundario neutro: sin relleno ni tinta de marca', () => {
    render(<BookingBackButton onBack={() => undefined} />)

    const volver = screen.getByRole('button', { name: 'Volver' })
    const style = volver.getAttribute('style') ?? ''

    expect(style).not.toContain('--brand')
    expect(volver.style.color).toBe('rgb(64, 64, 64)')
  })
})
