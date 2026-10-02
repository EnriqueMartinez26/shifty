import { render, screen } from '@testing-library/react'

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

  it('en mes corta en 4 eventos y cuenta el resto', () => {
    render(
      <AgendaRangeGrid days={days} eventsByDay={eventsByDay} compact renderEvent={renderEvent} />
    )
    expect(screen.getByText('Evento 4 (compacto)')).toBeInTheDocument()
    expect(screen.queryByText(/Evento 5/)).not.toBeInTheDocument()
    expect(screen.getByText('+2 eventos')).toBeInTheDocument()
  })
})
