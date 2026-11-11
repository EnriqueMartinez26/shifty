import React, { useEffect, useId, useState } from 'react'

import { ChevronDown, ChevronUp } from 'lucide-react'

import { formatArgentinaDayHeading } from '@shared/utils/argentinaTime'

import { colors2000s } from '../../../../theme/colors'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'

interface AgendaListViewProps {
  /** Eventos por dia argentino (`yyyy-MM-dd`), en el orden en que se muestran. */
  eventsByDay: ReadonlyMap<string, readonly UnifiedCalendarEvent[]>
  selectedDateKey: string
  /** Identifica el rango visible, no la referencia del mapa de eventos. */
  rangeKey: string
  renderEvent: (event: UnifiedCalendarEvent) => React.ReactNode
}

type AgendaListContentProps = Omit<AgendaListViewProps, 'rangeKey'>

const FIRST_AVAILABLE = Symbol('firstAvailable')

const AgendaListContent: React.FC<AgendaListContentProps> = ({
  eventsByDay,
  selectedDateKey,
  renderEvent
}) => {
  const id = useId()
  // undefined: apertura inicial; null: cierre manual; string: dia elegido.
  const [selection, setSelection] = useState<string | null | undefined | typeof FIRST_AVAILABLE>(
    undefined
  )
  const days = [...eventsByDay.keys()].sort()
  const firstDay = days[0]
  const defaultDay = eventsByDay.has(selectedDateKey) ? selectedDateKey : firstDay

  useEffect(() => {
    if (selection === undefined || selection === null) return
    if (selection === FIRST_AVAILABLE) {
      if (firstDay) setSelection(firstDay)
      return
    }
    if (!eventsByDay.has(selection)) setSelection(firstDay ?? FIRST_AVAILABLE)
  }, [eventsByDay, firstDay, selection])

  const expandedDay =
    selection === undefined
      ? defaultDay
      : selection === FIRST_AVAILABLE
        ? firstDay
        : typeof selection === 'string' && eventsByDay.has(selection)
          ? selection
          : undefined

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
    <div className="space-y-3 md:space-y-5">
      {days.map((day) => {
        const events = [...(eventsByDay.get(day) ?? [])].sort(
          (left, right) => left.startsAt.getTime() - right.startsAt.getTime()
        )
        const heading = formatArgentinaDayHeading(day)
        const expanded = expandedDay === day
        const panelId = `${id}-${day}`
        return (
          <section key={day} aria-label={heading} className="space-y-3">
            <h3 className="md:hidden">
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={panelId}
                onClick={() => setSelection(expanded ? null : day)}
                className="flex min-h-[44px] w-full items-center gap-2 rounded-[6px] border bg-white px-3 py-2 text-left"
                style={{ borderColor: colors2000s.border.light, color: colors2000s.text.primary }}
              >
                <span className="min-w-0 flex-1 text-sm font-black uppercase">{heading}</span>
                <span
                  className="shrink-0 rounded-full border px-2 py-1 text-xs font-bold"
                  style={{
                    borderColor: colors2000s.border.light,
                    background: colors2000s.bg.button,
                    color: colors2000s.text.primary
                  }}
                >
                  {events.length === 1 ? '1 evento' : `${events.length} eventos`}
                </span>
                {expanded ? (
                  <ChevronUp size={18} aria-hidden="true" />
                ) : (
                  <ChevronDown size={18} aria-hidden="true" />
                )}
              </button>
            </h3>
            <h3
              className="hidden text-[11px] font-black uppercase tracking-widest md:block"
              style={{ color: colors2000s.orange.accent }}
            >
              {heading}
            </h3>
            <div
              id={panelId}
              role="region"
              aria-label={heading}
              className={expanded ? 'space-y-3' : 'hidden space-y-3 md:block'}
            >
              {events.map((event) => (
                <React.Fragment key={event.id}>{renderEvent(event)}</React.Fragment>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

/** Cambiar de rango reinicia solo la seleccion del acordeon, no los datos. */
export const AgendaListView: React.FC<AgendaListViewProps> = ({ rangeKey, ...props }) => (
  <AgendaListContent key={rangeKey} {...props} />
)
