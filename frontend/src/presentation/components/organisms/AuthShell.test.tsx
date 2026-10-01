import type { ComponentProps } from 'react'

import { mdiStore } from '@mdi/js'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { AuthShell } from './AuthShell'
import { colors2000s } from '../../../theme/colors'

/** The value as jsdom normalizes it (hex to rgb), so it can be compared with `element.style`. */
const cssValue = (property: 'color' | 'border' | 'borderTop', value: string): string => {
  const probe = document.createElement('div')
  probe.style[property] = value
  return probe.style[property]
}

const renderShell = (props: Partial<ComponentProps<typeof AuthShell>> = {}) =>
  render(
    <MemoryRouter>
      <AuthShell title="Titulo" subtitle="Bajada" {...props}>
        <p>contenido</p>
      </AuthShell>
    </MemoryRouter>
  )

describe('AuthShell', () => {
  it('renders the title, the subtitle and the children inside the card', () => {
    renderShell()

    const heading = screen.getByRole('heading', { level: 1, name: 'Titulo' })
    expect(heading.className).toBe('text-3xl font-bold tracking-tight mb-1')
    expect(heading.style.color).toBe(cssValue('color', colors2000s.orange.accent))
    expect(screen.getByText('Bajada').tagName).toBe('P')

    const card = screen.getByText('contenido').parentElement as HTMLElement
    expect(card.className).toBe('p-8 rounded-3xl')
    expect(card.style.border).toBe(cssValue('border', `1px solid ${colors2000s.border.default}`))
  })

  it('renders the branding icon and the copyright', () => {
    renderShell()

    const heading = screen.getByRole('heading', { level: 1 })
    const iconBox = (heading.parentElement as HTMLElement).firstElementChild as HTMLElement
    expect(iconBox.className).toBe(
      'w-16 h-16 rounded-2xl flex items-center justify-center mb-4 rotate-3 relative overflow-hidden'
    )
    const icon = iconBox.querySelector('svg') as SVGElement
    expect(icon).toHaveAttribute('aria-hidden', 'true')
    expect(icon.querySelector('path')).toHaveAttribute('d', mdiStore)

    const copyright = screen.getByText('Copyright 2026 Shifty SaaS. Todos los derechos reservados.')
    expect(copyright.className).toBe('mt-8 text-center text-xs')
    expect(copyright.style.color).toBe(cssValue('color', colors2000s.text.disabled))
  })

  it('uses the recovery layout by default and omits the back link', () => {
    renderShell()

    const heading = screen.getByRole('heading', { level: 1 })
    const header = heading.parentElement as HTMLElement
    expect(header.className).toBe('flex flex-col items-center mb-8 text-center')
    expect((header.parentElement?.parentElement as HTMLElement).className).toBe(
      'min-h-screen w-full flex items-center justify-center relative overflow-hidden px-4'
    )
    expect(screen.queryByRole('link', { name: 'Volver a iniciar sesión' })).toBeNull()
  })

  it('keeps the original login layout with variant="login"', () => {
    renderShell({ variant: 'login' })

    const heading = screen.getByRole('heading', { level: 1 })
    const header = heading.parentElement as HTMLElement
    expect(header.className).toBe('flex flex-col items-center mb-8')
    expect((header.parentElement?.parentElement as HTMLElement).className).toBe(
      'min-h-screen w-full flex items-center justify-center relative overflow-hidden'
    )
  })

  it('renders the back-to-login footer after the children when requested', () => {
    renderShell({ showBackToLogin: true })

    const back = screen.getByRole('link', { name: 'Volver a iniciar sesión' })
    expect(back).toHaveAttribute('href', '/login')
    expect(back.className).toBe(
      'inline-flex items-center gap-2 text-sm font-bold transition-colors'
    )
    expect(back.style.color).toBe(cssValue('color', colors2000s.orange.accent))

    const footer = back.parentElement as HTMLElement
    expect(footer.className).toBe('mt-8 pt-8 text-center')
    expect(footer.style.borderTop).toBe(
      cssValue('borderTop', `1px solid ${colors2000s.border.light}`)
    )
    expect(footer.previousElementSibling).toBe(screen.getByText('contenido'))
    expect(footer.parentElement?.lastElementChild).toBe(footer)
  })
})
