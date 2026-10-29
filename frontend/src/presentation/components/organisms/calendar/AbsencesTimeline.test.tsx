import { fireEvent, render, screen } from '@testing-library/react'

import { AbsencesTimeline } from './AbsencesTimeline'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'

// 2026-09-30: el panel de bloqueos y ausencias salio de CalendarContainer
// (F11c-08). No llama hooks: desactivar llega como callback (D-58).

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

const absence: UnifiedCalendarEvent = {
  id: 'apt-1',
  type: 'absence',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  title: 'Carla Ruiz',
  subtitle: 'Corte',
  startsAt: new Date('2026-09-15T13:00:00Z'),
  endsAt: new Date('2026-09-15T13:30:00Z'),
  status: 'absent',
  clientPhone: null,
  clientHasEmail: true,
  serviceId: 'svc-1'
}

describe('AbsencesTimeline', () => {
  it('lista bloqueos y ausencias en hora argentina', () => {
    render(
      <AbsencesTimeline
        events={[block, absence]}
        canManageBlocks={false}
        onEdit={jest.fn()}
        onDeactivate={jest.fn()}
      />
    )
    expect(screen.getByText('Almuerzo')).toBeInTheDocument()
    expect(screen.getByText('Ausencia')).toBeInTheDocument()
    expect(screen.getByText(/12:00 - 13:00 · Ana Gomez/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument()
  })

  it('edita y desactiva un bloqueo por callback', () => {
    const onEdit = jest.fn()
    const onDeactivate = jest.fn()
    render(
      <AbsencesTimeline
        events={[block, absence]}
        canManageBlocks
        onEdit={onEdit}
        onDeactivate={onDeactivate}
      />
    )
    expect(screen.getByRole('button', { name: 'Editar' })).toHaveClass('min-h-11')
    expect(screen.getByRole('button', { name: 'Desactivar' })).toHaveClass('min-h-11')
    fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Desactivar' }))

    expect(onEdit).toHaveBeenCalledWith({
      public_id: 'blk-1',
      staff_id: 'st-1',
      starts_at: '2026-09-15T15:00:00.000Z',
      ends_at: '2026-09-15T16:00:00.000Z',
      reason: 'Almuerzo'
    })
    expect(onDeactivate).toHaveBeenCalledWith('blk-1')
  })

  it('avisa cuando no hay nada en el rango', () => {
    render(
      <AbsencesTimeline events={[]} canManageBlocks onEdit={jest.fn()} onDeactivate={jest.fn()} />
    )
    expect(screen.getByText('No hay bloqueos ni ausencias en el rango actual.')).toBeInTheDocument()
  })

  it('conserva los eventos disponibles junto al aviso de un rango incompleto', () => {
    render(
      <AbsencesTimeline
        events={[block]}
        canManageBlocks
        onEdit={jest.fn()}
        onDeactivate={jest.fn()}
        statusMessage="No se pudo cargar el rango actual."
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar el rango actual.')
    expect(screen.getByText('Almuerzo')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Editar' })).toBeInTheDocument()
    expect(
      screen.queryByText('No hay bloqueos ni ausencias en el rango actual.')
    ).not.toBeInTheDocument()
  })
})
