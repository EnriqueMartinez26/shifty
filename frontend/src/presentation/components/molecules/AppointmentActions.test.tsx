import { fireEvent, render, screen } from '@testing-library/react'

import { AppointmentActions } from './AppointmentActions'

describe('AppointmentActions', () => {
  it('un estado desconocido no muestra ninguna accion (F8-03)', () => {
    const { container } = render(
      <AppointmentActions
        status="on_hold"
        hasStarted
        canRelease
        canManage
        busy={false}
        onAction={() => undefined}
      />
    )
    expect(container.innerHTML).toBe('')
  })

  it('pinta las acciones que decide el dominio, en su orden', () => {
    render(
      <AppointmentActions
        status="pending"
        hasStarted={false}
        canRelease
        canManage
        busy={false}
        onAction={() => undefined}
      />
    )
    expect(screen.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      'Confirmar turno',
      'Liberar turno pendiente'
    ])
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
