import type { ComponentProps } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { StoreHeader } from './StoreHeader'
import { colors2000s } from '../../../../theme/colors'
import { resolveBrandTheme } from '../../../lib/brandTheme'

// 2026-10-21 (S1, portal publico): el encabezado decia "Reservar turno" con un
// icono generico; ahora es la tienda: logo, nombre, WhatsApp y "Mis turnos".
// 2026-10-22 (S9, Mateo: "el banner se ve horrible"): la portada era una caja
// suelta debajo del encabezado. Ahora va arriba y el logo redondo la pisa,
// como la vidriera de una tienda; el texto es neutro, nunca un tono de marca.

const brand = resolveBrandTheme('#123456')
// jsdom guarda los colores como rgb(); se normaliza igual para comparar.
const css = (color: string) => {
  const probe = document.createElement('div')
  probe.style.color = color
  return probe.style.color
}

const renderHeader = (overrides: Partial<ComponentProps<typeof StoreHeader>> = {}) =>
  render(
    <StoreHeader
      name="Peluqueria Sol"
      logoUrl={null}
      coverUrl={null}
      whatsappNumber={null}
      misTurnosHref="/b/sol/mis-turnos"
      brand={brand}
      {...overrides}
    />
  )

const isBefore = (a: Element, b: Element) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

describe('StoreHeader', () => {
  it('la portada va primero, arriba del logo y del nombre', () => {
    const { container } = renderHeader({
      coverUrl: '/media/cover.webp',
      logoUrl: '/media/logo.png'
    })

    const portada = container.querySelector('img[src="/media/cover.webp"]') as HTMLElement
    expect(portada).toHaveAttribute('alt', '')
    const logo = screen.getByRole('img', { name: 'Logo de Peluqueria Sol' })
    expect(isBefore(portada, logo)).toBe(true)
    expect(isBefore(portada, screen.getByRole('heading', { level: 1 }))).toBe(true)
    expect(screen.getByRole('banner').firstElementChild?.contains(portada)).toBe(true)
  })

  it('la portada usa el encuadre que eligio la tienda', () => {
    const { container } = renderHeader({ coverUrl: '/media/cover.webp', coverPosition: 'top' })

    const portada = container.querySelector('img[src="/media/cover.webp"]') as HTMLElement
    expect(portada.style.objectPosition).toBe('center 20%')
  })

  it('sin portada el degradado del color de marca ocupa su lugar', () => {
    renderHeader()

    const franja = screen.getByTestId('store-cover-band')
    expect(screen.getByRole('banner').firstElementChild).toBe(franja)
    expect(franja.getAttribute('style')).toContain('rgba(18, 52, 86,')
  })

  it('el nombre es el unico h1: hasta dos lineas, neutro y completo en el title', () => {
    const largo = 'Peluqueria y Barberia Sol de Mayo del Barrio Norte'
    renderHeader({ name: largo })

    const titulo = screen.getByRole('heading', { level: 1, name: largo })
    expect(titulo).toHaveClass('line-clamp-2')
    expect(titulo).toHaveAttribute('title', largo)
    expect(titulo.style.color).toBe(css(colors2000s.text.primary))
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('con logo muestra la imagen redonda con aro blanco', () => {
    renderHeader({ logoUrl: '/media/logo.png' })

    const logo = screen.getByRole('img', { name: 'Logo de Peluqueria Sol' })
    expect(logo).toHaveAttribute('src', '/media/logo.png')
    expect(logo).toHaveClass('rounded-full', 'border-4', 'border-white')
  })

  it('sin logo muestra la inicial en un circulo con el color de marca y el mismo aro', () => {
    renderHeader({ name: 'sol de mayo' })

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    const inicial = screen.getByText('S')
    expect(inicial).toHaveClass('rounded-full', 'border-4', 'border-white')
    expect(inicial.style.background).toBe(css(brand.fill))
    expect(inicial.style.color).toBe(css(brand.onFill))
  })

  it('si el logo no carga cae a la inicial', () => {
    renderHeader({ logoUrl: 'https://otro-sitio.test/logo.png' })

    fireEvent.error(screen.getByRole('img', { name: 'Logo de Peluqueria Sol' }))

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('P')).toHaveClass('rounded-full')
  })

  it('el WhatsApp va debajo del nombre como link a wa.me, en texto neutro y con icono', () => {
    renderHeader({ whatsappNumber: '351 555-1234' })

    const link = screen.getByRole('link', { name: '351 555-1234' })
    expect(link.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/5493515551234\?text=/)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveClass('min-h-11', 'min-w-11', 'underline')
    expect(link.style.color).toBe(css(colors2000s.text.primary))
    expect(link.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(isBefore(screen.getByRole('heading', { level: 1 }), link)).toBe(true)
  })

  it('un WhatsApp que no se puede leer se muestra como texto, sin link', () => {
    renderHeader({ whatsappNumber: 'pedir en el local' })

    expect(screen.getByText('pedir en el local').closest('a')).toBeNull()
  })

  it('sin WhatsApp no muestra nada en su lugar', () => {
    renderHeader()

    expect(screen.queryByText('Reserva por web disponible')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link')).toHaveLength(1)
  })

  it('"Mis turnos" es un boton neutro de 44 px que lleva a la pagina del cliente', () => {
    renderHeader()

    const link = screen.getByRole('link', { name: 'Mis turnos' })
    expect(link).toHaveAttribute('href', '/b/sol/mis-turnos')
    expect(link).toHaveClass('min-h-11', 'min-w-11', 'shrink-0')
    expect(link.style.color).toBe(css(colors2000s.text.primary))
  })

  // QA 2026-10-21: en 360 px la pastilla con texto dejaba sin lugar a un
  // nombre corto como "Jaziz Nails Studio". Debajo de sm queda el icono solo.
  it('"Mis turnos" en el celular es solo el icono, con el mismo nombre accesible', () => {
    renderHeader({ name: 'Jaziz Nails Studio' })

    expect(screen.getByText('Mis turnos')).toHaveClass('sr-only', 'sm:not-sr-only')
  })

  it('ningun texto ni icono del encabezado usa el color de marca', () => {
    const { container } = renderHeader({ whatsappNumber: '351 555-1234' })

    const marca = css(brand.fill)
    const teñidos = Array.from(container.querySelectorAll<HTMLElement>('[style]')).filter(
      (el) => el.style.color === marca
    )
    expect(teñidos).toHaveLength(0)
    expect(container.innerHTML).not.toContain('--brand-ink')
  })
})
