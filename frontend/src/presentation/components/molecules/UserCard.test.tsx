import { fireEvent, render, screen } from '@testing-library/react'

import { User } from '@domain/entities/User'

import { UserCard } from './UserCard'

const usuario = User.fromPrimitives({
  id: '01J8ZQ4Y7XKQ3M0B5N6P7R8S9T',
  email: 'ana@example.com',
  firstName: 'Ana',
  lastName: 'Perez',
  phone: null,
  role: 'staff',
  isActive: true,
  createdAt: '2026-09-10T12:00:00.000Z'
})

describe('UserCard', () => {
  // 2026-10-14: una tarjeta con botones no se escala. Al apretar, `active:scale`
  // la achica hacia el centro y corre los botones: el mouseup cae afuera y el
  // click se pierde (mismo bug que la tarjeta de la agenda del dia).
  it('la tarjeta no se escala al pasar ni al apretar', () => {
    const { container } = render(
      <UserCard user={usuario} onEdit={jest.fn()} onDelete={jest.fn()} canDelete />
    )

    const tarjeta = container.firstElementChild as HTMLElement
    expect(Array.from(tarjeta.classList).filter((name) => /(^|:)-?scale-/.test(name))).toEqual([])
  })

  it('Editar y Eliminar reciben el click', () => {
    const onEdit = jest.fn()
    const onDelete = jest.fn()
    render(<UserCard user={usuario} onEdit={onEdit} onDelete={onDelete} canDelete />)

    fireEvent.click(screen.getByRole('button', { name: /editar/i }))
    fireEvent.click(screen.getByRole('button', { name: /eliminar/i }))

    expect(onEdit).toHaveBeenCalledWith(usuario)
    expect(onDelete).toHaveBeenCalledWith(usuario.id)
  })
})
