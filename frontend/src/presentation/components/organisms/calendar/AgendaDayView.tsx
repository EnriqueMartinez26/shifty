import React, { useState } from 'react'

import { Clock, Loader2 } from 'lucide-react'

import { buttonStyles2000s, colors2000s, orangeCtaGradient } from '../../../../theme/colors'
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
 * En el telefono (debajo de `md`) se ve un profesional por vez, elegido con
 * los botones de arriba: la grilla de 800 px con todos al lado no se podia
 * recorrer en 343 px (QA movil 2026-10-08). Desde `md` se ven todos.
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
}) => {
  const [chosenStaffId, setChosenStaffId] = useState<string | null>(null)
  // Un profesional elegido que ya no esta (otra tienda, baja) vuelve al
  // primero: se deriva en el render.
  const focusedStaffId =
    staffMembers?.find((staff) => staff.id === chosenStaffId)?.id ?? staffMembers?.[0]?.id
  const hiddenOnPhone = (staffId: string) => staffId !== focusedStaffId

  return (
    <div className="space-y-3">
      {staffMembers && staffMembers.length > 1 && (
        <div role="group" aria-label="Profesional" className="md:hidden flex flex-wrap gap-2">
          {staffMembers.map((staff) => (
            <button
              key={staff.id}
              type="button"
              aria-pressed={staff.id === focusedStaffId}
              onClick={() => setChosenStaffId(staff.id)}
              className="min-h-10 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
              style={
                staff.id === focusedStaffId ? buttonStyles2000s.selected : buttonStyles2000s.default
              }
            >
              {staff.displayName}
            </button>
          ))}
        </div>
      )}
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
        hiddenOnPhone={hiddenOnPhone}
      />
    </div>
  )
}

const AgendaDayGrid: React.FC<
  AgendaDayViewProps & { hiddenOnPhone: (staffId: string) => boolean }
> = ({
  staffMembers,
  loading,
  dayGrid,
  hoursOfDay,
  blocks,
  cards,
  canManageBlocks,
  onToggleGap,
  onEditBlock,
  renderControls,
  hiddenOnPhone
}) => (
  <div className="rounded-[8px] border overflow-hidden relative" style={canvasStyle}>
    {loading && (
      <div className="absolute inset-0 z-50 bg-white/60 backdrop-blur-[2px] flex flex-col items-center justify-center">
        <Loader2 className="w-12 h-12 animate-spin text-orange-500 mb-4" />
        <p className="text-xs font-black text-gray-400 uppercase tracking-widest">
          Actualizando agenda...
        </p>
      </div>
    )}

    <div className="overflow-x-auto">
      <div className="md:min-w-[800px]">
        <div className="flex border-b" style={{ borderColor: colors2000s.border.light }}>
          <div
            className="w-20 flex-shrink-0 flex items-center justify-center border-r"
            style={{ borderColor: colors2000s.border.light }}
          >
            <Clock size={16} className="text-gray-400" />
          </div>
          <div className="flex flex-1" style={panelStyle}>
            {staffMembers?.map((staff, idx) => (
              <div
                key={staff.id}
                className={`${hiddenOnPhone(staff.id) ? 'hidden md:block' : ''} flex-1 min-w-[150px] p-4 text-center border-r`}
                style={{ borderColor: colors2000s.border.light }}
              >
                <div
                  className="w-10 h-10 rounded-full text-white flex items-center justify-center mx-auto mb-2 font-black text-xs shadow-md"
                  style={{
                    background:
                      idx % 2 === 0
                        ? 'linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)'
                        : orangeCtaGradient,
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

        <div className="h-[600px] overflow-y-auto relative bg-white">
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
                        <span className="text-[10px] font-black text-gray-400">{label.text}</span>
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
                        subtitle: event.subtitle,
                        status: event.status,
                        top: event.top,
                        height: event.height,
                        timeLabel: event.timeLabel,
                        controls: renderControls(event)
                      }))}
                    canManageBlocks={canManageBlocks}
                    onEditBlock={onEditBlock}
                    hiddenOnPhone={hiddenOnPhone(staff.id)}
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
