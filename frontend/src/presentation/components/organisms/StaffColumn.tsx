import React from 'react'

import { formatArgentinaTime } from '@shared/utils/argentinaTime'

import { colors2000s } from '../../../theme/colors'
import { statusStyle } from '../../lib/appointmentStatusStyle'
import { bookingStatusLabel } from '../../lib/bookingStatusLabel'
import { SLOT_HEIGHT_PX, gridPlacement, type DayGrid } from '../../lib/calendarGrid'

interface StaffColumnBlock {
  public_id: string
  staff_id: string
  starts_at: string
  ends_at: string
  reason: string
}

interface StaffColumnCard {
  id: string
  title: string
  subtitle: string
  status: string
  top: string
  height: string
  timeLabel: string
  /** Acciones y WhatsApp del turno, ya armados por el contenedor. */
  controls: React.ReactNode
}

interface StaffColumnProps {
  grid: DayGrid
  /** Tramos fuera del horario efectivo del profesional (FF-03), en px. */
  offHours: readonly { topPx: number; heightPx: number }[]
  blocks: readonly StaffColumnBlock[]
  cards: readonly StaffColumnCard[]
  canManageBlocks: boolean
  onEditBlock: (block: StaffColumnBlock) => void
  /** En el telefono se ve un profesional por vez (QA movil 2026-10-08). */
  hiddenOnPhone?: boolean
}

const closedBandStyle = {
  background: colors2000s.bg.disabled,
  borderColor: colors2000s.border.default,
  color: colors2000s.text.secondary
}

/**
 * Columna de un profesional en la vista dia (F4-08): franjas de la grilla,
 * tramos fuera de su horario, bloqueos y turnos. Solo pinta; lo que se
 * muestra y que hace cada click lo decide `CalendarContainer`.
 */
export const StaffColumn: React.FC<StaffColumnProps> = ({
  grid,
  offHours,
  blocks,
  cards,
  canManageBlocks,
  onEditBlock,
  hiddenOnPhone = false
}) => (
  <div
    data-staff-column
    className={`${hiddenOnPhone ? 'hidden md:block' : ''} flex-1 min-w-[150px] relative border-r border-gray-50`}
  >
    {grid.bands.map((band) =>
      band.kind === 'open' ? (
        band.labels.map((label) => (
          <div
            key={label.text}
            className="absolute inset-x-0 border-b border-gray-50/50"
            style={{ top: label.topPx, height: SLOT_HEIGHT_PX }}
          />
        ))
      ) : (
        <div
          key={band.key}
          className="absolute inset-x-0 border-y border-dashed flex items-center justify-center text-[9px] font-black uppercase tracking-widest"
          style={{ ...closedBandStyle, top: band.topPx, height: band.heightPx }}
        >
          {band.label}
        </div>
      )
    )}

    {offHours.map((segment) => (
      <div
        key={`off-${segment.topPx}`}
        data-testid="staff-off-hours"
        className="absolute inset-x-0 flex items-start justify-center pt-1 text-[9px] font-black uppercase tracking-widest"
        style={{
          top: segment.topPx,
          height: segment.heightPx,
          background: colors2000s.bg.disabled,
          color: colors2000s.text.secondary
        }}
      >
        Fuera de horario
      </div>
    ))}

    {blocks.flatMap((block) => {
      const placement = gridPlacement(grid, block.starts_at, block.ends_at)
      if (!placement) return []
      return (
        <button
          key={block.public_id}
          type="button"
          disabled={!canManageBlocks}
          onClick={() => onEditBlock(block)}
          className="absolute left-2 right-2 rounded-[6px] p-3 border border-l-[5px] text-left"
          style={{
            ...placement,
            background: 'linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)',
            borderColor: '#fb923c',
            borderLeftColor: '#c2410c',
            boxShadow: '0 3px 6px rgba(0,0,0,0.05)'
          }}
        >
          <p className="text-[8px] font-black uppercase tracking-widest text-orange-700 mb-1">
            {block.reason}
          </p>
          <p className="text-[10px] font-black text-orange-900">
            {formatArgentinaTime(block.starts_at)} - {formatArgentinaTime(block.ends_at)}
          </p>
        </button>
      )
    })}

    {cards.map((card) => {
      const style = statusStyle(card.status)
      return (
        <div
          key={card.id}
          className="absolute left-2 right-2 rounded-[6px] p-3 border border-l-[5px] transition-all hover:scale-[1.02] active:scale-95 cursor-pointer flex flex-col justify-between gap-1 overflow-y-auto"
          style={{
            top: card.top,
            height: card.height,
            background: style.background,
            borderColor: colors2000s.border.default,
            borderLeftColor: style.accent,
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.8), 0 3px 6px rgba(0,0,0,0.05)'
          }}
        >
          <div className="min-w-0">
            <p
              className="text-[8px] font-black uppercase tracking-widest mb-0.5"
              style={{ color: style.text }}
            >
              {card.subtitle}
            </p>
            <h4
              className="text-[11px] font-black uppercase truncate leading-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {card.title}
            </h4>
            {/* Debajo del nombre, no encima: tapaban el servicio (QA movil 2026-10-08). */}
            <div className="flex flex-wrap items-start gap-1">{card.controls}</div>
          </div>
          <span
            className="self-start px-2 py-0.5 rounded-[4px] text-[8px] font-black tracking-widest uppercase"
            style={{
              background: 'white',
              boxShadow: colors2000s.shadows.insetDark,
              color: style.text
            }}
          >
            {card.timeLabel} - {bookingStatusLabel(card.status)}
          </span>
        </div>
      )
    })}
  </div>
)
