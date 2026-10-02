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
  readOnlyReason = null
}) => (
  <div
    className="flex flex-col md:flex-row items-center justify-between gap-6 p-4 sm:p-6 rounded-[8px]"
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
          Vistas día, semana, mes y lista
        </p>
      </div>
    </div>

    <div
      className="flex flex-wrap items-center justify-center gap-2 sm:gap-3 p-2 rounded-[6px] border"
      style={fieldStyle}
    >
      <button
        type="button"
        onClick={onPrev}
        className="w-10 h-10 flex items-center justify-center transition-all active:scale-90"
        style={buttonStyles2000s.default}
      >
        <ChevronLeft size={20} className="text-gray-600" />
      </button>
      <div className="px-4 sm:px-6 text-center min-w-[140px] sm:min-w-[200px]">
        <p
          className="text-[9px] font-black uppercase tracking-widest mb-0.5"
          style={{ color: colors2000s.orange.accent }}
        >
          {VIEW_LABELS[view]}
        </p>
        <p
          className="text-base font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          {formatArgentinaLongDate(format(selectedDate, 'yyyy-MM-dd'))}
        </p>
      </div>
      <button
        type="button"
        onClick={onNext}
        className="w-10 h-10 flex items-center justify-center transition-all active:scale-90"
        style={buttonStyles2000s.default}
      >
        <ChevronRight size={20} className="text-gray-600" />
      </button>
    </div>

    <div className="flex flex-wrap items-center gap-2">
      {(Object.keys(VIEW_LABELS) as CalendarView[]).map((viewKey) => (
        <button
          key={viewKey}
          type="button"
          onClick={() => onViewChange(viewKey)}
          className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
          style={view === viewKey ? buttonStyles2000s.selected : buttonStyles2000s.default}
        >
          {VIEW_LABELS[viewKey]}
        </button>
      ))}
      <button
        type="button"
        onClick={onNewAppointment}
        disabled={readOnlyReason !== null}
        title={readOnlyReason ?? undefined}
        className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs disabled:opacity-50"
        style={buttonStyles2000s.selected}
      >
        <Plus size={18} /> Nuevo turno
      </button>
    </div>
  </div>
)
