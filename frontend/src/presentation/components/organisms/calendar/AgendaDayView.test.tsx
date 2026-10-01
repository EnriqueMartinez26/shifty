import { fireEvent, render, screen } from '@testing-library/react'

import { AgendaDayView } from './AgendaDayView'
import type { DayGrid } from '../../../lib/calendarGrid'

// 2026-09-30: la vista dia salio de CalendarContainer (F11c-08). Solo pinta:
// abrir un hueco, editar un bloqueo y los controles de cada turno los decide
// el contenedor.

const dayGrid: DayGrid = {
  totalHeightPx: 300,
  bands: [
    {
      kind: 'open',
      startMinutes: 540,
      endMinutes: 600,
      topPx: 0,
      heightPx: 256,
      labels: [{ text: '09:00', topPx: 0 }]
    },
    {
      kind: 'closed',
      key: 'gap-600',
      startMinutes: 600,
      endMinutes: 840,
      topPx: 256,
      heightPx: 44,
      label: '10:00 - 14:00',
      expanded: false
    }
  ]
}

const staffMembers = [
  { id: 'st-1', displayName: 'Ana Gomez' },
  { id: 'st-2', displayName: 'Bruno Diaz' }
]

const block = {
  public_id: 'blk-1',
  staff_id: 'st-1',
  starts_at: '2026-09-15T12:00:00.000Z',
  ends_at: '2026-09-15T12:30:00.000Z',
  reason: 'Almuerzo'
}

const card = {
  id: 'apt-1',
  type: 'appointment' as const,
  staffId: 'st-2',
  staffName: 'Bruno Diaz',
  title: 'Carla Ruiz',
  subtitle: 'Corte',
  startsAt: new Date('2026-09-15T12:00:00Z'),
  endsAt: new Date('2026-09-15T12:30:00Z'),
  status: 'confirmed',
  clientPhone: null,
  serviceId: 'svc-1',
  top: '0px',
  height: '128px',
  timeLabel: '09:00'
}

const renderDayView = (loading = false) => {
  const handlers = {
    onToggleGap: jest.fn(),
    onEditBlock: jest.fn(),
    renderControls: jest.fn(() => <button type="button">Confirmar</button>)
  }
  render(
    <AgendaDayView
      staffMembers={staffMembers}
      loading={loading}
      dayGrid={dayGrid}
      hoursOfDay={{ byStaff: new Map([['st-1', null]]) }}
      blocks={[block]}
      cards={[card]}
      canManageBlocks={false}
      {...handlers}
    />
  )
  return handlers
}

describe('AgendaDayView', () => {
  it('pinta un encabezado por profesional con sus iniciales y la grilla', () => {
    renderDayView()
    expect(screen.getByText('AG')).toBeInTheDocument()
    expect(screen.getByText('Bruno Diaz')).toBeInTheDocument()
    expect(screen.getByText('09:00', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('Carla Ruiz')).toBeInTheDocument()
    expect(screen.queryByText('Actualizando agenda...')).not.toBeInTheDocument()
  })

  it('arma los controles de cada turno con renderControls', () => {
    const handlers = renderDayView()
    expect(handlers.renderControls).toHaveBeenCalledWith(card)
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeInTheDocument()
  })

  it('avisa el hueco cerrado por callback', () => {
    const handlers = renderDayView()
    const gap = screen.getByTitle('Cerrado 10:00 - 14:00')
    expect(gap).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(gap)
    expect(handlers.onToggleGap).toHaveBeenCalledWith('gap-600')
  })

  it('muestra el aviso de carga', () => {
    renderDayView(true)
    expect(screen.getByText('Actualizando agenda...')).toBeInTheDocument()
  })
})
