import { fireEvent, render, screen } from '@testing-library/react'

import { AgendaRangeGrid } from './AgendaRangeGrid'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'

// 2026-09-30: la grilla de semana y mes salio de CalendarContainer (F11c-08).
// Cada evento lo pinta `renderEvent`, que decide el contenedor.

const eventOf = (id: string): UnifiedCalendarEvent => ({
  id,
  type: 'block',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  title: `Evento ${id}`,
  subtitle: 'Bloqueo',
  startsAt: new Date('2026-09-15T15:00:00Z'),
  endsAt: new Date('2026-09-15T16:00:00Z'),
  status: 'blocked'
})

const days = [new Date(2026, 8, 15), new Date(2026, 8, 16)]
const sixEvents = ['1', '2', '3', '4', '5', '6'].map(eventOf)
const eventsByDay = new Map([['2026-09-15', sixEvents]])

const renderEvent = (event: UnifiedCalendarEvent, compact: boolean) => (
  <p key={event.id}>{`${event.title}${compact ? ' (compacto)' : ''}`}</p>
)

const setTabletViewport = (matches: boolean) => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: jest.fn(() => ({
      matches,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn()
    }))
  })
}

beforeEach(() => setTabletViewport(false))

describe('AgendaRangeGrid', () => {
  it('en semana pinta todos los eventos del dia y avisa el dia vacio', () => {
    render(
      <AgendaRangeGrid
        days={days}
        eventsByDay={eventsByDay}
        compact={false}
        renderEvent={renderEvent}
      />
    )
    expect(screen.getByText('15/09')).toBeInTheDocument()
    // QA 2026-10-02: date-fns sin locale mostraba 'Tue'.
    expect(screen.getByText('mar')).toBeInTheDocument()
    expect(screen.getByText('mié')).toBeInTheDocument()
    expect(screen.getByText('Evento 6')).toBeInTheDocument()
    expect(screen.getByText('Sin eventos')).toBeInTheDocument()
  })

  it('en mes, en pantalla grande muestra 4 eventos y permite revelar el resto', () => {
    setTabletViewport(true)
    render(
      <AgendaRangeGrid days={days} eventsByDay={eventsByDay} compact renderEvent={renderEvent} />
    )
    expect(
      screen.getByRole('region', { name: 'Calendario mensual desplazable horizontalmente' })
    ).toHaveAttribute('tabindex', '0')
    expect(
      screen.getByText('Deslizá horizontalmente para ver todos los días del mes.')
    ).toHaveClass('md:block', 'xl:hidden')
    expect(screen.getByText('Evento 4 (compacto)').closest('[class~="md:hidden"]')).toBeNull()
    // El quinto en adelante solo se ve en el telefono, donde el mes es una lista.
    expect(screen.getByText('Evento 5 (compacto)').closest('[class~="md:hidden"]')).not.toBeNull()
    const showMore = screen.getByRole('button', { name: 'Mostrar 2 eventos más del 15/09' })
    expect(showMore).toHaveClass('hidden', 'md:flex', 'min-h-11', 'min-w-11')
    expect(showMore).toHaveAttribute('aria-controls', 'agenda-events-2026-09-15')
    expect(showMore).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('+2 eventos')).toBeInTheDocument()
    expect(screen.getByText('Evento 5 (compacto)').closest('[class~="md:hidden"]')).not.toBeNull()

    fireEvent.click(showMore)

    const showLess = screen.getByRole('button', { name: 'Mostrar menos eventos del 15/09' })
    const scrollableDay = screen.getByRole('group', { name: 'Eventos del 15/09' })
    expect(showLess).toHaveAttribute('aria-expanded', 'true')
    expect(scrollableDay).toHaveAttribute('tabindex', '0')
    expect(scrollableDay).toHaveAttribute(
      'aria-describedby',
      'agenda-events-2026-09-15-scroll-hint'
    )
    expect(
      screen.getByText('Deslizá verticalmente para recorrer los eventos del día.')
    ).toBeInTheDocument()
    expect(screen.getByText('Evento 5 (compacto)').closest('[class~="md:hidden"]')).toBeNull()
  })

  // QA movil 2026-10-08: la grilla del mes medía 900 px dentro de 343 y no se
  // podia usar. En el telefono el mes es una lista de los dias con eventos.
  it('en mes, el telefono ve una lista de una columna sin los dias vacios', () => {
    setTabletViewport(false)
    const { container } = render(
      <AgendaRangeGrid days={days} eventsByDay={eventsByDay} compact renderEvent={renderEvent} />
    )
    const grid = container.querySelector('.grid')
    expect(grid).toHaveClass('grid-cols-1', 'md:grid-cols-7')
    expect(grid).not.toHaveClass('min-w-[900px]')
    expect(screen.getByText('16/09').closest('[data-day]')).toHaveClass('hidden', 'md:block')
    expect(screen.getByText('15/09').closest('[data-day]')).not.toHaveClass('hidden')
    expect(
      screen.queryByRole('region', { name: 'Calendario mensual desplazable horizontalmente' })
    ).not.toBeInTheDocument()
  })

  it('en semana, una lista larga tiene scroll vertical accesible desde tablet', () => {
    setTabletViewport(true)
    render(
      <AgendaRangeGrid
        days={days}
        eventsByDay={eventsByDay}
        compact={false}
        renderEvent={renderEvent}
      />
    )
    const list = screen.getByText('Evento 1').parentElement
    expect(list).toHaveAttribute('tabindex', '0')
    expect(list).toHaveAttribute('aria-describedby', 'agenda-events-2026-09-15-scroll-hint')
    expect(list).toHaveClass('md:max-h-64', 'md:overflow-y-auto')
    expect(
      screen.getByText('Deslizá verticalmente para recorrer los eventos del día.')
    ).toBeInTheDocument()
  })
})
