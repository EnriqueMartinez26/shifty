import type { ComponentProps } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { StoreHeader } from './StoreHeader'
import { resolveBrandTheme } from '../../../lib/brandTheme'

// 2026-10-21 (S1, portal publico): el encabezado decia "Reservar turno" con un
// icono generico; ahora es la tienda: logo, nombre, WhatsApp y "Mis turnos".

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
      whatsappNumber={null}
      misTurnosHref="/b/sol/mis-turnos"
      brand={brand}
      {...overrides}
    />
  )

describe('StoreHeader', () => {
  it('el nombre de la tienda es el titulo principal, en una linea y completo en el title', () => {
    const largo = 'Peluqueria y Barberia Sol de Mayo del Barrio Norte'
    renderHeader({ name: largo })

    const titulo = screen.getByRole('heading', { level: 1, name: largo })
    expect(titulo).toHaveClass('truncate')
    expect(titulo).toHaveAttribute('title', largo)
  })

  it('con logo muestra la imagen de la tienda', () => {
    renderHeader({ logoUrl: '/media/logo.png' })

    expect(screen.getByRole('img', { name: 'Logo de Peluqueria Sol' })).toHaveAttribute(
      'src',
      '/media/logo.png'
    )
  })

  it('sin logo muestra la inicial en un circulo con el color de marca', () => {
    renderHeader({ name: 'sol de mayo' })

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    const inicial = screen.getByText('S')
    expect(inicial).toHaveClass('rounded-full')
    expect(inicial.style.background).toBe(css(brand.fill))
    expect(inicial.style.color).toBe(css(brand.onFill))
  })

  it('si el logo no carga cae a la inicial', () => {
    renderHeader({ logoUrl: 'https://otro-sitio.test/logo.png' })

    fireEvent.error(screen.getByRole('img', { name: 'Logo de Peluqueria Sol' }))

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('P')).toHaveClass('rounded-full')
  })

  it('el WhatsApp de la tienda va debajo del nombre como link a wa.me', () => {
    renderHeader({ whatsappNumber: '351 555-1234' })

    const link = screen.getByRole('link', { name: '351 555-1234' })
    expect(link.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/5493515551234\?text=/)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveClass('min-h-11', 'min-w-11', 'break-all')
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

  it('"Mis turnos" lleva a la pagina del cliente con 44 px de alto', () => {
    renderHeader()

    const link = screen.getByRole('link', { name: 'Mis turnos' })
    expect(link).toHaveAttribute('href', '/b/sol/mis-turnos')
    expect(link).toHaveClass('min-h-11', 'shrink-0')
  })

  it('todo va en una fila que no se estira con un nombre largo', () => {
    renderHeader()

    const fila = screen.getByRole('banner')
    expect(fila).toHaveClass('flex', 'items-center')
    expect(fila).not.toHaveClass('flex-col')
    expect(screen.getByRole('heading', { level: 1 }).parentElement).toHaveClass('min-w-0', 'flex-1')
  })
})
