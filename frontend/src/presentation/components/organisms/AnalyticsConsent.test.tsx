import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router'

import {
  enterBookingAnalytics,
  isAnalyticsConfigured,
  readAnalyticsConsent,
  setAnalyticsConsent
} from '@infrastructure/analytics/bookingAnalytics'

import { AnalyticsConsent } from './AnalyticsConsent'
import LegalFooterLinks from '../navigation/LegalFooterLinks'

const mockLeave = jest.fn()
jest.mock('@infrastructure/analytics/bookingAnalytics', () => ({
  ...jest.requireActual('@infrastructure/analytics/bookingAnalytics'),
  enterBookingAnalytics: jest.fn(() => mockLeave),
  isAnalyticsConfigured: jest.fn(() => true),
  readAnalyticsConsent: jest.fn(() => null),
  setAnalyticsConsent: jest.fn()
}))

const Exit = () => {
  const navigate = useNavigate()
  return <button onClick={() => void navigate('/login')}>Salir</button>
}

beforeEach(() => {
  jest.clearAllMocks()
  jest.mocked(isAnalyticsConfigured).mockReturnValue(true)
  jest.mocked(readAnalyticsConsent).mockReturnValue(null)
})

it('aceptar y rechazar tienen la misma presentacion y se puede revocar desde el pie', () => {
  render(
    <MemoryRouter initialEntries={['/b/tienda']}>
      <AnalyticsConsent />
      <LegalFooterLinks analyticsPreferences />
    </MemoryRouter>
  )
  const accept = screen.getByRole('button', { name: 'Aceptar analítica' })
  const reject = screen.getByRole('button', { name: 'Rechazar analítica' })
  expect(accept.className).toBe(reject.className)
  expect(accept.getAttribute('style')).toBe(reject.getAttribute('style'))
  fireEvent.click(accept)
  expect(setAnalyticsConsent).toHaveBeenLastCalledWith('accepted')
  expect(screen.queryByText(/Aceptás Google/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Preferencias de analítica' }))
  fireEvent.click(screen.getByRole('button', { name: 'Rechazar analítica' }))
  expect(setAnalyticsConsent).toHaveBeenLastCalledWith('rejected')
})

// 2026-11-02: dos clientas de jaziz-nails vieron el boton flotante tapar
// "Continuar" en el celular y lo tomaron por un cartel externo.
it('despues de elegir no queda ningun control flotante sobre el portal', () => {
  render(
    <MemoryRouter initialEntries={['/b/tienda']}>
      <AnalyticsConsent />
    </MemoryRouter>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Aceptar analítica' }))
  expect(
    screen.queryByRole('button', { name: 'Preferencias de analítica' })
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole('region', { name: 'Preferencias de analítica' })
  ).not.toBeInTheDocument()
})

it('con una eleccion guardada el aviso no aparece hasta tocar el enlace del pie', () => {
  jest.mocked(readAnalyticsConsent).mockReturnValue('rejected')
  render(
    <MemoryRouter initialEntries={['/b/tienda']}>
      <AnalyticsConsent />
      <LegalFooterLinks analyticsPreferences />
    </MemoryRouter>
  )
  expect(screen.queryByText(/Aceptás Google/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Preferencias de analítica' }))
  expect(screen.getByText(/Aceptás Google/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar' }))
  expect(screen.queryByText(/Aceptás Google/)).not.toBeInTheDocument()
})

it('el pie solo ofrece preferencias en el portal y con analitica configurada', () => {
  jest.mocked(isAnalyticsConfigured).mockReturnValue(false)
  const { unmount } = render(
    <MemoryRouter initialEntries={['/b/tienda']}>
      <LegalFooterLinks analyticsPreferences />
    </MemoryRouter>
  )
  expect(
    screen.queryByRole('button', { name: 'Preferencias de analítica' })
  ).not.toBeInTheDocument()
  unmount()
  jest.mocked(isAnalyticsConfigured).mockReturnValue(true)
  render(
    <MemoryRouter initialEntries={['/login']}>
      <LegalFooterLinks />
    </MemoryRouter>
  )
  expect(
    screen.queryByRole('button', { name: 'Preferencias de analítica' })
  ).not.toBeInTheDocument()
})

it('sin ID valido no hay aviso ni inicializacion', () => {
  jest.mocked(isAnalyticsConfigured).mockReturnValue(false)
  render(
    <MemoryRouter initialEntries={['/booking/tienda']}>
      <AnalyticsConsent />
    </MemoryRouter>
  )
  expect(screen.queryByText(/Aceptás Google/)).not.toBeInTheDocument()
  expect(enterBookingAnalytics).not.toHaveBeenCalled()
})

it.each(['/login', '/dashboard', '/reset-password?token=secret', '/b/tienda/mis-turnos'])(
  'no monta analitica en %s',
  (path) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <AnalyticsConsent />
      </MemoryRouter>
    )
    expect(enterBookingAnalytics).not.toHaveBeenCalled()
    expect(screen.queryByText(/Aceptás Google/)).not.toBeInTheDocument()
  }
)

it('salir del portal llama a la guarda que bloquea el tag', () => {
  render(
    <MemoryRouter initialEntries={['/booking/tienda']}>
      <AnalyticsConsent />
      <Exit />
    </MemoryRouter>
  )
  expect(enterBookingAnalytics).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByText('Salir'))
  expect(mockLeave).toHaveBeenCalledTimes(1)
  expect(screen.queryByText(/Aceptás Google/)).not.toBeInTheDocument()
})
