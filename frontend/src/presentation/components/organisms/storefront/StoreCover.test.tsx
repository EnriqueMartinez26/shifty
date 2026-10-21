import { fireEvent, render, screen } from '@testing-library/react'

import { StoreCover } from './StoreCover'
import { resolveBrandTheme } from '../../../lib/brandTheme'

// 2026-10-21 (S2, portal publico): portada ancha debajo del encabezado; sin
// portada, una franja del color de la tienda.
// 2026-10-22 (S9): la portada va arriba de todo, de borde a borde en el
// celular; sin portada, un degradado suave del color de la tienda.
// 2026-10-22 (S10.1): con la foto real se veia el medio y se cortaba lo que
// importaba; la tienda elige que parte se ve (arriba, centro o abajo).

const brand = resolveBrandTheme('#123456')

describe('StoreCover', () => {
  it('con portada muestra la imagen decorativa, recortada, mas baja en el celular', () => {
    const { container } = render(<StoreCover coverUrl="/media/cover.webp" brand={brand} />)

    const img = container.querySelector('img')
    expect(img).toHaveAttribute('src', '/media/cover.webp')
    expect(img).toHaveAttribute('alt', '')
    expect(img).toHaveClass('h-full', 'w-full', 'object-cover')
    expect(img?.parentElement).toHaveClass('h-[140px]', 'sm:h-[232px]', 'w-full')
    expect(screen.queryByTestId('store-cover-band')).not.toBeInTheDocument()
  })

  it.each([
    ['top', 'center 20%'],
    ['center', 'center 50%'],
    ['bottom', 'center 80%']
  ] as const)('con el encuadre %s muestra la foto en %s', (position, objectPosition) => {
    const { container } = render(
      <StoreCover coverUrl="/media/cover.webp" coverPosition={position} brand={brand} />
    )

    expect(container.querySelector('img')?.style.objectPosition).toBe(objectPosition)
  })

  it('sin encuadre elegido muestra un poco por debajo del medio', () => {
    const { container, rerender } = render(
      <StoreCover coverUrl="/media/cover.webp" coverPosition={null} brand={brand} />
    )
    expect(container.querySelector('img')?.style.objectPosition).toBe('center 65%')

    // Un backend que todavia no manda el campo se ve igual.
    rerender(<StoreCover coverUrl="/media/cover.webp" brand={brand} />)
    expect(container.querySelector('img')?.style.objectPosition).toBe('center 65%')
  })

  it('sin portada pinta un degradado suave del color de marca, mas bajo', () => {
    const { container } = render(<StoreCover coverUrl={null} brand={brand} />)

    expect(container.querySelector('img')).toBeNull()
    const franja = screen.getByTestId('store-cover-band')
    expect(franja).toHaveClass('h-24', 'sm:h-40', 'w-full')
    expect(franja).toHaveAttribute('aria-hidden', 'true')
    expect(franja.getAttribute('style')).toContain('linear-gradient(')
    expect(franja.getAttribute('style')).toContain('rgba(18, 52, 86,')
  })

  it('si la portada no carga cae al degradado', () => {
    const { container } = render(
      <StoreCover coverUrl="https://otro-sitio.test/cover.png" brand={brand} />
    )

    fireEvent.error(container.querySelector('img') as HTMLImageElement)

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByTestId('store-cover-band').getAttribute('style')).toContain(
      'rgba(18, 52, 86,'
    )
  })
})
