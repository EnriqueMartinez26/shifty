import { fireEvent, render, screen } from '@testing-library/react'

import { AppointmentActions, availableActions } from './AppointmentActions'

describe('AppointmentActions', () => {
  it('un turno pendiente ofrece confirmar y, al admin, liberar', () => {
    const acciones = availableActions('pending', false, true, true).map((a) => a.action)
    expect(acciones).toEqual(['confirm', 'release'])
  })

  it('un turno confirmado que ya empezo ofrece completar y ausente', () => {
    const acciones = availableActions('confirmed', true, true, true).map((a) => a.action)
    expect(acciones).toEqual(['complete', 'absent'])
  })

  it('un turno confirmado que todavia no empezo no ofrece cerrar', () => {
    expect(availableActions('confirmed', false, true, true)).toEqual([])
  })

  it('los estados terminales no ofrecen nada', () => {
    for (const status of ['completed', 'cancelled', 'absent', 'expired']) {
      expect(availableActions(status, true, true, true)).toEqual([])
    }
  })

  it('el personal puede confirmar pero no liberar', () => {
    const acciones = availableActions('pending', false, false, true).map((a) => a.action)
    expect(acciones).toEqual(['confirm'])
  })

  it('dispara la accion sin propagar el click a la tarjeta', () => {
    const onAction = jest.fn()
    const onCard = jest.fn()
    render(
      <div onClick={onCard}>
        <AppointmentActions
          status="confirmed"
          hasStarted
          canRelease
          canManage
          busy={false}
          onAction={onAction}
        />
      </div>
    )
    fireEvent.click(screen.getByRole('button', { name: 'El cliente no vino' }))
    expect(onAction).toHaveBeenCalledWith('absent')
    expect(onCard).not.toHaveBeenCalled()
  })

  it('no renderiza nada cuando no hay acciones', () => {
    const { container } = render(
      <AppointmentActions
        status="cancelled"
        hasStarted
        canRelease
        canManage
        busy={false}
        onAction={() => undefined}
      />
    )
    expect(container.innerHTML).toBe('')
  })
})
