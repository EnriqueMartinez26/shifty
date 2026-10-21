import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'

import AdminLayout from './AdminLayout'

let mockSubscriptionQuery: {
  data?: { status: string }
}

jest.mock('../hooks/useStores', () => ({
  useStoreSubscription: () => mockSubscriptionQuery,
  useStoreSettings: () => ({ data: { name: 'Peluquería Sol' } })
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      first_name: 'Ana',
      email: 'ana@example.com',
      role: 'store_admin',
      is_global_admin: false
    },
    logout: jest.fn()
  })
}))

jest.mock('../components/molecules/SubscriptionBanner', () => ({
  SubscriptionBanner: () => null
}))
jest.mock('../components/navigation/NotificationsBell', () => ({
  __esModule: true,
  default: () => <button type="button">Notificaciones</button>
}))
jest.mock('../components/navigation/LegalFooterLinks', () => ({
  __esModule: true,
  default: () => null
}))

const originalMatchMedia = window.matchMedia
let desktop = false
let mediaListeners: Set<() => void>

const renderShell = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/calendar']}>
      <Routes>
        <Route path="/dashboard" element={<AdminLayout />}>
          <Route path="calendar" element={<button type="button">Acción principal</button>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )

describe('AdminLayout', () => {
  beforeEach(() => {
    desktop = false
    mediaListeners = new Set()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: jest.fn((query: string) => ({
        media: query,
        get matches() {
          return desktop
        },
        addEventListener: (_event: string, listener: () => void) => mediaListeners.add(listener),
        removeEventListener: (_event: string, listener: () => void) =>
          mediaListeners.delete(listener)
      }))
    })
    mockSubscriptionQuery = {
      data: undefined
    }
  })

  afterEach(() => {
    if (originalMatchMedia) {
      Object.defineProperty(window, 'matchMedia', {
        configurable: true,
        value: originalMatchMedia
      })
    } else {
      Reflect.deleteProperty(window, 'matchMedia')
    }
    document.body.style.overflow = ''
  })

  it('contiene el foco dentro del menú móvil y lo devuelve al cerrarlo con Escape', () => {
    const view = renderShell()
    const trigger = screen.getByRole('button', { name: 'Abrir menú de navegación' })
    const main = trigger.closest('main')
    const sidebar = view.container.querySelector('#admin-sidebar')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(trigger).toHaveAttribute('aria-controls', 'admin-sidebar')
    expect(trigger).toHaveClass('min-h-11', 'min-w-11')
    expect(sidebar).toHaveAttribute('inert')
    expect(screen.queryByRole('dialog', { name: 'Menú de navegación' })).not.toBeInTheDocument()

    fireEvent.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(main).toHaveAttribute('inert')
    expect(sidebar).not.toHaveAttribute('inert')
    expect(screen.getByRole('dialog', { name: 'Menú de navegación' })).toHaveAttribute(
      'aria-modal',
      'true'
    )
    const firstLink = within(sidebar as HTMLElement).getByRole('link', { name: 'Dashboard' })
    const closeButton = within(sidebar as HTMLElement).getByRole('button', {
      name: 'Cerrar menú de navegación'
    })
    const logout = within(sidebar as HTMLElement).getByRole('button', { name: 'Cerrar sesión' })
    expect(firstLink).toHaveFocus()
    expect(document.body.style.overflow).toBe('hidden')

    logout.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(closeButton).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(logout).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(main).not.toHaveAttribute('inert')
    expect(sidebar).toHaveAttribute('inert')
    expect(screen.queryByRole('dialog', { name: 'Menú de navegación' })).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe('')
  })

  it('permite cerrar desde el diálogo y devuelve el foco al disparador', () => {
    const view = renderShell()
    const trigger = screen.getByRole('button', { name: 'Abrir menú de navegación' })
    const sidebar = view.container.querySelector('#admin-sidebar') as HTMLElement
    const main = trigger.closest('main')

    fireEvent.click(trigger)
    const closeButton = within(sidebar).getByRole('button', {
      name: 'Cerrar menú de navegación'
    })
    expect(closeButton).toHaveClass('h-11', 'w-11')

    fireEvent.click(closeButton)

    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(main).not.toHaveAttribute('inert')
    expect(sidebar).toHaveAttribute('inert')
    expect(screen.queryByRole('dialog', { name: 'Menú de navegación' })).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe('')
    expect(trigger).toHaveFocus()
  })

  it('cierra el drawer al navegar desde un enlace', () => {
    const view = renderShell()
    const trigger = screen.getByRole('button', { name: 'Abrir menú de navegación' })
    const sidebar = view.container.querySelector('#admin-sidebar') as HTMLElement
    const main = trigger.closest('main')

    fireEvent.click(trigger)
    fireEvent.click(within(sidebar).getByRole('link', { name: 'Dashboard' }))

    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(main).not.toHaveAttribute('inert')
    expect(sidebar).toHaveAttribute('inert')
    expect(trigger).toHaveFocus()
  })

  it('devuelve el foco al cerrar con el fondo y mantiene el sidebar de escritorio disponible', () => {
    const view = renderShell()
    const trigger = screen.getByRole('button', { name: 'Abrir menú de navegación' })
    fireEvent.click(trigger)
    const backdrop = view.container.querySelector('.z-40')
    expect(backdrop).not.toBeNull()
    fireEvent.click(backdrop as Element)
    expect(trigger).toHaveFocus()

    act(() => {
      desktop = true
      mediaListeners.forEach((listener) => listener())
    })
    expect(view.container.querySelector('#admin-sidebar')).not.toHaveAttribute('inert')
    expect(screen.queryByRole('dialog', { name: 'Menú de navegación' })).not.toBeInTheDocument()
    expect(trigger.closest('main')).not.toHaveAttribute('inert')
    screen.getByRole('link', { name: 'Agenda' }).focus()
    expect(screen.getByRole('link', { name: 'Agenda' })).toHaveFocus()
  })
})
