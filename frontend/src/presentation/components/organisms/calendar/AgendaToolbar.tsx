import React from 'react'

import { format } from 'date-fns'
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, Plus } from 'lucide-react'

import { formatArgentinaLongDate } from '@shared/utils/argentinaTime'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { fieldStyle, panelStyle } from '../../../lib/calendarStyles'

export type CalendarView = 'day' | 'week' | 'month' | 'list'

const VIEW_LABELS: Record<CalendarView, string> = {
  day: 'Día',
  week: 'Semana',
  month: 'Mes',
  list: 'Lista'
}

interface AgendaToolbarProps {
  view: CalendarView
  selectedDate: Date
  onPrev: () => void
  onNext: () => void
  onViewChange: (view: CalendarView) => void
  onNewAppointment: () => void
  /** En teléfono la vista lista es fija; la preferencia de escritorio se conserva. */
  mobileList?: boolean
  /** El listado móvil puede acotarse al día seleccionado si el rango se recorta. */
  mobileSingleDay?: boolean
  onToggleMobileRange?: () => void
  /** Tienda suspendida: POST /appointments/ responde 402 (FF-15). */
  readOnlyReason?: string | null
}

/**
 * Cabecera de la agenda (F11c-08): titulo, navegacion de fechas, vistas y
 * turno nuevo. Solo pinta; el salto de cada flecha lo decide el contenedor.
 */
export const AgendaToolbar: React.FC<AgendaToolbarProps> = ({
  view,
  selectedDate,
  onPrev,
  onNext,
  onViewChange,
  onNewAppointment,
  mobileList = false,
  mobileSingleDay = false,
  onToggleMobileRange,
  readOnlyReason = null
}) => (
  <div
    className="flex flex-col 2xl:flex-row items-stretch 2xl:items-center justify-between gap-4 2xl:gap-6 p-4 sm:p-6 rounded-[8px]"
    style={panelStyle}
  >
    <div className="flex items-center gap-4">
      <div
        className="w-12 h-12 rounded-[6px] text-white flex items-center justify-center flex-shrink-0"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
          boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
        }}
      >
        <CalendarIcon size={24} />
      </div>
      <div>
        <h2
          className="text-2xl font-black uppercase tracking-tight leading-none mb-1"
          style={{ color: colors2000s.text.primary }}
        >
          Agenda
        </h2>
        <p
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          {mobileList ? 'Vista de lista móvil' : 'Vistas día, semana, mes y lista'}
        </p>
      </div>
    </div>

    <div className="flex w-full min-w-0 items-center justify-center gap-2 2xl:w-auto 2xl:gap-4">
      <button
        type="button"
        onClick={onPrev}
        aria-label="Anterior"
        className="min-h-11 min-w-11 flex items-center justify-center transition-all active:scale-90"
        style={buttonStyles2000s.default}
      >
        <ChevronLeft size={20} className="text-gray-600" />
      </button>
      <div className="min-w-0 flex-1 px-1 text-center sm:flex-initial sm:min-w-[200px] sm:px-6">
        <p
          className="text-[9px] font-black uppercase tracking-widest mb-0.5"
          style={{ color: colors2000s.orange.accent }}
        >
          {VIEW_LABELS[view]}
        </p>
        <p
          className="text-sm font-black uppercase tracking-tight sm:text-base"
          style={{ color: colors2000s.text.primary }}
        >
          {formatArgentinaLongDate(format(selectedDate, 'yyyy-MM-dd'))}
        </p>
      </div>
      <button
        type="button"
        onClick={onNext}
        aria-label="Siguiente"
        className="min-h-11 min-w-11 flex items-center justify-center transition-all active:scale-90"
        style={buttonStyles2000s.default}
      >
        <ChevronRight size={20} className="text-gray-600" />
      </button>
    </div>

    <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-2 2xl:w-auto 2xl:justify-end">
      {mobileList ? (
        <div className="flex flex-wrap items-center gap-2">
          <span
            role="status"
            className="px-3 py-2 rounded-md text-xs font-bold"
            style={{ color: colors2000s.text.secondary, background: 'white' }}
          >
            Lista en móvil · {mobileSingleDay ? '1 día' : '14 días'}
          </span>
          {onToggleMobileRange && (
            <button
              type="button"
              onClick={onToggleMobileRange}
              className="min-h-11 px-3 py-2 rounded-md text-xs font-bold"
              style={buttonStyles2000s.default}
            >
              {mobileSingleDay ? 'Ver 14 días' : 'Ver solo este día'}
            </button>
          )}
        </div>
      ) : (
        <div
          role="group"
          aria-label="Vista de agenda"
          className="flex flex-wrap items-center gap-2 sm:gap-3 p-2 rounded-[6px] border"
          style={fieldStyle}
        >
          {(Object.keys(VIEW_LABELS) as CalendarView[]).map((viewKey) => (
            <button
              key={viewKey}
              type="button"
              onClick={() => onViewChange(viewKey)}
              aria-pressed={view === viewKey}
              className="min-h-11 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
              style={view === viewKey ? buttonStyles2000s.selected : buttonStyles2000s.default}
            >
              {VIEW_LABELS[viewKey]}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={onNewAppointment}
        disabled={readOnlyReason !== null}
        title={readOnlyReason ?? undefined}
        className="min-h-11 px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs disabled:opacity-50"
        style={buttonStyles2000s.selected}
      >
        <Plus size={18} /> Nuevo turno
      </button>
    </div>
  </div>
)
