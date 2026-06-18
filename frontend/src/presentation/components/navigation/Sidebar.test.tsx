import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import Sidebar from './Sidebar'

const mockLogout = jest.fn()
let mockUser: {
  first_name: string
  email: string
  role: string
  is_global_admin: boolean
}

jest.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    logout: mockLogout
  })
}))

describe('Sidebar', () => {
  beforeEach(() => {
    mockLogout.mockReset()
    mockUser = {
      first_name: 'Ana',
      email: 'ana@example.com',
      role: 'professional',
      is_global_admin: false
    }
  })

  it('shows only the authorized menu items and logs out from the button', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/calendar']}>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/dashboard')
    expect(screen.getByRole('link', { name: 'Agenda' })).toHaveAttribute(
      'href',
      '/dashboard/calendar'
    )
    expect(screen.queryByRole('link', { name: 'Usuarios' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cerrar sesión' }))

    expect(mockLogout).toHaveBeenCalledTimes(1)
  })

  it('shows admin-only links when the user is global admin', () => {
    mockUser = {
      first_name: 'Lara',
      email: 'lara@example.com',
      role: 'receptionist',
      is_global_admin: true
    }

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: 'Usuarios' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Promociones' })).toBeInTheDocument()
  })
})
