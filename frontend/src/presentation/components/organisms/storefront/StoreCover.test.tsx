import { fireEvent, render, screen } from '@testing-library/react'

import { StoreCover } from './StoreCover'
import { resolveBrandTheme } from '../../../lib/brandTheme'

// 2026-10-21 (S2, portal publico): portada ancha debajo del encabezado; sin
// portada, una franja del color de la tienda.

const brand = resolveBrandTheme('#123456')
// jsdom guarda los colores como rgb(); se normaliza igual para comparar.
const css = (color: string) => {
  const probe = document.createElement('div')
  probe.style.color = color
  return probe.style.color
}

describe('StoreCover', () => {
  it('con portada muestra la imagen decorativa, recortada y con alto acotado', () => {
    const { container } = render(<StoreCover coverUrl="/media/cover.webp" brand={brand} />)

    const img = container.querySelector('img')
    expect(img).toHaveAttribute('src', '/media/cover.webp')
    expect(img).toHaveAttribute('alt', '')
    expect(img).toHaveClass('object-cover')
    expect(img?.parentElement).toHaveClass('aspect-[3/1]', 'max-h-48')
    expect(screen.queryByTestId('store-cover-band')).not.toBeInTheDocument()
  })

  it('sin portada pinta una franja fina del color de marca', () => {
    const { container } = render(<StoreCover coverUrl={null} brand={brand} />)

    expect(container.querySelector('img')).toBeNull()
    const franja = screen.getByTestId('store-cover-band')
    expect(franja).toHaveClass('h-2.5')
    expect(franja).toHaveAttribute('aria-hidden', 'true')
    expect(franja.style.background).toBe(css(brand.fill))
  })

  it('si la portada no carga cae a la franja', () => {
    const { container } = render(
      <StoreCover coverUrl="https://otro-sitio.test/cover.png" brand={brand} />
    )

    fireEvent.error(container.querySelector('img') as HTMLImageElement)

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByTestId('store-cover-band').style.background).toBe(css(brand.fill))
  })
})
