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
  // unico boton principal del paso. Es secundario: superficie neutra, texto y
  // borde con el color de la tienda.
  it('es un boton secundario: sin relleno de marca, texto y borde en tinta de marca', () => {
    render(<BookingBackButton onBack={() => undefined} />)

    const style = screen.getByRole('button', { name: 'Volver' }).getAttribute('style') ?? ''

    expect(style).not.toContain('--brand-fill')
    expect(style).toContain('var(--brand-ink')
  })
})
