import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Navigate, Route, Routes, useLocation } from 'react-router'

import LegalPage from './Legal'

const CurrentPath = () => <span data-testid="path">{useLocation().pathname}</span>

const renderAt = (entries: string[]) =>
  render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <Routes>
        <Route path="/legal/:document" element={<LegalPage />} />
        <Route path="*" element={<CurrentPath />} />
      </Routes>
    </MemoryRouter>
  )

describe('LegalPage', () => {
  it('renders a navigation bar whose home link points to /', () => {
    renderAt(['/legal/terminos'])

    expect(
      screen.getByRole('heading', { level: 1, name: 'Términos y Condiciones' })
    ).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Navegación' })
    const home = screen.getByRole('link', { name: 'Inicio' })
    expect(nav.contains(home)).toBe(true)
    expect(home).toHaveAttribute('href', '/')
  })

  it('opened as the first page of the tab offers no "Volver" (there is nowhere to go back)', () => {
    renderAt(['/legal/terminos'])

    expect(screen.queryByRole('button', { name: 'Volver' })).toBeNull()
  })

  it('after navigating inside the app, "Volver" goes back to the previous page', () => {
    renderAt(['/b/mi-tienda', '/legal/terminos'])

    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))

    expect(screen.getByTestId('path')).toHaveTextContent('/b/mi-tienda')
  })

  it('reached through the /legal redirect as the first page, offers no "Volver"', () => {
    render(
      <MemoryRouter initialEntries={['/legal']}>
        <Routes>
          <Route path="/legal" element={<Navigate to="/legal/terminos" replace />} />
          <Route path="/legal/:document" element={<LegalPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: 'Inicio' })).toHaveAttribute('href', '/')
    expect(screen.queryByRole('button', { name: 'Volver' })).toBeNull()
  })

  it('renders the privacy policy with a link to the terms', () => {
    renderAt(['/legal/privacidad'])

    expect(
      screen.getByRole('heading', { level: 1, name: 'Política de Privacidad' })
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver Términos y Condiciones' })).toHaveAttribute(
      'href',
      '/legal/terminos'
    )
  })

  it('reads the document in a centered column with 16px body text', () => {
    renderAt(['/legal/terminos'])

    const main = screen.getByRole('main')
    expect(main.className).toBe('max-w-3xl mx-auto')
    const paragraph = screen.getByText(/^Shifty provee únicamente la herramienta/)
    expect(paragraph.className).toBe('text-base leading-7 mb-3')
  })

  it('an unknown document is a 404, not the terms under another address', () => {
    renderAt(['/legal/cookies'])

    expect(
      screen.getByRole('heading', { level: 1, name: 'Página no encontrada' })
    ).toBeInTheDocument()
    expect(screen.queryByText('Términos y Condiciones')).toBeNull()
  })
})
