import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import ForgotPasswordPage from '@presentation/pages/ForgotPassword'
import Sidebar from '@presentation/components/navigation/Sidebar'

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

    emailInput.focus()
    expect(emailInput).toHaveFocus()

    submitButton.focus()
    expect(submitButton).toHaveFocus()

    backLink.focus()
    expect(backLink).toHaveFocus()
  })
})
