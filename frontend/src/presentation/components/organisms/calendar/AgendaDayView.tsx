import React from 'react'

import { Clock, Loader2 } from 'lucide-react'

import { colors2000s, orangeCtaGradient } from '../../../../theme/colors'
import type { UnifiedCalendarEvent } from '../../../lib/calendarEvents'
import { SLOT_HEIGHT_PX, type DayGrid, type TimeRange } from '../../../lib/calendarGrid'
import { canvasStyle, panelStyle } from '../../../lib/calendarStyles'
import { offHoursSegments } from '../../../lib/staffHours'
import { StaffColumn } from '../StaffColumn'

type StaffColumnProps = React.ComponentProps<typeof StaffColumn>

/** Turno de la vista dia, ya ubicado en la grilla por el contenedor. */
type AgendaDayCard = UnifiedCalendarEvent & { top: string; height: string; timeLabel: string }

interface AgendaDayViewProps {
  staffMembers: readonly { id: string; displayName: string }[] | undefined
  loading: boolean
  dayGrid: DayGrid
  /** Franjas de cada profesional el dia elegido; `null` = todavia no se sabe. */
  hoursOfDay: { byStaff: ReadonlyMap<string, readonly TimeRange[] | null> }
  blocks: StaffColumnProps['blocks']
  cards: readonly AgendaDayCard[]
  canManageBlocks: boolean
  onToggleGap: (key: string) => void
  onEditBlock: StaffColumnProps['onEditBlock']
  /** Acciones y WhatsApp de un turno, armados por el contenedor. */
  renderControls: (card: AgendaDayCard) => React.ReactNode
}

/**
 * Vista dia de la agenda (F11c-08): encabezado por profesional, columna de
 * horas con los huecos cerrados y una StaffColumn por profesional. Solo
 * pinta; lo que hace cada click lo decide `CalendarContainer`.
 *
 * En telefonos `CalendarContainer` usa la lista movil (hasta 767 px); esta
 * grilla se reserva para tablet y escritorio, donde se ven todos los profesionales.
 */
export const AgendaDayView: React.FC<AgendaDayViewProps> = ({
  staffMembers,
  loading,
  dayGrid,
  hoursOfDay,
  blocks,
  cards,
  canManageBlocks,
  onToggleGap,
  onEditBlock,
  renderControls
}) => (
  <AgendaDayGrid
    staffMembers={staffMembers}
    loading={loading}
    dayGrid={dayGrid}
    hoursOfDay={hoursOfDay}
    blocks={blocks}
    cards={cards}
    canManageBlocks={canManageBlocks}
    onToggleGap={onToggleGap}
    onEditBlock={onEditBlock}
    renderControls={renderControls}
  />
)

