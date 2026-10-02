import { render, screen } from '@testing-library/react'

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
