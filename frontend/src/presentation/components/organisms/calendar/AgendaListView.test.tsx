import { render, screen, within } from '@testing-library/react'

import { AgendaListView } from './AgendaListView'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'

const eventOf = (id: string, startsAt: string): UnifiedCalendarEvent => ({
  id,
  type: 'block',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  title: `Evento ${id}`,
  subtitle: 'Bloqueo',
  startsAt: new Date(startsAt),
  endsAt: new Date(startsAt),
  status: 'blocked'
})

const renderEvent = (event: UnifiedCalendarEvent) => <p key={event.id}>{event.title}</p>

// 2026-10-02, QA en navegador: la vista Lista abarca dos semanas y pintaba
// todos los eventos seguidos, sin fecha, como si fueran del dia elegido.
describe('AgendaListView', () => {
  it('agrupa por dia con un encabezado en castellano, en orden', () => {
    const eventsByDay = new Map([
      ['2026-10-05', [eventOf('c', '2026-10-05T15:00:00Z')]],
      ['2026-10-02', [eventOf('b', '2026-10-02T18:00:00Z'), eventOf('a', '2026-10-02T12:00:00Z')]]
    ])

    render(<AgendaListView eventsByDay={eventsByDay} renderEvent={renderEvent} />)

    const headings = screen.getAllByRole('heading').map((h) => h.textContent)
    expect(headings).toEqual(['viernes 02/10', 'lunes 05/10'])
    const viernes = within(screen.getByRole('region', { name: 'viernes 02/10' }))
    expect(viernes.getAllByText(/Evento/).map((p) => p.textContent)).toEqual([
      'Evento a',
      'Evento b'
    ])
  })

  it('sin eventos lo dice', () => {
    render(<AgendaListView eventsByDay={new Map()} renderEvent={renderEvent} />)

    expect(screen.getByText('No hay eventos para el rango seleccionado.')).toBeInTheDocument()
  })
})