const AgendaDayGrid: React.FC<AgendaDayViewProps> = ({
  staffMembers,
  loading,
  dayGrid,
  hoursOfDay,
  blocks,
  cards,
  canManageBlocks,
  onToggleGap,
  onEditBlock,
  renderControls
}) => (
  <div className="rounded-[8px] border overflow-hidden relative" style={canvasStyle}>
    {loading && (
      <div
        role="status"
        aria-live="polite"
        className="absolute inset-0 z-50 bg-white/60 backdrop-blur-[2px] flex flex-col items-center justify-center"
      >
        <Loader2 className="w-12 h-12 animate-spin text-orange-500 mb-4" aria-hidden="true" />
        <p
          className="text-xs font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Cargando profesionales...
        </p>
      </div>
    )}

    <div
      role="region"
      aria-label="Agenda diaria por profesional, desplazable horizontalmente"
      tabIndex={0}
      className="overflow-x-auto overscroll-x-contain"
    >
      <p
        className="hidden px-3 py-2 text-xs font-medium md:block xl:hidden"
        style={{ color: colors2000s.text.secondary }}
      >
        Deslizá horizontalmente para ver todos los profesionales.
      </p>
      {dayGrid.totalHeightPx > 600 && (
        <p
          id="agenda-day-scroll-hint"
          className="px-3 py-2 text-xs font-medium"
          style={{ color: colors2000s.text.secondary }}
        >
          Deslizá verticalmente para recorrer los horarios.
        </p>
      )}
      <div className="md:min-w-[800px]">
        <div className="flex border-b" style={{ borderColor: colors2000s.border.light }}>
          <div
            className="w-20 flex-shrink-0 flex items-center justify-center border-r"
            style={{ borderColor: colors2000s.border.light }}
          >
            <Clock size={16} style={{ color: colors2000s.text.secondary }} />
          </div>
          <div className="flex flex-1" style={panelStyle}>
            {staffMembers?.map((staff, idx) => (
              <div
                key={staff.id}
                className="flex-1 min-w-[150px] p-4 text-center border-r"
                style={{ borderColor: colors2000s.border.light }}
              >
                <div
                  className="w-10 h-10 rounded-full flex items-center justify-center mx-auto mb-2 font-black text-xs shadow-md"
                  style={{
                    background:
                      idx % 2 === 0
                        ? `linear-gradient(180deg, ${colors2000s.status.info.dark} 0%, ${colors2000s.status.info.accent} 100%)`
                        : orangeCtaGradient,
                    color:
                      idx % 2 === 0
                        ? colors2000s.text.onOrange
                        : colors2000s.text.onOrangeSelection,
                    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
                  }}
                >
                  {staff.displayName
                    .split(' ')
                    .map((word) => word[0])
                    .join('')
                    .toUpperCase()}
                </div>
                <p className="text-[10px] font-black uppercase tracking-tight text-gray-800">
                  {staff.displayName}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div
          role="region"
          aria-label="Horarios de la agenda diaria, desplazable verticalmente"
          aria-describedby={dayGrid.totalHeightPx > 600 ? 'agenda-day-scroll-hint' : undefined}
          tabIndex={dayGrid.totalHeightPx > 600 ? 0 : undefined}
          className="h-[600px] overflow-y-auto relative bg-white"
        >
          <div className="flex">
            <div
              className="w-20 flex-shrink-0 bg-white sticky left-0 z-10 border-r"
              style={{ borderColor: colors2000s.border.light }}
            >
              <div className="relative" style={{ height: dayGrid.totalHeightPx }}>
                {dayGrid.bands.map((band) =>
                  band.kind === 'open' ? (
                    band.labels.map((label) => (
                      <div
                        key={label.text}
                        className="absolute inset-x-0 border-b border-gray-50 flex items-start justify-center pt-2"
                        style={{ top: label.topPx, height: SLOT_HEIGHT_PX }}
                      >
                        <span
                          className="text-[10px] font-black"
                          style={{ color: colors2000s.text.secondary }}
                        >
                          {label.text}
                        </span>
                      </div>
                    ))
                  ) : (
                    <button
                      key={band.key}
                      type="button"
                      onClick={() => onToggleGap(band.key)}
                      title={`Cerrado ${band.label}`}
                      aria-expanded={band.expanded}
                      className="absolute inset-x-0 border-y border-dashed flex items-center justify-center gap-1 text-[9px] font-black uppercase tracking-widest"
                      style={{
                        top: band.topPx,
                        height: band.heightPx,
                        background: colors2000s.bg.disabled,
                        borderColor: colors2000s.border.default,
                        color: colors2000s.text.secondary
                      }}
                    >
                      {band.expanded ? '▾' : '▸'} Cerrado
                    </button>
                  )
                )}
              </div>
            </div>

            <div className="flex flex-1">
              {staffMembers?.map((staff) => {
                const working = hoursOfDay.byStaff.get(staff.id) ?? null
                return (
                  <StaffColumn
                    key={staff.id}
                    grid={dayGrid}
                    offHours={working ? offHoursSegments(dayGrid, working) : []}
                    blocks={blocks.filter((block) => block.staff_id === staff.id)}
                    cards={cards
                      .filter((event) => event.staffId === staff.id)
                      .map((event) => ({
                        id: event.id,
                        title: event.title,
                        subtitle:
                          event.type !== 'block' && event.addonsLabel
                            ? `${event.subtitle} + ${event.addonsLabel}`
                            : event.subtitle,
                        status: event.status,
                        top: event.top,
                        height: event.height,
                        timeLabel: event.timeLabel,
                        controls: renderControls(event)
                      }))}
                    canManageBlocks={canManageBlocks}
                    onEditBlock={onEditBlock}
                  />
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
)
