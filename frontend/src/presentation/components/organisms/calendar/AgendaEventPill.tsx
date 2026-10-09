import React from 'react'

import { formatArgentinaTime } from '@shared/utils/argentinaTime'

import { colors2000s } from '../../../../theme/colors'
import { statusStyle } from '../../../lib/appointmentStatusStyle'
import { bookingStatusLabel } from '../../../lib/bookingStatusLabel'
import { toInstantIso, type UnifiedCalendarEvent } from '../../../lib/calendarEvents'

interface AgendaEventPillProps {
  event: UnifiedCalendarEvent
  compact?: boolean
  /** Acciones y WhatsApp del turno, ya armados por el contenedor. */
  actions: React.ReactNode
}

/**
 * Pastilla de un evento en las vistas semana, mes y lista (F11c-08). Solo
 * pinta; que acciones ofrece lo decide `CalendarContainer`.
 */
export const AgendaEventPill: React.FC<AgendaEventPillProps> = ({
  event,
  compact = false,
  actions
}) => {
  const style =
    event.type === 'block'
      ? {
          accent: '#c2410c',
          background: 'linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)',
          text: '#9a3412'
        }
      : statusStyle(event.status)
  return (
    <div
      className={`relative rounded-[6px] border ${compact ? 'p-2' : 'p-3'}`}
      style={{
        background: style.background,
        borderColor: style.accent,
        boxShadow: '0 3px 6px rgba(0,0,0,0.05)'
      }}
    >
      <p
        className={`${compact ? 'text-[8px]' : 'text-[9px]'} font-black uppercase tracking-widest`}
        style={{ color: style.text }}
      >
        {event.type === 'block' ? 'Bloqueo' : bookingStatusLabel(event.status)}
      </p>
      <p
        className={`${compact ? 'text-[11px]' : 'text-xs'} font-black`}
        style={{ color: colors2000s.text.primary }}
      >
        {event.title}
      </p>
      <p className="text-[10px] font-bold" style={{ color: colors2000s.text.secondary }}>
        {formatArgentinaTime(toInstantIso(event.startsAt))} -{' '}
        {formatArgentinaTime(toInstantIso(event.endsAt))} · {event.staffName}
      </p>
      {actions}
    </div>
  )
}
