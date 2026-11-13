import { fireEvent, render, screen } from '@testing-library/react'

import { AgendaToolbar } from './AgendaToolbar'

type View = 'day' | 'week' | 'month' | 'list'

const renderToolbar = (
  options: {
    mobile?: boolean
    view?: View
    mobileSingleDay?: boolean
  } = {}
) => {
  const handlers = {
    onPrev: jest.fn(),
    onNext: jest.fn(),
    onViewChange: jest.fn(),
    onNewAppointment: jest.fn(),
    onToggleMobileRange: jest.fn()
  }
  render(
    <AgendaToolbar
      view={options.view ?? 'week'}
      selectedDate={new Date(2026, 8, 15, 12)}
      mobileList={options.mobile ?? false}
      mobileSingleDay={options.mobileSingleDay ?? false}
      {...handlers}
    />
  )
  return handlers
}

describe('AgendaToolbar', () => {
  it('muestra la vista activa y la fecha elegida en escritorio', () => {
    renderToolbar()
    expect(screen.getByRole('heading', { name: 'Agenda' })).toBeInTheDocument()
    expect(screen.getByText('15 de septiembre')).toBeInTheDocument()
    expect(screen.getAllByText('Semana')).toHaveLength(2)
  })

  it('nombra las flechas y notifica navegación, vista y turno nuevo', () => {
    const handlers = renderToolbar()
    fireEvent.click(screen.getByRole('button', { name: 'Anterior' }))
    fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }))
    fireEvent.click(screen.getByRole('button', { name: 'Mes' }))
    fireEvent.click(screen.getByRole('button', { name: /Nuevo turno/ }))

    expect(handlers.onPrev).toHaveBeenCalledTimes(1)
    expect(handlers.onNext).toHaveBeenCalledTimes(1)
    expect(handlers.onViewChange).toHaveBeenCalledWith('month')
    expect(handlers.onNewAppointment).toHaveBeenCalledTimes(1)
  })

  it('mantiene los controles de escritorio en objetivos táctiles de al menos 44 px', () => {
    renderToolbar()

    expect(screen.getByRole('button', { name: 'Anterior' })).toHaveClass('min-w-11', 'min-h-11')
    expect(screen.getByRole('button', { name: 'Siguiente' })).toHaveClass('min-w-11', 'min-h-11')
    for (const label of ['Día', 'Semana', 'Mes', 'Lista']) {
      expect(screen.getByRole('button', { name: label })).toHaveClass('min-h-11')
    }
    expect(screen.getByRole('button', { name: /Nuevo turno/ })).toHaveClass('min-h-11')
  })

  it('ofrece accesos móviles y el selector conserva las cuatro vistas', () => {
    const handlers = renderToolbar({ mobile: true, view: 'list' })
    const listShortcut = screen.getByRole('button', { name: 'Lista' })
    const dayShortcut = screen.getByRole('button', { name: 'Día' })
    expect(listShortcut).toHaveAttribute('aria-pressed', 'true')
    expect(dayShortcut).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(listShortcut)
    fireEvent.click(dayShortcut)

    const select = screen.getByRole('combobox', { name: 'Vista de agenda' })
    expect(Array.from((select as HTMLSelectElement).options).map((option) => option.value)).toEqual(
      ['day', 'week', 'month', 'list']
    )
    for (const view of ['day', 'week', 'month', 'list'] as const) {
      fireEvent.change(select, { target: { value: view } })
      expect(handlers.onViewChange).toHaveBeenLastCalledWith(view)
    }
    expect(handlers.onViewChange).toHaveBeenNthCalledWith(1, 'list')
    expect(handlers.onViewChange).toHaveBeenNthCalledWith(2, 'day')
    expect(screen.getByRole('status')).toHaveTextContent('Lista en móvil · 14 días')
    expect(screen.queryByRole('group', { name: 'Vista de agenda' })).not.toBeInTheDocument()
  })

  it('mantiene el selector móvil y el cambio del rango de lista', () => {
    const handlers = renderToolbar({ mobile: true, view: 'list', mobileSingleDay: true })
    expect(screen.getByRole('status')).toHaveTextContent('Lista en móvil · 1 día')
    fireEvent.click(screen.getByRole('button', { name: 'Ver 14 días' }))
    expect(handlers.onToggleMobileRange).toHaveBeenCalledTimes(1)
  })

  it('impide crear turnos cuando la tienda está suspendida', () => {
    const onNewAppointment = jest.fn()
    render(
      <AgendaToolbar
        view="list"
        selectedDate={new Date(2026, 8, 15, 12)}
        onPrev={jest.fn()}
        onNext={jest.fn()}
        onViewChange={jest.fn()}
        onNewAppointment={onNewAppointment}
        readOnlyReason="Tienda suspendida"
      />
    )
    const button = screen.getByRole('button', { name: /Nuevo turno/ })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'Tienda suspendida')
    fireEvent.click(button)
    expect(onNewAppointment).not.toHaveBeenCalled()
  })
})
