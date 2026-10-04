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

/**
 * Grilla de dias de las vistas semana y mes (F11c-08). Solo pinta; cada
 * evento lo arma `renderEvent`, que decide el contenedor.
 */
export const AgendaRangeGrid: React.FC<AgendaRangeGridProps> = ({
  days,
  eventsByDay,
  compact,
  renderEvent
}) => (
  <div className={compact ? 'overflow-x-auto' : undefined}>
    <div
      className={`grid ${compact ? 'grid-cols-7 min-w-[900px]' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-4'} gap-4`}
    >
      {days.map((day) => {
        const dayKey = format(day, 'yyyy-MM-dd')
        const dayEvents = eventsByDay.get(dayKey) ?? NO_EVENTS
        return (
          <div key={day.toISOString()} className="rounded-[6px] p-4 bg-white" style={cardStyle}>
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
            <div className="space-y-2 max-h-64 overflow-auto">
              {dayEvents
                .slice(0, compact ? 4 : dayEvents.length)
                .map((event) => renderEvent(event, compact))}
              {compact && dayEvents.length > 4 && (
                <div
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  +{dayEvents.length - 4} eventos
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
