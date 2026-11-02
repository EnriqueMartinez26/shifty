import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import Sidebar from '@presentation/components/navigation/Sidebar'
import ForgotPasswordPage from '@presentation/pages/ForgotPassword'

const logoutMock = jest.fn()

jest.mock('@presentation/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      first_name: 'Ana',
      email: 'ana@example.com',
      role: 'store_admin',
      is_global_admin: false
    },
    logout: logoutMock
  })
}))

jest.mock('@presentation/hooks/useForgotPassword', () => ({
  useForgotPassword: () => ({
    mutateAsync: jest.fn(),
    isPending: false
  })
}))

describe('accessibility smoke checks', () => {
  it('keeps sidebar navigation and logout focusable with native controls', () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    )

    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' })
    const logoutButton = screen.getByRole('button', { name: 'Cerrar sesión' })
    const userName = screen.getByText('Ana', { selector: 'p' })
    const userEmail = screen.getByText('ana@example.com', { selector: 'p' })

    expect(userName).toHaveClass('whitespace-normal', 'break-words')
    expect(userEmail).toHaveClass('whitespace-normal', 'break-all')
    expect(userName).not.toHaveClass('truncate')
    expect(userEmail).not.toHaveClass('truncate')

    // Programmatic focus also works for `tabIndex={-1}`; 0 keeps these native
    // controls in the normal keyboard sequence as well.
    expect(dashboardLink.tabIndex).toBe(0)
    expect(logoutButton.tabIndex).toBe(0)

    dashboardLink.focus()
    expect(dashboardLink).toHaveFocus()

    logoutButton.focus()
    expect(logoutButton).toHaveFocus()
  })

  it('keeps the forgot-password form keyboard accessible', () => {
    render(
      <MemoryRouter>
        <ForgotPasswordPage />
      </MemoryRouter>
    )

    const emailInput = screen.getByLabelText('Email')
    const submitButton = screen.getByRole('button', { name: 'Enviar enlace' })
    const backLink = screen.getByRole('link', { name: 'Volver a iniciar sesión' })

    expect(emailInput.tabIndex).toBe(0)
    expect(submitButton.tabIndex).toBe(0)
    expect(backLink.tabIndex).toBe(0)

    emailInput.focus()
    expect(emailInput).toHaveFocus()

    submitButton.focus()
    expect(submitButton).toHaveFocus()

    backLink.focus()
    expect(backLink).toHaveFocus()
  })
})
