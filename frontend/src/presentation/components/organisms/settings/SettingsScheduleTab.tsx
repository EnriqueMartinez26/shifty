import React from 'react'

import { Trash2 } from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import type { BusinessHoursPeriod } from '../../../lib/settingsDraft'
import { DAYS, isValidPeriod } from '../../../lib/settingsValidation'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'

interface SettingsScheduleTabProps {
  businessHours: Record<string, BusinessHoursPeriod[]>
  onChange: (businessHours: Record<string, BusinessHoursPeriod[]>) => void
}

/**
 * Pestana "Horarios" de Configuracion (F11b-08). Solo pinta: el borrador y el
 * guardado viven en la pagina.
 */
export const SettingsScheduleTab: React.FC<SettingsScheduleTabProps> = ({
  businessHours,
  onChange
}) => (
  <div className="space-y-6">
    <h3
      className="text-lg font-black uppercase tracking-tight"
      style={{ color: colors2000s.orange.accent }}
    >
      Horarios de Atención
    </h3>
    <div className="space-y-3">
      {DAYS.map((day) => (
        // La fila se identifica por el dia, nunca por las horas: con
        // las horas en la key cada tecla remontaba el input y se
        // perdia el foco (FF-08).
        <BusinessHoursDayRow
          key={day.id}
          label={day.label}
          periods={businessHours[day.id] ?? []}
          onChange={(periods) => onChange({ ...businessHours, [day.id]: periods })}
        />
      ))}
    </div>
  </div>
)

const TIME_INPUT_CLASS = 'rounded-lg px-2 py-1 text-[11px] font-black uppercase outline-none'

/**
 * Un dia de la semana: cerrado o UN periodo. El backend guarda un solo periodo
 * por dia y rechaza el resto con 422 (`reject_extra_periods` en
 * `backend/modules/stores/schemas.py`); el horario partido es decision de
 * producto pendiente, asi que no hay "+ Bloque".
 */
const BusinessHoursDayRow: React.FC<{
  label: string
  periods: BusinessHoursPeriod[]
  onChange: (periods: BusinessHoursPeriod[]) => void
}> = ({ label, periods, onChange }) => {
  // Un periodo solo se edita cuando es el unico: con varios (dia legado) no
  // se trunca nada en silencio, el admin elige cual conservar.
  const period = periods.length === 1 ? periods[0] : undefined
  return (
    <div
      className="flex flex-col md:flex-row md:items-center gap-4 p-4 rounded-md transition-all"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.light}`,
        boxShadow: colors2000s.shadows.outer
      }}
    >
      <div
        className="w-24 font-black uppercase tracking-widest text-[10px]"
        style={{ color: colors2000s.text.primary }}
      >
        {label}
      </div>
      {period ? (
        <div className="flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="time"
              aria-label={`Apertura ${label}`}
              value={period.open}
              onChange={(e) => onChange([{ ...period, open: e.target.value }])}
              className={TIME_INPUT_CLASS}
              style={createSettingsInputStyle()}
            />
            <span className="text-[10px] font-bold" style={{ color: colors2000s.text.disabled }}>
              A
            </span>
            <input
              type="time"
              aria-label={`Cierre ${label}`}
              value={period.close}
              onChange={(e) => onChange([{ ...period, close: e.target.value }])}
              className={TIME_INPUT_CLASS}
              style={createSettingsInputStyle()}
            />
            <button
              type="button"
              aria-label={`Cerrar ${label}`}
              onClick={() => onChange([])}
              className="p-1.5 transition-all"
              style={{ color: colors2000s.status.danger.light }}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
          {!isValidPeriod(period) && (
            <p className="text-[10px] font-bold" style={{ color: colors2000s.status.danger.text }}>
              La apertura tiene que ser antes del cierre.
            </p>
          )}
        </div>
      ) : periods.length > 1 ? (
        <div className="flex-1 space-y-1">
          <p className="text-[10px] font-bold" style={{ color: colors2000s.status.danger.text }}>
            Hay {periods.length} horarios guardados; por ahora se admite uno. Elegí cuál conservar.
          </p>
          {periods.map((p) => (
            <div key={`${p.open}-${p.close}`} className="flex items-center gap-2 text-[11px]">
              <span className="font-black">
                {p.open} A {p.close}
              </span>
              <button
                type="button"
                aria-label={`Conservar ${p.open} a ${p.close} el ${label}`}
                onClick={() => onChange([p])}
                className="px-2 py-1 text-[9px] font-black uppercase"
                style={buttonStyles2000s.default}
              >
                Conservar este
              </button>
            </div>
          ))}
        </div>
      ) : (
        <>
          <span
            className="flex-1 text-[10px] font-black uppercase italic"
            style={{ color: colors2000s.text.disabled }}
          >
            Cerrado
          </span>
          <button
            type="button"
            aria-label={`Abrir ${label}`}
            onClick={() => onChange([{ open: '09:00', close: '18:00' }])}
            className="px-3 py-2 text-[9px] font-black uppercase tracking-widest transition-all active:scale-95"
            style={buttonStyles2000s.default}
          >
            Abrir
          </button>
        </>
      )}
    </div>
  )
}
