import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import ForgotPasswordPage from './ForgotPassword'

const mockMutateAsync = jest.fn()
let mockIsPending = false

jest.mock('../hooks/useForgotPassword', () => ({
  useForgotPassword: () => ({
    mutateAsync: mockMutateAsync,
    isPending: mockIsPending
  })
}))

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset()
    mockIsPending = false
  })

  it('submits the email and shows the success message', async () => {
    mockMutateAsync.mockResolvedValueOnce({
      message: 'Revisá tu casilla de correo.'
    })

    render(
      <MemoryRouter>
        <ForgotPasswordPage />
      </MemoryRouter>
    )

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'ana@example.com' }
    })
    fireEvent.submit(screen.getByRole('button', { name: 'Enviar enlace' }).closest('form')!)

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ email: 'ana@example.com' })
    })

    expect(await screen.findByRole('status')).toHaveTextContent('Revisá tu casilla de correo.')
  })

  it('shows the error message when the request fails', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('Servicio caído'))

    render(
      <MemoryRouter>
        <ForgotPasswordPage />
      </MemoryRouter>
    )

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'ana@example.com' }
    })
    fireEvent.submit(screen.getByRole('button', { name: 'Enviar enlace' }).closest('form')!)

    expect(await screen.findByRole('alert')).toHaveTextContent('Servicio caído')
  })

  it('renders the pending state as disabled and busy', () => {
    mockIsPending = true

    render(
      <MemoryRouter>
        <ForgotPasswordPage />
      </MemoryRouter>
    )

    const submitButton = screen.getByRole('button', { name: 'Enviando...' })

    expect(submitButton).toBeDisabled()
    expect(submitButton).toHaveAttribute('aria-busy', 'true')
  })
})
