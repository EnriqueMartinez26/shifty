import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import Sidebar from './Sidebar'

const mockLogout = jest.fn()
const mockAuth = {
  user: {
    first_name: 'Ana',
    email: 'ana@example.com',
    role: 'store_admin',
    is_global_admin: false
  },
  logout: mockLogout
}

jest.mock('../../context/AuthContext', () => ({
  useAuth: () => mockAuth
}))

const renderSidebar = (role: string, isGlobalAdmin = false) => {
  mockAuth.user = { ...mockAuth.user, role, is_global_admin: isGlobalAdmin }
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>
  )
}

const openSalesGroup = () => {
  fireEvent.click(screen.getByRole('button', { name: 'Ventas' }))
}

const openAllGroups = () => {
  openSalesGroup()
  fireEvent.click(screen.getByRole('button', { name: 'Mi Negocio' }))
}

describe('visibilidad de navegación del panel', () => {
  it('recepción ve agenda y tareas de tienda, sin enlaces financieros o de configuración', () => {
    renderSidebar('receptionist')

    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Agenda' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Lista de espera' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manual de uso' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reportes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ventas' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mi Negocio' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Configuración' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reservas del portal' })).not.toBeInTheDocument()
  })

  it('el profesional conserva reportes y cobros, pero no cobra online ni administra el negocio', () => {
    renderSidebar('professional')
    openSalesGroup()

    expect(screen.getByRole('link', { name: 'Reportes' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Cobros' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Cuentas pendientes' })).toBeInTheDocument()
    for (const name of [
      'Cobros online',
      'Promociones',
      'Servicios',
      'Personal',
      'Usuarios',
      'Reservas del portal'
    ]) {
      expect(screen.queryByRole('link', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('link', { name: 'Configuración' })).not.toBeInTheDocument()
  })

  it.each(['store_admin', 'admin', 'super_admin'])(
    '%s ve las opciones de administración de tienda',
    (role) => {
      renderSidebar(role)
      openAllGroups()

      for (const name of [
        'Cobros online',
        'Cobros',
        'Cuentas pendientes',
        'Promociones',
        'Reservas del portal',
        'Servicios',
        'Personal',
        'Usuarios',
        'Configuración'
      ]) {
        expect(screen.getByRole('link', { name })).toBeInTheDocument()
      }
    }
  )

  it('la marca global da la navegación de administración aunque el rol de cuenta sea cliente', () => {
    renderSidebar('client', true)
    openAllGroups()

    expect(screen.getByRole('link', { name: 'Cobros online' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Servicios' })).toBeInTheDocument()
  })
})
