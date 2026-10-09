import React, { useId, useState } from 'react'

import { Copy, Loader2, Plus, Trash2, X } from 'lucide-react'

import type { StaffSchedule } from '@domain/entities/Staff'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import {
  MAX_RANGES_PER_DAY,
  WEEK_DAYS,
  DEFAULT_RANGE,
  copyDayToAll,
  draftFromSchedules,
  draftFromStoreHours,
  nextRange,
  replaceDay,
  scheduleSaveErrorMessage,
  validateWeek,
  weekToSchedules,
  type ScheduleMode,
  type WeekDraft,
  type WeekRange
} from '../../lib/staffWeekDraft'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'

type BusinessHours = Readonly<Record<string, readonly { open: string; close: string }[]>>

interface StaffScheduleModalProps {
  /** Nombre que se muestra en el titulo. */
  staffName: string
  /** Franjas guardadas; ninguna = usa el horario de la tienda. */
  schedules: readonly StaffSchedule[]
  /** Horario comercial del local (`business_hours`); `undefined` mientras carga. */
  storeBusinessHours: BusinessHours | undefined
  onClose: () => void
  onSave: (schedules: StaffSchedule[]) => Promise<void>
  /** Tienda suspendida (FF-15): `PUT /staff/{id}/schedules` responde 402. */
  readOnlyReason?: string | null
}

const TAP = 'min-h-[44px]'
const TIME_INPUT_CLASS = `${TAP} w-full rounded-xl px-3 text-sm font-bold outline-none disabled:opacity-60`
const SMALL_BUTTON_CLASS = `${TAP} inline-flex items-center justify-center gap-1.5 px-3 text-[10px] font-black uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50`

const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

/**
 * Editor de la semana de trabajo de un profesional. Solo pinta y arma el
 * borrador: guardar lo hace el contenedor (`onSave`).
 *
 * El contenedor lo monta con `key` por profesional, asi que el borrador nace
 * del estado guardado en el `useState` inicial, sin efectos que lo repueblen.
 */
