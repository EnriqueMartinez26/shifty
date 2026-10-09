import React from 'react'

import { formatArgentinaDayMonth, formatArgentinaTime } from '@shared/utils/argentinaTime'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { toInstantIso, type UnifiedCalendarEvent } from '../../../lib/calendarEvents'
import { cardStyle, panelStyle } from '../../../lib/calendarStyles'

/** Bloqueo a editar, con la forma que espera el formulario de bloqueos. */
interface AbsencesTimelineBlock {
  public_id: string
  staff_id: string
  starts_at: string
  ends_at: string
  reason: string
}

interface AbsencesTimelineProps {
  events: readonly UnifiedCalendarEvent[]
  canManageBlocks: boolean
  onEdit: (block: AbsencesTimelineBlock) => void
  onDeactivate: (blockId: string) => void
  /** Tienda suspendida: PATCH y DELETE de bloqueos responden 402 (FF-15). */
  readOnlyReason?: string | null
}

/**
 * Panel de bloqueos y ausencias del rango (F11c-08). Solo pinta: editar y
 * desactivar los resuelve el contenedor, que es quien tiene los hooks (D-58).
 */
export const AbsencesTimeline: React.FC<AbsencesTimelineProps> = ({
  events,
  canManageBlocks,
  onEdit,
  onDeactivate,
  readOnlyReason = null
}) => (
  <div className="p-6 rounded-[8px] space-y-4" style={panelStyle}>
    <h3
      className="text-lg font-black uppercase tracking-tight"
      style={{ color: colors2000s.text.primary }}
    >
      Bloqueos y ausencias
    </h3>
    <div className="space-y-3">
      {events.map((event) => (
        <div
          key={`${event.type}-${event.id}`}
          className="rounded-[6px] p-4 bg-white flex flex-col gap-3"
          style={cardStyle}
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                {event.title}
              </p>
              <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
                {formatArgentinaDayMonth(toInstantIso(event.startsAt))}{' '}
                {formatArgentinaTime(toInstantIso(event.startsAt))} -{' '}
                {formatArgentinaTime(toInstantIso(event.endsAt))} · {event.staffName}
              </p>
            </div>
            <span
              className="px-2 py-1 rounded-[4px] text-[10px] font-black uppercase tracking-widest"
              style={{
                background: event.type === 'block' ? '#ffedd5' : '#fee2e2',
                color: event.type === 'block' ? '#c2410c' : '#b91c1c'
              }}
            >
              {event.type === 'block' ? 'Bloqueo' : 'Ausencia'}
            </span>
          </div>
          {event.type === 'block' && canManageBlocks && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() =>
                  onEdit({
                    public_id: event.id,
                    staff_id: event.staffId,
                    starts_at: toInstantIso(event.startsAt),
                    ends_at: toInstantIso(event.endsAt),
                    reason: event.title
                  })
                }
                disabled={readOnlyReason !== null}
                title={readOnlyReason ?? undefined}
                className="px-3 py-2 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                style={buttonStyles2000s.default}
              >
                Editar
              </button>
              <button
                type="button"
                onClick={() => onDeactivate(event.id)}
                disabled={readOnlyReason !== null}
                title={readOnlyReason ?? undefined}
                className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                style={buttonStyles2000s.selected}
              >
                Desactivar
              </button>
            </div>
          )}
        </div>
      ))}
      {!events.length && (
        <div
          className="rounded-[6px] p-6 bg-white text-sm font-bold"
          style={{ ...cardStyle, color: colors2000s.text.secondary }}
        >
          No hay bloqueos ni ausencias en el rango actual.
        </div>
      )}
    </div>
  </div>
)
