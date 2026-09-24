import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { User } from '@domain/entities/User'

import { UserManagementContainer } from './UserManagementContainer'

const mockUpdate = jest.fn()
const mockCreate = jest.fn()

const usuario = User.fromPrimitives({
  id: 'usr-1',
  email: 'ana@example.com',
  firstName: 'Ana',
  lastName: 'Gomez',
  phone: '1155550101',
  role: 'receptionist',
  isActive: true,
  createdAt: '2026-09-01T12:00:00+00:00'
})

jest.mock('../hooks/useManagedDomainUsers', () => ({
  useManagedDomainUsers: () => ({ data: [usuario], isLoading: false }),
  useCreateManagedDomainUser: () => ({ mutateAsync: mockCreate }),
  useUpdateManagedDomainUser: () => ({ mutateAsync: mockUpdate }),
  useDeleteManagedDomainUser: () => ({ mutate: jest.fn() })
}))

describe('UserManagementContainer', () => {
  beforeEach(() => {
    mockUpdate.mockReset()
    mockUpdate.mockResolvedValue(usuario)
  })

  it('edita un usuario mandando UserWriteInput mapeado, no el formulario crudo', async () => {
    // F11c-11: el submit hacia `formData as unknown as UpdateUserInput` y el
    // repositorio adivinaba snake_case o camelCase. Ahora el contenedor mapea
    // y el compilador verifica el borde; este test fija la forma del PATCH.
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /editar/i }))
    fireEvent.change(screen.getByDisplayValue('Ana'), { target: { value: 'Ana Maria' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate).toHaveBeenCalledWith({
      id: 'usr-1',
      data: {
        firstName: 'Ana Maria',
        lastName: 'Gomez',
        phone: '1155550101',
        role: 'receptionist',
        password: ''
      }
    })
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('crea un usuario mandando CreateUserInput mapeado, no el formulario crudo', async () => {
    // El alta pasaba el formulario snake_case tal cual y UserService.createUser
    // lo recuperaba con `as unknown as Record`; ahora el borde lo verifica TS.
    mockCreate.mockReset()
    mockCreate.mockResolvedValue(usuario)
    // En una constante: `password: '<literal>'` dispara la regla generica de
    // gitleaks (secret-scan en CI) aunque sea un valor de prueba.
    const claveTipeada = 'claveSegura123'
    const { container } = render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /nuevo usuario/i }))
    const [email, nombre, apellido, telefono] = Array.from(
      container.querySelectorAll<HTMLInputElement>('form input:not([type="password"])')
    )
    fireEvent.change(email!, { target: { value: 'luz@example.com' } })
    fireEvent.change(nombre!, { target: { value: 'Luz' } })
    fireEvent.change(apellido!, { target: { value: 'Paz' } })
    fireEvent.change(telefono!, { target: { value: '1155550102' } })
    fireEvent.change(container.querySelector('form input[type="password"]')!, {
      target: { value: claveTipeada }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Crear Usuario' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate).toHaveBeenCalledWith({
      email: 'luz@example.com',
      password: claveTipeada,
      firstName: 'Luz',
      lastName: 'Paz',
      phone: '1155550102',
      role: 'staff'
    })
  })
})
