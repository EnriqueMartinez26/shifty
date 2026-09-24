import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import ResetPasswordPage from './ResetPassword'

const mockMutateAsync = jest.fn()

jest.mock('../hooks/useResetPassword', () => ({
  useResetPassword: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false
  })
}))

describe('ResetPasswordPage', () => {
  it('rechaza una clave de menos de 12 caracteres sin llamar al backend (L1)', async () => {
    // El backend exige 12 (`ResetPasswordRequest`); con el piso viejo de 8,
    // una clave de 10 pasaba el formulario y volvia como 422.
    render(
      <MemoryRouter initialEntries={['/reset-password?token=abc']}>
        <ResetPasswordPage />
      </MemoryRouter>
    )

    fireEvent.change(screen.getByLabelText('Nueva contraseña'), {
      target: { value: 'corta12345' }
    })
    fireEvent.change(screen.getByLabelText('Confirmar contraseña'), {
      target: { value: 'corta12345' }
    })
    fireEvent.submit(screen.getByRole('button', { name: 'Actualizar contraseña' }).closest('form')!)

    expect(await screen.findByRole('alert')).toHaveTextContent('al menos 12 caracteres')
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })
})
