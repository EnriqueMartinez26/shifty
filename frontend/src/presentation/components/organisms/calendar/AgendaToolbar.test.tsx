import { fireEvent, render, screen } from '@testing-library/react'

import { AgendaToolbar } from './AgendaToolbar'

// 2026-09-30: la cabecera salio de CalendarContainer (F11c-08). Solo pinta:
// el salto de fecha y el cambio de vista los decide el contenedor.

const renderToolbar = () => {
  const handlers = {
    onPrev: jest.fn(),
    onNext: jest.fn(),
    onViewChange: jest.fn(),
    onNewAppointment: jest.fn()
  }
  render(<AgendaToolbar view="week" selectedDate={new Date(2026, 8, 15, 12)} {...handlers} />)
  return handlers
}

describe('AgendaToolbar', () => {
  it('muestra la vista activa y la fecha elegida', () => {
    renderToolbar()
    expect(screen.getByRole('heading', { name: 'Agenda' })).toBeInTheDocument()
    // QA 2026-10-02: date-fns sin locale mostraba '15 de September'.
    expect(screen.getByText('15 de septiembre')).toBeInTheDocument()
    expect(screen.getAllByText('Semana')).toHaveLength(2)
  })

  it('avisa las flechas, la vista elegida y el turno nuevo', () => {
    const handlers = renderToolbar()
    const [prev, next] = screen.getAllByRole('button').filter((button) => button.textContent === '')
    if (!prev || !next) throw new Error('faltan las flechas de navegación')
    fireEvent.click(prev)
    fireEvent.click(next)
    fireEvent.click(screen.getByRole('button', { name: 'Mes' }))
    fireEvent.click(screen.getByRole('button', { name: /Nuevo turno/ }))

    expect(handlers.onPrev).toHaveBeenCalledTimes(1)
    expect(handlers.onNext).toHaveBeenCalledTimes(1)
    expect(handlers.onViewChange).toHaveBeenCalledWith('month')
    expect(handlers.onNewAppointment).toHaveBeenCalledTimes(1)
  })

  it('mantiene los controles principales en un objetivo táctil de al menos 44 px', () => {
    renderToolbar()

    expect(screen.getByRole('button', { name: 'Anterior' })).toHaveClass('min-w-11', 'min-h-11')
    expect(screen.getByRole('button', { name: 'Siguiente' })).toHaveClass('min-w-11', 'min-h-11')
    for (const label of ['Día', 'Semana', 'Mes', 'Lista']) {
      expect(screen.getByRole('button', { name: label })).toHaveClass('min-h-11')
    }
    expect(screen.getByRole('button', { name: /Nuevo turno/ })).toHaveClass('min-h-11')
  })
})
