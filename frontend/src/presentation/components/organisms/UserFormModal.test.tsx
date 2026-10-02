import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ValidationError } from '@shared/errors/ValidationError'

import { UserFormModal } from './UserFormModal'

const rules = { showAdminOption: false, canChangeRole: true, canChangePassword: true }

const fill = (password: string) => {
  const [email, password_] = [
    document.querySelector('input[type="email"]') as HTMLInputElement,
    document.querySelector('input[type="password"]') as HTMLInputElement
  ]
  fireEvent.change(email, { target: { value: 'nuevo@example.com' } })
  fireEvent.change(password_, { target: { value: password } })
}

const submit = () =>
  fireEvent.submit(document.querySelector('form') as HTMLFormElement, { target: {} })

// 2026-10-02, QA en navegador (S\48): un alta con contrasena corta respondia
// 422 y el modal decia "No se pudo guardar el usuario", sin el motivo.
describe('UserFormModal: errores de validacion', () => {
  it('una contrasena corta no se envia y dice la politica', () => {
    const onSubmit = jest.fn()
    render(<UserFormModal onClose={jest.fn()} onSubmit={onSubmit} rules={rules} />)

    fill('corta1')
    submit()

    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(/al menos 12 caracteres/)
  })

  it('un 422 del servidor en password dice la politica, nunca el texto crudo', async () => {
    const onSubmit = jest.fn().mockRejectedValue(
      new ValidationError('password: Value error, Esa contrasena es demasiado comun', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422,
        detail: ['password: Value error, Esa contrasena es demasiado comun; elegi otra']
      })
    )
    render(<UserFormModal onClose={jest.fn()} onSubmit={onSubmit} rules={rules} />)

    fill('Barberia2026ok')
    submit()

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(/contraseña/i)
    expect(alerta).not.toHaveTextContent(/Value error/)
  })
})
