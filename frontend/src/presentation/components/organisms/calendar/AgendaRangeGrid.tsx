import React, { useEffect, useState } from 'react'

import { format } from 'date-fns'

import { formatArgentinaWeekdayShort } from '@shared/utils/argentinaTime'

import { colors2000s } from '../../../../theme/colors'
import { NO_EVENTS, type UnifiedCalendarEvent } from '../../../lib/calendarEvents'
import { cardStyle } from '../../../lib/calendarStyles'

interface AgendaRangeGridProps {
  days: readonly Date[]
  eventsByDay: ReadonlyMap<string, readonly UnifiedCalendarEvent[]>
  /** Vista mes: siete columnas y hasta 4 eventos por dia. */
  compact: boolean
  renderEvent: (event: UnifiedCalendarEvent, compact: boolean) => React.ReactNode
}

/** Eventos por dia que entran en una celda del mes en pantalla grande. */
const MONTH_CELL_EVENTS = 4
const TABLET_VIEWPORT_QUERY = '(min-width: 768px)'

const isTabletViewport = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia(TABLET_VIEWPORT_QUERY).matches

/**
 * Grilla de dias de las vistas semana y mes (F11c-08). Solo pinta; cada
 * evento lo arma `renderEvent`, que decide el contenedor.
 *
 * En el telefono (debajo de `md`) el mes es una lista de una columna con los
 * dias que tienen eventos, todos sus eventos y sin scroll por dia: la grilla
 * de siete columnas medía 900 px dentro de 343 (QA movil 2026-10-08).
 */
export const AgendaRangeGrid: React.FC<AgendaRangeGridProps> = ({
  days,
  eventsByDay,
  compact,
  renderEvent
}) => {
  const [hasTabletViewport, setHasTabletViewport] = useState(isTabletViewport)
  const [expandedMonthDays, setExpandedMonthDays] = useState<ReadonlySet<string>>(() => new Set())

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(TABLET_VIEWPORT_QUERY)
    const onChange = (event: MediaQueryListEvent) => setHasTabletViewport(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const monthIsEmpty =
    compact && days.every((day) => !eventsByDay.get(format(day, 'yyyy-MM-dd'))?.length)
  const hasHorizontalScrollRegion = compact && hasTabletViewport
  return (
    <div
      className={compact ? 'md:overflow-x-auto' : undefined}
      role={hasHorizontalScrollRegion ? 'region' : undefined}
      aria-label={
        hasHorizontalScrollRegion ? 'Calendario mensual desplazable horizontalmente' : undefined
      }
      tabIndex={hasHorizontalScrollRegion ? 0 : undefined}
    >
      {compact && (
        <p
          className="hidden px-2 pb-2 text-xs font-medium md:block xl:hidden"
          style={{ color: colors2000s.text.secondary }}
        >
          Deslizá horizontalmente para ver todos los días del mes.
        </p>
      )}
      {monthIsEmpty && (
        <p
          className="md:hidden rounded-[6px] p-6 bg-white text-sm font-bold"
          style={{ ...cardStyle, color: colors2000s.text.secondary }}
        >
          No hay eventos este mes.
        </p>
      )}
      <div
        className={`grid ${compact ? 'grid-cols-1 md:grid-cols-7 md:min-w-[900px]' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-4'} gap-4`}
      >
        {days.map((day) => {
          const dayKey = format(day, 'yyyy-MM-dd')
          const dayEvents = eventsByDay.get(dayKey) ?? NO_EVENTS
          const hideOnPhone = compact && dayEvents.length === 0
          const hasMoreMonthEvents = compact && dayEvents.length > MONTH_CELL_EVENTS
          const monthDayExpanded = expandedMonthDays.has(dayKey)
          const scrollableEvents =
            hasTabletViewport &&
            dayEvents.length > MONTH_CELL_EVENTS &&
            (!compact || monthDayExpanded)
          const eventsId = `agenda-events-${dayKey}`
          return (
            <div
              key={day.toISOString()}
              data-day={dayKey}
              className={`${hideOnPhone ? 'hidden md:block' : ''} rounded-[6px] p-4 bg-white`}
              style={cardStyle}
            >
              <div className="mb-3">
                <p
                  className="text-[9px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.orange.accent }}
                >
                  {formatArgentinaWeekdayShort(dayKey)}
                </p>
                <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>
                  {format(day, 'dd/MM')}
                </p>
              </div>
              <div
                id={eventsId}
                role="group"
                aria-label={`Eventos del ${format(day, 'dd/MM')}`}
                aria-describedby={scrollableEvents ? `${eventsId}-scroll-hint` : undefined}
                tabIndex={scrollableEvents ? 0 : undefined}
                className={`space-y-2 ${scrollableEvents ? 'md:max-h-64 md:overflow-y-auto' : ''}`}
              >
                {scrollableEvents && (
                  <p
                    id={`${eventsId}-scroll-hint`}
                    className="hidden text-xs font-medium md:block"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Deslizá verticalmente para recorrer los eventos del día.
                  </p>
                )}
                {dayEvents.map((event, index) =>
                  compact && index >= MONTH_CELL_EVENTS && !monthDayExpanded ? (
                    <div key={`${event.type}-${event.id}`} className="md:hidden">
                      {renderEvent(event, compact)}
                    </div>
                  ) : (
                    renderEvent(event, compact)
                  )
                )}
                {dayEvents.length === 0 && (
                  <div
                    className="text-[10px] font-bold uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Sin eventos
                  </div>
                )}
              </div>
              {hasMoreMonthEvents && (
                <button
                  type="button"
                  aria-controls={eventsId}
                  aria-expanded={monthDayExpanded}
                  aria-label={
                    monthDayExpanded
                      ? `Mostrar menos eventos del ${format(day, 'dd/MM')}`
                      : `Mostrar ${dayEvents.length - MONTH_CELL_EVENTS} eventos más del ${format(day, 'dd/MM')}`
                  }
                  className="hidden min-h-11 min-w-11 items-center rounded px-1 text-left text-[10px] font-black uppercase tracking-widest md:flex"
                  style={{ color: colors2000s.text.secondary }}
                  onClick={() =>
                    setExpandedMonthDays((current) => {
                      const next = new Set(current)
                      if (monthDayExpanded) next.delete(dayKey)
                      else next.add(dayKey)
                      return next
                    })
                  }
                >
                  {monthDayExpanded
                    ? 'Mostrar menos eventos'
                    : `+${dayEvents.length - MONTH_CELL_EVENTS} eventos`}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
