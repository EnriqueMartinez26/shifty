import React from 'react'

import { ShieldBan } from 'lucide-react'

import type { BlockTemplate } from '@application/services/AppointmentBlocksService'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { MAX_BLOCK_OCCURRENCES, type BlockRecurrence } from '../../lib/blockRecurrence'
import { create2000sPanelStyle } from '../../lib/surfaceStyles'

export interface BlockFormState {
  /** '' = el primer profesional de la lista (se resuelve en el render). */
  staff_id: string
  /**
   * null = el bloqueo nuevo sigue al dia que muestra el calendario. Una fecha
   * la fija quien edita un bloqueo o la tipea (F11c-05).
   */
  date: string | null
  starts_at: string
  ends_at: string
  reason: string
  recurrence: BlockRecurrence
  /**
   * Fecha de fin de la serie (FF-13, D-20260929-10). null = el dia del
   * bloqueo + 7, asi sigue al dia elegido igual que `date`.
   */
  recurrence_until: string | null
}

interface StaffOption {
  id: string
  displayName: string
}

interface BlockFormProps {
  form: BlockFormState
  blockDate: string
  recurrenceUntil: string
  staffId: string
  staffMembers: readonly StaffOption[] | undefined
  templates: readonly BlockTemplate[] | undefined
  isEditing: boolean
  occurrences: number
  canSave: boolean
  onChange: (patch: Partial<BlockFormState>) => void
  onSave: () => void
  onReset: () => void
}

const panelStyle = create2000sPanelStyle()

const fieldStyle = {
  background: 'white',
  border: `1px solid ${colors2000s.border.light}`,
  boxShadow: colors2000s.shadows.insetDark,
  color: colors2000s.text.primary
}

const fieldClass = 'rounded-[6px] px-4 py-3 font-bold outline-none disabled:opacity-60'

const occurrencesText = (occurrences: number): { text: string; isError: boolean } => {
  if (occurrences === 0) {
    return { text: 'La fecha de fin no puede ser anterior al día del bloqueo.', isError: true }
  }
  if (occurrences > MAX_BLOCK_OCCURRENCES) {
    return {
      text: `Se crearían ${occurrences} bloqueos y el máximo es ${MAX_BLOCK_OCCURRENCES}. Acortá la fecha de fin.`,
      isError: true
    }
  }
  return {
    text: occurrences === 1 ? 'Se creará 1 bloqueo' : `Se crearán ${occurrences} bloqueos`,
    isError: false
  }
}

const RecurrenceFields: React.FC<
  Pick<BlockFormProps, 'form' | 'recurrenceUntil' | 'occurrences' | 'onChange'>
> = ({ form, recurrenceUntil, occurrences, onChange }) => {
  const summary = form.recurrence === 'none' ? null : occurrencesText(occurrences)
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <select
          aria-label="Recurrencia"
          value={form.recurrence}
          onChange={(e) => onChange({ recurrence: e.target.value as BlockRecurrence })}
          className={fieldClass}
          style={fieldStyle}
        >
          <option value="none">Sin recurrencia</option>
          <option value="daily">Diaria</option>
          <option value="weekly">Semanal</option>
        </select>
        {form.recurrence !== 'none' && (
          <input
            type="date"
            aria-label="Repetir hasta"
            value={recurrenceUntil}
            onChange={(e) => onChange({ recurrence_until: e.target.value })}
            className={fieldClass}
            style={fieldStyle}
          />
        )}
      </div>
      {summary && (
        <p
          role={summary.isError ? 'alert' : 'status'}
          className={`text-xs font-bold ${summary.isError ? 'text-red-700' : 'text-gray-600'}`}
        >
          {summary.text}
        </p>
      )}
    </div>
  )
}

const BlockTimeFields: React.FC<Pick<BlockFormProps, 'form' | 'blockDate' | 'onChange'>> = ({
  form,
  blockDate,
  onChange
}) => (
  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
    <input
      type="date"
      aria-label="Fecha"
      value={blockDate}
      onChange={(e) => onChange({ date: e.target.value })}
      className={fieldClass}
      style={fieldStyle}
    />
    <input
      type="time"
      aria-label="Desde"
      value={form.starts_at}
      onChange={(e) => onChange({ starts_at: e.target.value })}
      className={fieldClass}
      style={fieldStyle}
    />
    <input
      type="time"
      aria-label="Hasta"
      value={form.ends_at}
      onChange={(e) => onChange({ ends_at: e.target.value })}
      className={fieldClass}
      style={fieldStyle}
    />
  </div>
)

const BlockIdentityFields: React.FC<
  Pick<BlockFormProps, 'form' | 'staffId' | 'staffMembers' | 'templates' | 'isEditing' | 'onChange'>
> = ({ form, staffId, staffMembers, templates, isEditing, onChange }) => (
  <>
    <div className="flex flex-wrap gap-2">
      {templates?.map((template) => (
        <button
          key={template.key}
          type="button"
          onClick={() => onChange({ reason: template.reason })}
          className="px-3 py-2 text-[10px] font-black uppercase tracking-widest"
          style={buttonStyles2000s.default}
        >
          {template.label}
        </button>
      ))}
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Editar no cambia el profesional (D-20260929-11): el PATCH no lo acepta. */}
      <select
        aria-label="Profesional"
        value={staffId}
        disabled={isEditing}
        onChange={(e) => onChange({ staff_id: e.target.value })}
        className={fieldClass}
        style={fieldStyle}
      >
        {staffMembers?.map((staff) => (
          <option key={staff.id} value={staff.id}>
            {staff.displayName}
          </option>
        ))}
      </select>
      <input
        aria-label="Motivo interno"
        value={form.reason}
        onChange={(e) => onChange({ reason: e.target.value })}
        className={fieldClass}
        style={fieldStyle}
        placeholder="Motivo interno"
      />
    </div>
  </>
)

/**
 * Formulario de bloqueos, sin estado propio (F4-08): antes vivia en
 * CalendarContainer y cada tecla re-renderizaba la agenda entera.
 */
export const BlockForm: React.FC<BlockFormProps> = (props) => {
  const { form, isEditing, canSave, onChange } = props
  return (
    <div className="p-6 rounded-[8px] space-y-4" style={panelStyle}>
      <div className="flex items-center gap-3">
        <ShieldBan className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
        <h3
          className="text-lg font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Bloqueos de agenda
        </h3>
      </div>

      <BlockIdentityFields {...props} />

      <BlockTimeFields form={form} blockDate={props.blockDate} onChange={onChange} />

      {!isEditing && (
        <RecurrenceFields
          form={form}
          recurrenceUntil={props.recurrenceUntil}
          occurrences={props.occurrences}
          onChange={onChange}
        />
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={props.onSave}
          disabled={!canSave}
          className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
          style={buttonStyles2000s.selected}
        >
          {isEditing ? 'Actualizar bloqueo' : 'Guardar bloqueo'}
        </button>
        <button
          type="button"
          onClick={props.onReset}
          className="px-4 py-3 text-xs font-black uppercase tracking-widest"
          style={buttonStyles2000s.default}
        >
          Limpiar
        </button>
      </div>
    </div>
  )
}
