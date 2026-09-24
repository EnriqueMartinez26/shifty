import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router'

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
    // El personal no tiene ningun hijo visible en "Mi Negocio": el grupo entero
    // no deberia renderizarse, ni siquiera colapsado.
    expect(screen.queryByRole('button', { name: /Mi Negocio/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Usuarios' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cerrar sesión' }))

    expect(mockLogout).toHaveBeenCalledTimes(1)
  })

  it('shows admin-only links inside their group once expanded, for a global admin', () => {
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

    // Colapsados por defecto: no estan en pantalla hasta abrir el grupo.
    expect(screen.queryByRole('link', { name: 'Usuarios' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Promociones' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Mi Negocio/ }))
    expect(screen.getByRole('link', { name: 'Usuarios' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Ventas/ }))
    expect(screen.getByRole('link', { name: 'Promociones' })).toBeInTheDocument()
  })

  it('auto-expands the group that contains the active route', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/ledger']}>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: 'Cuentas pendientes' })).toHaveAttribute(
      'href',
      '/dashboard/ledger'
    )
  })
})

describe('Sidebar: grupos que siguen a la ruta (F11a-11)', () => {
  const GoTo = ({ path }: { path: string }) => {
    const navigate = useNavigate()
    return (
      <button type="button" onClick={() => void navigate(path)}>
        {`ir a ${path}`}
      </button>
    )
  }

  const renderAt = (initial: string, targets: string[]) =>
    render(
      <MemoryRouter initialEntries={[initial]}>
        <Sidebar />
        {targets.map((path) => (
          <GoTo key={path} path={path} />
        ))}
      </MemoryRouter>
    )

  beforeEach(() => {
    mockUser = {
      first_name: 'Lara',
      email: 'lara@example.com',
      role: 'receptionist',
      is_global_admin: true
    }
  })

  it('navegar a una pagina de un grupo cerrado lo abre', () => {
    renderAt('/dashboard', ['/dashboard/ledger'])
    expect(screen.queryByRole('link', { name: 'Cuentas pendientes' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'ir a /dashboard/ledger' }))

    expect(screen.getByRole('link', { name: 'Cuentas pendientes' })).toBeInTheDocument()
  })

  it('un grupo cerrado a mano se reabre al navegar a una de sus paginas', () => {
    renderAt('/dashboard', ['/dashboard/ledger'])
    fireEvent.click(screen.getByRole('button', { name: /Ventas/ }))
    fireEvent.click(screen.getByRole('button', { name: /Ventas/ }))
    expect(screen.queryByRole('link', { name: 'Cuentas pendientes' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'ir a /dashboard/ledger' }))

    expect(screen.getByRole('link', { name: 'Cuentas pendientes' })).toBeInTheDocument()
  })

  it('cerrar el grupo de la pagina actual lo deja cerrado', () => {
    renderAt('/dashboard/ledger', [])
    expect(screen.getByRole('link', { name: 'Cuentas pendientes' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Ventas/ }))

    expect(screen.queryByRole('link', { name: 'Cuentas pendientes' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Ventas/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('un grupo abierto a mano sigue abierto al navegar fuera de el', () => {
    renderAt('/dashboard', ['/dashboard/calendar'])
    fireEvent.click(screen.getByRole('button', { name: /Mi Negocio/ }))
    expect(screen.getByRole('link', { name: 'Usuarios' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'ir a /dashboard/calendar' }))

    expect(screen.getByRole('link', { name: 'Usuarios' })).toBeInTheDocument()
  })
})
