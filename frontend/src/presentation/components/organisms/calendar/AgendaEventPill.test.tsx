import { render, screen } from '@testing-library/react'

import { AgendaEventPill } from './AgendaEventPill'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'

// 2026-09-30: la pastilla de un evento salio de CalendarContainer (F11c-08).
// Las acciones llegan armadas por el contenedor en el slot `actions`.

const appointment: UnifiedCalendarEvent = {
  id: 'apt-1',
  type: 'appointment',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  title: 'Carla Ruiz',
  subtitle: 'Corte',
  startsAt: new Date('2026-09-15T13:00:00Z'),
  endsAt: new Date('2026-09-15T13:30:00Z'),
  status: 'confirmed',
  clientPhone: null,
  serviceId: 'svc-1'
}

const block: UnifiedCalendarEvent = {
  id: 'blk-1',
  type: 'block',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  title: 'Almuerzo',
  subtitle: 'Bloqueo',
  startsAt: new Date('2026-09-15T15:00:00Z'),
  endsAt: new Date('2026-09-15T16:00:00Z'),
  status: 'blocked'
}

describe('AgendaEventPill', () => {
  it('muestra estado, titulo, horario argentino y el slot de acciones', () => {
    render(
      <AgendaEventPill event={appointment} actions={<button type="button">Confirmar</button>} />
    )
    expect(screen.getByText('confirmed')).toBeInTheDocument()
    expect(screen.getByText('Carla Ruiz')).toBeInTheDocument()
    expect(screen.getByText(/10:00 - 10:30 · Ana Gomez/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeInTheDocument()
  })

  it('rotula un bloqueo como Bloqueo en la version compacta', () => {
    render(<AgendaEventPill event={block} compact actions={null} />)
    expect(screen.getByText('Bloqueo')).toBeInTheDocument()
    expect(screen.getByText('Almuerzo')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
