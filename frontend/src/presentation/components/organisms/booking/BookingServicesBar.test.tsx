import { fireEvent, render, screen } from '@testing-library/react'

import { formatCurrency } from '@shared/utils/currency'

import { BookingServicesBar } from './BookingServicesBar'

// Varios servicios en un turno (2026-10-16): la barra solo pinta.
describe('BookingServicesBar', () => {
  it('dice cuantos servicios, cuanto dura el turno y cuanto suman', () => {
    render(
      <BookingServicesBar count={2} durationMinutes={45} listPrice={15000} onContinue={jest.fn()} />
    )

    expect(screen.getByRole('status')).toHaveTextContent(
      `2 servicios · 45 min · ${formatCurrency(15000)}`
    )
  })

  it('con uno solo habla en singular', () => {
    render(
      <BookingServicesBar count={1} durationMinutes={30} listPrice={10000} onContinue={jest.fn()} />
    )

    expect(screen.getByRole('status')).toHaveTextContent(/^1 servicio · 30 min/)
  })

  it('Continuar avisa al paso', () => {
    const onContinue = jest.fn()
    render(
      <BookingServicesBar
        count={2}
        durationMinutes={45}
        listPrice={15000}
        onContinue={onContinue}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
    expect(onContinue).toHaveBeenCalledTimes(1)
  })
})

// S3 (2026-10-21): el boton principal usa el color de la tienda.
describe('BookingServicesBar con el color de la tienda', () => {
  it('Continuar usa el relleno y el texto de marca', () => {
    render(
      <BookingServicesBar count={2} durationMinutes={45} listPrice={15000} onContinue={jest.fn()} />
    )

    const continuar = screen.getByRole('button', { name: /Continuar/ })
    expect(continuar.getAttribute('style')).toContain('var(--brand-fill,')
    expect(continuar.getAttribute('style')).toContain('var(--brand-on-fill,')
  })
})
