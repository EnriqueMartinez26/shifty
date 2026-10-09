import React from 'react'

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
  const monthIsEmpty =
    compact && days.every((day) => !eventsByDay.get(format(day, 'yyyy-MM-dd'))?.length)
  return (
    <div className={compact ? 'md:overflow-x-auto' : undefined}>
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
              <div className="space-y-2 md:max-h-64 md:overflow-auto">
                {dayEvents.map((event, index) =>
                  compact && index >= MONTH_CELL_EVENTS ? (
                    <div key={`${event.type}-${event.id}`} className="md:hidden">
                      {renderEvent(event, compact)}
                    </div>
                  ) : (
                    renderEvent(event, compact)
                  )
                )}
                {compact && dayEvents.length > MONTH_CELL_EVENTS && (
                  <div
                    className="hidden md:block text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    +{dayEvents.length - MONTH_CELL_EVENTS} eventos
                  </div>
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
            </div>
          )
        })}
      </div>
    </div>
  )
}
