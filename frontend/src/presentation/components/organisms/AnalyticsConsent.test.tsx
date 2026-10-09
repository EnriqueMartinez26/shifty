import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router'

import {
  enterBookingAnalytics,
  isAnalyticsConfigured,
  readAnalyticsConsent,
  setAnalyticsConsent
} from '@infrastructure/analytics/bookingAnalytics'

import { AnalyticsConsent } from './AnalyticsConsent'

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

it('aceptar y rechazar tienen la misma presentacion y se puede revocar', () => {
  render(
    <MemoryRouter initialEntries={['/b/tienda']}>
      <AnalyticsConsent />
    </MemoryRouter>
  )
  const accept = screen.getByRole('button', { name: 'Aceptar analítica' })
  const reject = screen.getByRole('button', { name: 'Rechazar analítica' })
  expect(accept.className).toBe(reject.className)
  fireEvent.click(accept)
  expect(setAnalyticsConsent).toHaveBeenLastCalledWith('accepted')
  fireEvent.click(screen.getByRole('button', { name: 'Preferencias de analítica' }))
  fireEvent.click(screen.getByRole('button', { name: 'Rechazar analítica' }))
  expect(setAnalyticsConsent).toHaveBeenLastCalledWith('rejected')
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
