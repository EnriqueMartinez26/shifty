import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Navigate, Route, Routes, useLocation } from 'react-router'

import { getContactEnv } from '@shared/utils/env'

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

// 2026-10-03: Ley 25.326 art. 6 pide identidad y contacto del responsable y la
// Res. 104/2005 un telefono o email de contacto. El repo es publico: los datos
// reales llegan por configuracion del build (VITE_LEGAL_RESPONSABLES,
// VITE_CONTACT_EMAIL, VITE_SUPPORT_WHATSAPP). Aca, valores de prueba.
describe('LegalPage: responsables y contacto', () => {
  const bloque = () => screen.queryByRole('region', { name: 'Responsables y contacto' })

  afterEach(() => {
    jest.mocked(getContactEnv).mockReturnValue({})
  })

  it.each([['/legal/terminos'], ['/legal/privacidad']])(
    'con todo configurado %s muestra responsables, email y WhatsApp',
    (ruta) => {
      jest.mocked(getContactEnv).mockReturnValue({
        legalResponsables: 'Persona Responsable Uno',
        contactEmail: 'responsable@example.com',
        supportWhatsApp: '5493510000000'
      })
      renderAt([ruta])

      const region = bloque()
      expect(region).not.toBeNull()
      expect(region).toHaveTextContent('Persona Responsable Uno')
      expect(screen.getByRole('link', { name: 'responsable@example.com' })).toHaveAttribute(
        'href',
        'mailto:responsable@example.com'
      )
      expect(screen.getByRole('link', { name: '+5493510000000' })).toHaveAttribute(
        'href',
        'https://wa.me/5493510000000'
      )
    }
  )

  it('con una parte configurada muestra solo esa linea, sin texto de relleno', () => {
    jest.mocked(getContactEnv).mockReturnValue({ contactEmail: 'responsable@example.com' })
    renderAt(['/legal/privacidad'])

    const region = bloque()
    expect(region).not.toBeNull()
    expect(region).toHaveTextContent('responsable@example.com')
    expect(region).not.toHaveTextContent(/Responsables:|WhatsApp/)
    expect(region).not.toHaveTextContent(/pendiente|COMPLETAR/i)
  })

  it('sin nada configurado (o con placeholders) no hay bloque ni texto de relleno', () => {
    jest.mocked(getContactEnv).mockReturnValue({
      legalResponsables: '[[COMPLETAR]]',
      contactEmail: 'pendiente',
      supportWhatsApp: ''
    })
    renderAt(['/legal/terminos'])

    expect(bloque()).toBeNull()
    expect(screen.queryByText(/COMPLETAR|\bpendiente\b/i)).toBeNull()
  })

  it('las consultas sobre los terminos van al email configurado', () => {
    jest.mocked(getContactEnv).mockReturnValue({ contactEmail: 'responsable@example.com' })
    renderAt(['/legal/terminos'])

    expect(
      screen.getByText(
        /^Para consultas sobre estos términos, escribinos a responsable@example\.com/
      )
    ).toBeInTheDocument()
    expect(screen.queryByText(/canales de contacto informados por la plataforma/)).toBeNull()
  })

  it('sin email, las consultas remiten a los canales de la plataforma como antes', () => {
    renderAt(['/legal/terminos'])

    expect(screen.getByText(/canales de contacto informados por la plataforma/)).toBeInTheDocument()
  })
})
