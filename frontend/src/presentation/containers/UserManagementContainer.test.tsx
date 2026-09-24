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
})
