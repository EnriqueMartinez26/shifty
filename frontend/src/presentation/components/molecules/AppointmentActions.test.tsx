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
        canCancelOrReschedule={false}
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
        canCancelOrReschedule={false}
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
          canCancelOrReschedule={false}
          busy={false}
          onAction={onAction}
        />
      </div>
    )
    fireEvent.click(screen.getByRole('button', { name: 'El cliente no vino' }))
    expect(onAction).toHaveBeenCalledWith('absent')
    expect(onCard).not.toHaveBeenCalled()
  })

  // FF-31: cancelar y reprogramar un confirmado que todavia no empezo.
  it('ofrece cancelar y reprogramar a quien puede, y emite la accion elegida', () => {
    const onAction = jest.fn()
    render(
      <AppointmentActions
        status="confirmed"
        hasStarted={false}
        canRelease={false}
        canManage
        canCancelOrReschedule
        busy={false}
        onAction={onAction}
      />
    )
    expect(screen.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      'Cancelar turno',
      'Reprogramar turno'
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Reprogramar turno' }))
    expect(onAction).toHaveBeenCalledWith('reschedule')
  })

  // 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
  // verse deshabilitada (FF-15). Cancelar y liberar siguen (D-20260930-12).
  describe('con la tienda suspendida', () => {
    const reason = 'Tienda suspendida'
    const renderSuspended = (status: string, hasStarted: boolean, canRelease: boolean) => {
      const onAction = jest.fn()
      render(
        <AppointmentActions
          status={status}
          hasStarted={hasStarted}
          canRelease={canRelease}
          canManage
          canCancelOrReschedule
          busy={false}
          readOnlyReason={reason}
          onAction={onAction}
        />
      )
      return onAction
    }
    const expectBlocked = (name: string) => {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', reason)
    }

    it('confirmar y reprogramar quedan deshabilitados; liberar sigue', () => {
      const onAction = renderSuspended('pending', false, true)
      expectBlocked('Confirmar turno')
      expectBlocked('Reprogramar turno')
      fireEvent.click(screen.getByRole('button', { name: 'Liberar turno pendiente' }))
      expect(onAction).toHaveBeenCalledWith('release')
    })

    it('cancelar sigue habilitado', () => {
      const onAction = renderSuspended('confirmed', false, false)
      fireEvent.click(screen.getByRole('button', { name: 'Cancelar turno' }))
      expect(onAction).toHaveBeenCalledWith('cancel')
    })

    it('completar y ausente quedan deshabilitados', () => {
      renderSuspended('confirmed', true, false)
      expectBlocked('Marcar turno como completado')
      expectBlocked('El cliente no vino')
    })
  })

  it('sin suspension nada cambia: confirmar habilitado con su titulo', () => {
    render(
      <AppointmentActions
        status="pending"
        hasStarted={false}
        canRelease
        canManage
        canCancelOrReschedule
        busy={false}
        readOnlyReason={null}
        onAction={() => undefined}
      />
    )
    const confirmar = screen.getByRole('button', { name: 'Confirmar turno' })
    expect(confirmar).not.toBeDisabled()
    expect(confirmar).toHaveAttribute('title', 'Confirmar turno')
  })

  it('no renderiza nada cuando no hay acciones', () => {
    const { container } = render(
      <AppointmentActions
        status="cancelled"
        hasStarted
        canRelease
        canManage
        canCancelOrReschedule={false}
        busy={false}
        onAction={() => undefined}
      />
    )
    expect(container.innerHTML).toBe('')
  })
})
