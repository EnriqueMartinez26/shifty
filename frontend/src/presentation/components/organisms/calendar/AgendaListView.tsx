import React from 'react'

import { formatArgentinaDayHeading } from '@shared/utils/argentinaTime'

import { colors2000s } from '../../../../theme/colors'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'

interface AgendaListViewProps {
  /** Eventos por dia argentino (`yyyy-MM-dd`), en el orden en que se muestran. */
  eventsByDay: ReadonlyMap<string, readonly UnifiedCalendarEvent[]>
  renderEvent: (event: UnifiedCalendarEvent) => React.ReactNode
}

/**
 * Vista "Lista" de la agenda: un encabezado por dia y sus eventos por hora.
 * La lista abarca dos semanas; antes pintaba todos los eventos seguidos, sin
 * fecha, y parecian del dia elegido (QA 2026-10-02).
 */
export const AgendaListView: React.FC<AgendaListViewProps> = ({ eventsByDay, renderEvent }) => {
  const days = [...eventsByDay.keys()].sort()
  if (!days.length) {
    return (
      <div
        className="rounded-[6px] p-6 bg-white text-sm font-bold"
        style={{
          border: `1px solid ${colors2000s.border.light}`,
          boxShadow: colors2000s.shadows.insetDark,
          color: colors2000s.text.secondary
        }}
      >
        No hay eventos para el rango seleccionado.
      </div>
    )
  }
  return (
    <div className="space-y-5">
      {days.map((day) => {
        const events = [...(eventsByDay.get(day) ?? [])].sort(
          (left, right) => left.startsAt.getTime() - right.startsAt.getTime()
        )
        return (
          <section key={day} aria-label={formatArgentinaDayHeading(day)} className="space-y-3">
            <h3
              className="text-[11px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.orange.accent }}
            >
              {formatArgentinaDayHeading(day)}
            </h3>
            {events.map((event) => renderEvent(event))}
          </section>
        )
      })}
    </div>
  )
}