export const StaffScheduleModal: React.FC<StaffScheduleModalProps> = ({
  staffName,
  schedules,
  storeBusinessHours,
  onClose,
  onSave,
  readOnlyReason = null
}) => {
  const [mode, setMode] = useState<ScheduleMode>(schedules.length === 0 ? 'store' : 'own')
  const [draft, setDraft] = useState<WeekDraft>(() => draftFromSchedules(schedules))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validation = validateWeek(mode, draft)
  const blocked = readOnlyReason !== null
  // Ni la tienda suspendida ni un guardado en curso dejan tocar el borrador.
  const locked = blocked || saving
  const titleId = useId()

  const chooseOwn = () => {
    // Sin franjas propias, el punto de partida es el horario de la tienda.
    if (mode === 'store' && draft.every((ranges) => ranges.length === 0)) {
      setDraft(draftFromStoreHours(storeBusinessHours))
    }
    setMode('own')
  }

  const updateDay = (day: number, ranges: readonly WeekRange[]) => {
    setDraft(replaceDay(draft, day, ranges))
  }

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!validation.isValid || blocked) return
    setSaving(true)
    setError(null)
    try {
      await onSave(weekToSchedules(mode, draft))
      onClose()
    } catch (err: unknown) {
      setError(scheduleSaveErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const footerMessage = error ?? (mode === 'own' ? validation.weekError : null)

  return (
    <div className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center sm:p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-2xl rounded-t-md sm:rounded-md shadow-2xl flex flex-col overflow-hidden max-h-[100dvh] sm:max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div
          className="px-4 py-3 sm:px-6 sm:py-4 flex items-center justify-between gap-3"
          style={{ background: colors2000s.bg.disabled }}
        >
          <div className="min-w-0">
            <h3
              id={titleId}
              className="text-lg sm:text-xl font-black uppercase tracking-tight truncate"
              style={{ color: colors2000s.text.primary }}
            >
              Horarios de {staffName}
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Fuera de este horario nadie le puede reservar.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className={`${TAP} min-w-[44px] flex items-center justify-center`}
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form
          noValidate
          onSubmit={(event) => {
            void handleSave(event)
          }}
          className="flex flex-col flex-1 min-h-0"
        >
          <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 space-y-4">
            {blocked && (
              <p
                className="rounded-xl px-3 py-2 text-xs font-bold"
                style={{ background: colors2000s.bg.disabled, color: colors2000s.text.secondary }}
              >
                {readOnlyReason}
              </p>
            )}

            <div
              role="radiogroup"
              aria-label="¿Cuándo atiende?"
              className="grid gap-2 sm:grid-cols-2"
            >
              <ModeOption
                checked={mode === 'store'}
                label="Usa el horario de la tienda"
                hint="Sigue el horario de Configuración: si lo cambiás, cambia también acá."
                disabled={locked}
                onSelect={() => setMode('store')}
              />
              <ModeOption
                checked={mode === 'own'}
                label="Horario propio"
                hint="Días y franjas solo para esta persona. Los demás días no atiende."
                disabled={locked}
                onSelect={chooseOwn}
              />
            </div>

            {mode === 'store' ? (
              <StoreHoursSummary businessHours={storeBusinessHours} />
            ) : (
              <div className="space-y-3">
                {WEEK_DAYS.map((day, index) => (
                  <DayEditor
                    key={day.label}
                    label={day.label}
                    ranges={draft[index] ?? []}
                    error={validation.dayErrors[index] ?? null}
                    disabled={locked}
                    onChange={(ranges) => updateDay(index, ranges)}
                    onCopyToAll={() => setDraft(copyDayToAll(draft, index))}
                  />
                ))}
              </div>
            )}
          </div>

          <div
            className="px-4 py-3 sm:px-6 space-y-2"
            style={{ borderTop: `1px solid ${colors2000s.border.light}` }}
          >
            {footerMessage && (
              <p
                role="alert"
                className="rounded-xl px-3 py-2 text-xs font-bold"
                style={{ background: '#fff1f2', color: '#be123c' }}
              >
                {footerMessage}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onClose}
                className={`${TAP} px-5 font-black uppercase tracking-widest text-xs transition-all active:scale-95`}
                style={buttonStyles2000s.default}
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={saving || blocked || !validation.isValid}
                title={readOnlyReason ?? undefined}
                className={`${TAP} flex-1 font-black rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 disabled:opacity-50`}
                style={buttonStyles2000s.selected}
              >
                {saving ? (
                  <Loader2 className="w-5 h-5 animate-spin mx-auto" aria-label="Guardando" />
                ) : (
                  'Guardar horario'
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

const ModeOption: React.FC<{
  checked: boolean
  label: string
  hint: string
  disabled: boolean
  onSelect: () => void
}> = ({ checked, label, hint, disabled, onSelect }) => (
  <button
    type="button"
    role="radio"
    aria-checked={checked}
    disabled={disabled}
    onClick={onSelect}
    className={`${TAP} rounded-xl border px-3 py-2 text-left disabled:opacity-60`}
    style={{
      borderColor: checked ? colors2000s.orange.accent : colors2000s.border.default,
      background: checked ? colors2000s.orange.accent : colors2000s.bg.button,
      color: checked ? '#ffffff' : colors2000s.text.primary
    }}
  >
    <span className="block text-[11px] font-black uppercase tracking-widest">{label}</span>
    <span className="block text-[11px] font-bold opacity-90">{hint}</span>
  </button>
)

const StoreHoursSummary: React.FC<{ businessHours: BusinessHours | undefined }> = ({
  businessHours
}) => {
  if (!businessHours) {
    return (
      <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
        Cargando el horario de la tienda...
      </p>
    )
  }
  return (
    <ul
      aria-label="Horario de la tienda"
      className="rounded-xl p-3 space-y-1"
      style={{ background: 'white', boxShadow: colors2000s.shadows.insetDark }}
    >
      {WEEK_DAYS.map((day, index) => {
        const periods = businessHours[DAY_KEYS[index] ?? ''] ?? []
        return (
          <li key={day.label} className="flex justify-between gap-3 text-xs font-bold">
            <span style={{ color: colors2000s.text.primary }}>{day.label}</span>
            <span style={{ color: colors2000s.text.secondary }}>
              {periods.length === 0
                ? 'Cerrado'
                : periods.map((p) => `${p.open.slice(0, 5)} a ${p.close.slice(0, 5)}`).join(', ')}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

const DayEditor: React.FC<{
  label: string
  ranges: readonly WeekRange[]
  error: string | null
  disabled: boolean
  onChange: (ranges: readonly WeekRange[]) => void
  onCopyToAll: () => void
}> = ({ label, ranges, error, disabled, onChange, onCopyToAll }) => {
  const open = ranges.length > 0
  const errorId = useId()
  const setRange = (index: number, patch: Partial<WeekRange>) =>
    onChange(ranges.map((range, i) => (i === index ? { ...range, ...patch } : range)))

  return (
    <section
      aria-label={label}
      className="rounded-xl p-3 space-y-2"
      style={{
        background: 'white',
        border: `1px solid ${error ? colors2000s.status.danger.light : colors2000s.border.light}`
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className="font-black uppercase tracking-widest text-[11px]"
          style={{ color: colors2000s.text.primary }}
        >
          {label}
        </span>
        <button
          type="button"
          aria-pressed={open}
          disabled={disabled}
          aria-label={`${label}: ${open ? 'atiende' : 'no atiende'}`}
          onClick={() => onChange(open ? [] : [{ ...DEFAULT_RANGE }])}
          className={`${SMALL_BUTTON_CLASS} rounded-xl min-w-[110px]`}
          style={open ? buttonStyles2000s.selected : buttonStyles2000s.default}
        >
          {open ? 'Atiende' : 'No atiende'}
        </button>
      </div>

      {open && (
        <>
          {ranges.map((range, index) => (
            <div key={index} className="flex items-end gap-2">
              <label className="flex-1 space-y-1">
                <span
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Desde
                </span>
                <input
                  type="time"
                  aria-label={`${label}, franja ${index + 1}: desde`}
                  aria-describedby={error ? errorId : undefined}
                  disabled={disabled}
                  value={range.start}
                  onChange={(event) => setRange(index, { start: event.target.value })}
                  className={TIME_INPUT_CLASS}
                  style={create2000sModalInputStyle()}
                />
              </label>
              <label className="flex-1 space-y-1">
                <span
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Hasta
                </span>
                <input
                  type="time"
                  aria-label={`${label}, franja ${index + 1}: hasta`}
                  aria-describedby={error ? errorId : undefined}
                  disabled={disabled}
                  value={range.end}
                  onChange={(event) => setRange(index, { end: event.target.value })}
                  className={TIME_INPUT_CLASS}
                  style={create2000sModalInputStyle()}
                />
              </label>
              <button
                type="button"
                aria-label={`Quitar franja ${index + 1} del ${label}`}
                disabled={disabled}
                onClick={() => onChange(ranges.filter((_, i) => i !== index))}
                className={`${TAP} min-w-[44px] flex items-center justify-center rounded-xl disabled:opacity-50`}
                style={{ ...buttonStyles2000s.default, color: colors2000s.status.danger.light }}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {error && (
            <p
              id={errorId}
              className="text-[11px] font-bold"
              style={{ color: colors2000s.status.danger.text }}
            >
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onChange([...ranges, nextRange(ranges)])}
              disabled={disabled || ranges.length >= MAX_RANGES_PER_DAY}
              className={`${SMALL_BUTTON_CLASS} rounded-xl`}
              style={buttonStyles2000s.default}
            >
              <Plus size={14} /> Agregar franja
            </button>
            <button
              type="button"
              onClick={onCopyToAll}
              disabled={disabled}
              className={`${SMALL_BUTTON_CLASS} rounded-xl`}
              style={buttonStyles2000s.default}
            >
              <Copy size={14} /> Copiar a todos los días
            </button>
          </div>
        </>
      )}
    </section>
  )
}
