import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Staff } from '@domain/entities/Staff'

import { StaffFormModal } from './StaffFormModal'

jest.mock('@presentation/hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: [] })
}))

const montar = (readOnlyReason?: string | null) =>
  render(
    <StaffFormModal
      isOpen
      onClose={jest.fn()}
      onSubmit={jest.fn().mockResolvedValue(undefined)}
      readOnlyReason={readOnlyReason}
    />
  )

describe('StaffFormModal: tienda suspendida', () => {
  // 2026-10-02: si la tienda se suspendia con el modal abierto, guardar
  // fallaba con 402 en vez de verse deshabilitado (FF-15). POST y PUT
  // /staff/... no estan en SUSPENSION_ALLOWED_WRITES.
  it('con la tienda suspendida guardar queda deshabilitado con el motivo', () => {
    montar('Tienda suspendida')

    const guardar = screen.getByRole('button', { name: 'Dar de Alta Profesional' })
    expect(guardar).toBeDisabled()
    expect(guardar).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('sin suspension guardar sigue habilitado y sin motivo', () => {
    montar()

    const guardar = screen.getByRole('button', { name: 'Dar de Alta Profesional' })
    expect(guardar).not.toBeDisabled()
    expect(guardar).not.toHaveAttribute('title')
  })
})

// 2026-10-08, decision de Mateo: el dueno se agrega como profesional con su
// cuenta. Nombre, apellido y email salen de la cuenta: no se piden.
describe('StaffFormModal: agregarme como profesional', () => {
  it('no pide nombre, apellido ni email y propone el nombre de la cuenta', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    render(
      <StaffFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={onSubmit}
        selfName="Enrique Martinez"
        selfEmail="duenio@example.com"
      />
    )

    expect(screen.getByText('Agregarme como profesional')).toBeInTheDocument()
    expect(screen.getByText(/no se crea otro usuario ni otra clave/i)).toHaveTextContent(
      'duenio@example.com'
    )
    expect(screen.queryByPlaceholderText('Ej: Marcelo')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('marcelo@shifty.com')).not.toBeInTheDocument()
    expect(screen.queryByRole('radiogroup', { name: 'Tipo' })).not.toBeInTheDocument()
    expect((screen.getByPlaceholderText('Ej: Marce R.') as HTMLInputElement).value).toBe(
      'Enrique Martinez'
    )

    fireEvent.click(screen.getByRole('button', { name: 'Agregarme' }))

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ display_name: 'Enrique Martinez', service_ids: [] })
      )
    )
  })

  it('editando la ficha propia el email de login no se cambia', () => {
    const propia = Staff.fromPrimitives({
      public_id: 'usr-duenio',
      kind: 'person',
      first_name: 'Enrique',
      last_name: 'Martinez',
      email: 'duenio@example.com',
      display_name: 'Enrique',
      is_active: true,
      service_ids: []
    })
    render(
      <StaffFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={jest.fn()}
        editingStaff={propia}
        isOwnAccount
      />
    )

    const email = screen.getByPlaceholderText('marcelo@shifty.com')
    expect(email).toHaveAttribute('readonly')
    const hint = document.getElementById(email.getAttribute('aria-describedby') ?? '')
    expect(hint).toHaveTextContent('Es el email con el que entrás: acá no se cambia.')
  })
})
