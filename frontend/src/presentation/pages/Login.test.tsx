import { mdiStore } from '@mdi/js'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'

import LoginPage from './Login'
import { colors2000s } from '../../theme/colors'

/**
 * 2026-09-28 (FF-36, D-20260928-06). Sintoma: al vencer la sesion el login
 * mandaba siempre a la ruta por defecto del rol y se perdia donde estaba.
 */

/** The value as jsdom normalizes it (hex to rgb), so it can be compared with `element.style`. */
const cssValue = (property: 'color' | 'border' | 'borderTop', value: string): string => {
  const probe = document.createElement('div')
  probe.style[property] = value
  return probe.style[property]
}

const mockMutateAsync = jest.fn()

jest.mock('../hooks/useLogin', () => ({
  useLogin: () => ({ mutateAsync: mockMutateAsync, isPending: false })
}))

const entrarDesde = (from: string) => {
  mockMutateAsync.mockResolvedValue({
    access_token: 't',
    user: { email: 'a@x.com', role: 'store_admin', store_id: 's1', public_id: 'usr-a' }
  })
  render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state: { from } }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<p>inicio</p>} />
        <Route path="/dashboard/calendar" element={<p>agenda</p>} />
      </Routes>
    </MemoryRouter>
  )
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@x.com' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave' } })
  fireEvent.click(screen.getByRole('button', { name: /Entrar al Panel/ }))
}

describe('LoginPage shell', () => {
  /** F11b-14: fija la cascara de la pagina antes de moverla a `AuthShell`. */
  it('renders the branding, card, forgot-password link and footer', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    )

    const heading = screen.getByRole('heading', { level: 1, name: 'Shifty' })
    expect(heading.className).toBe('text-3xl font-bold tracking-tight mb-1')
    expect(heading.style.color).toBe(cssValue('color', colors2000s.orange.accent))

    const subtitle = screen.getByText('Gestiona tus turnos, clientes y equipo')
    expect(subtitle.tagName).toBe('P')
    expect(subtitle.className).toBe('text-sm font-medium')
    expect(subtitle.style.color).toBe(cssValue('color', colors2000s.text.secondary))

    const header = heading.parentElement as HTMLElement
    expect(header.className).toBe('flex flex-col items-center mb-8')

    const iconBox = header.firstElementChild as HTMLElement
    expect(iconBox.className).toBe(
      'w-16 h-16 rounded-2xl flex items-center justify-center mb-4 rotate-3 relative overflow-hidden'
    )
    expect(iconBox.style.border).toBe(cssValue('border', `1px solid ${colors2000s.orange.accent}`))
    expect((iconBox.firstElementChild as HTMLElement).className).toBe(
      'absolute top-0 left-0 right-0 h-1/2 bg-white/20 pointer-events-none'
    )
    const icon = iconBox.querySelector('svg') as SVGElement
    expect(icon).toHaveAttribute('aria-hidden', 'true')
    expect(icon).toHaveAttribute('width', '30')
    expect(icon.querySelector('path')).toHaveAttribute('d', mdiStore)

    const column = header.parentElement as HTMLElement
    expect(column.className).toBe('w-full max-w-md p-8 relative z-10')
    expect((column.parentElement as HTMLElement).className).toBe(
      'min-h-screen w-full flex items-center justify-center relative overflow-hidden'
    )

    const form = screen.getByLabelText('Email').closest('form') as HTMLFormElement
    const card = form.parentElement as HTMLElement
    expect(card.className).toBe('p-8 rounded-3xl')
    expect(card.style.border).toBe(cssValue('border', `1px solid ${colors2000s.border.default}`))
    expect(card.lastElementChild).toBe(form)

    const forgot = screen.getByRole('link', { name: '¿Olvidaste tu contraseña?' })
    expect(forgot).toHaveAttribute('href', '/forgot-password')
    expect(forgot.className).toBe('text-xs transition-colors font-medium')
    expect(forgot.style.color).toBe(cssValue('color', colors2000s.orange.accent))
    expect(screen.queryByRole('link', { name: 'Volver a iniciar sesión' })).not.toBeInTheDocument()

    const copyright = screen.getByText('Copyright 2026 Shifty SaaS. Todos los derechos reservados.')
    expect(copyright.className).toBe('mt-8 text-center text-xs')
    expect(copyright.style.color).toBe(cssValue('color', colors2000s.text.disabled))
    expect(column.lastElementChild).toBe(copyright)
  })
})

describe('LoginPage', () => {
  it('vuelve a la ruta interna donde estaba', async () => {
    entrarDesde('/dashboard/calendar')

    expect(await screen.findByText('agenda')).toBeInTheDocument()
  })

  it('ignora un destino externo y va a la ruta del rol', async () => {
    entrarDesde('//evil.com/dashboard')

    expect(await screen.findByText('inicio')).toBeInTheDocument()
  })
})
