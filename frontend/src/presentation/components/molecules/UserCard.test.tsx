import { fireEvent, render, screen } from '@testing-library/react'

import { User } from '@domain/entities/User'

import { UserCard } from './UserCard'
import { colors2000s } from '../../../theme/colors'

const relativeLuminance = (hex: string): number => {
  const channel = (offset: number) => parseInt(hex.slice(offset, offset + 2), 16) / 255
  const linear = (value: number) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4

  return 0.2126 * linear(channel(1)) + 0.7152 * linear(channel(3)) + 0.0722 * linear(channel(5))
}

const contrastWithWhite = (background: string): number =>
  1.05 / (relativeLuminance(background) + 0.05)

describe('UserCard', () => {
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

  it('envuelve nombres y correos largos en vez de recortarlos', () => {
    const user = User.fromPrimitives({
      id: 'user-1',
      email: 'staff@example.test',
      firstName: 'Lucía',
      lastName: 'Fernández',
      phone: '+54 11 5555 5555',
      role: 'client',
      isActive: true,
      createdAt: '2026-10-11T12:00:00.000Z'
    })

    render(<UserCard user={user} canDelete onEdit={jest.fn()} onDelete={jest.fn()} />)

    const name = screen.getByRole('heading', { name: 'Lucía Fernández' })
    const email = screen.getByText('staff@example.test', { selector: 'p' })
    expect(name).toHaveClass('whitespace-normal', 'break-words')
    expect(email).toHaveClass('whitespace-normal', 'break-words')
    expect(name).not.toHaveClass('truncate')
    expect(email).not.toHaveClass('truncate')
  })

  it('mantiene los botones de accion en targets tactiles de 44 px', () => {
    const user = User.fromPrimitives({
      id: 'user-2',
      email: 'staff@example.test',
      firstName: 'Ana',
      lastName: 'Perez',
      phone: null,
      role: 'client',
      isActive: true,
      createdAt: '2026-10-11T12:00:00.000Z'
    })

    render(<UserCard user={user} canDelete onEdit={jest.fn()} onDelete={jest.fn()} />)

    expect(screen.getByRole('button', { name: /editar/i })).toHaveClass('min-h-11')
    expect(screen.getByRole('button', { name: /eliminar/i })).toHaveClass('min-h-11')
  })

  it('usa dos stops azules que mantienen contraste AA para las iniciales blancas de admins', () => {
    const admin = User.fromPrimitives({
      id: 'admin-1',
      email: 'ana@example.test',
      firstName: 'Ana',
      lastName: 'Perez',
      phone: null,
      role: 'admin',
      isActive: true,
      createdAt: '2026-10-11T12:00:00.000Z'
    })

    render(<UserCard user={admin} canDelete={false} onEdit={jest.fn()} onDelete={jest.fn()} />)

    const initials = screen.getByText('AP')
    const style = initials.getAttribute('style') ?? ''
    const dark = colors2000s.status.info.dark
    const accent = colors2000s.status.info.accent

    expect(style).toContain(`linear-gradient(180deg, ${dark} 0%, ${accent} 100%)`)
    expect(contrastWithWhite(dark)).toBeGreaterThanOrEqual(4.5)
    expect(contrastWithWhite(accent)).toBeGreaterThanOrEqual(4.5)
    expect(style).not.toContain(colors2000s.status.info.light)
  })
})
