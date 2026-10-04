import React from 'react'

import { Plus, Trash2 } from 'lucide-react'

import type { StoreCustomField } from '@application/services/StoreSettingsService'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import {
  createEmptyCustomField,
  parseFieldOptions,
  serializeFieldOptions
} from '../../../lib/customClientFields'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'

const CUSTOM_FIELD_TYPE_OPTIONS = [
  { value: 'text', label: 'Texto corto' },
  { value: 'textarea', label: 'Texto largo' },
  { value: 'tel', label: 'Teléfono' },
  { value: 'email', label: 'Email' },
  { value: 'date', label: 'Fecha' },
  { value: 'select', label: 'Lista' }
] as const

interface CustomClientFieldsEditorProps {
  fields: StoreCustomField[]
  onChange: (fields: StoreCustomField[]) => void
}

/**
 * Campos extra del booking (F11b-08). Solo pinta: devuelve la lista completa
 * con el cambio y la pagina la suma al borrador.
 */
export const CustomClientFieldsEditor: React.FC<CustomClientFieldsEditorProps> = ({
  fields,
  onChange
}) => (
  <div className="space-y-4">
    <div className="flex items-center justify-between gap-4">
      <div>
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Campos extra de la reserva
        </label>
        <p className="text-[11px] font-bold mt-1" style={{ color: colors2000s.text.secondary }}>
          Definí preguntas opcionales o requeridas para el portal público.
        </p>
      </div>
      <button
        type="button"
        onClick={() =>
          onChange([...(fields || []), createEmptyCustomField((fields?.length || 0) + 1)])
        }
        className="px-4 py-2 text-[10px] font-black uppercase tracking-widest transition-all active:scale-95"
        style={buttonStyles2000s.default}
      >
        <Plus className="w-3 h-3 mr-1" />
        Agregar campo
      </button>
    </div>

    {(fields || []).length === 0 ? (
      <div
        className="p-4 rounded-2xl text-xs font-bold"
        style={{
          background: 'white',
          boxShadow: colors2000s.shadows.insetDark,
          color: colors2000s.text.secondary
        }}
      >
        No hay campos extra configurados. La reserva pública va a pedir solo nombre, teléfono, email
        opcional y notas.
      </div>
    ) : (
      <div className="space-y-4">
        {(fields || []).map((field: StoreCustomField, index: number) => (
          <div
            key={`${field.key}-${index}`}
            className="p-5 rounded-md space-y-4"
            style={{
              background: 'white',
              border: `1px solid ${colors2000s.border.light}`,
              boxShadow: colors2000s.shadows.outer
            }}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Campo #{index + 1}
                </p>
                <p className="text-xs font-bold mt-1" style={{ color: colors2000s.text.secondary }}>
                  La clave se usa internamente y conviene mantenerla corta, en minusculas y con
                  guiones bajos.
                </p>
              </div>
              <button
                type="button"
                onClick={() =>
                  onChange(
                    (fields || []).filter(
                      (_: StoreCustomField, fieldIndex: number) => fieldIndex !== index
                    )
                  )
                }
                className="p-2 rounded-xl transition-all active:scale-95"
                style={{ color: colors2000s.status.danger.light }}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Etiqueta
                </label>
                <input
                  value={field.label}
                  onChange={(e) => {
                    const nextFields = [...(fields || [])]
                    nextFields[index] = { ...field, label: e.target.value }
                    onChange(nextFields)
                  }}
                  className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="Ej: Motivo de consulta"
                />
              </div>
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Clave
                </label>
                <input
                  value={field.key}
                  onChange={(e) => {
                    const nextFields = [...(fields || [])]
                    nextFields[index] = {
                      ...field,
                      key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
                    }
                    onChange(nextFields)
                  }}
                  className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="motivo_consulta"
                />
              </div>
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Tipo
                </label>
                <select
                  value={field.type}
                  onChange={(e) => {
                    const nextFields = [...(fields || [])]
                    nextFields[index] = {
                      ...field,
                      type: e.target.value as StoreCustomField['type'],
                      options: e.target.value === 'select' ? field.options : []
                    }
                    onChange(nextFields)
                  }}
                  className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                  style={createSettingsInputStyle()}
                >
                  {CUSTOM_FIELD_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Placeholder
                </label>
                <input
                  value={field.placeholder || ''}
                  onChange={(e) => {
                    const nextFields = [...(fields || [])]
                    nextFields[index] = { ...field, placeholder: e.target.value }
                    onChange(nextFields)
                  }}
                  className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="Texto de ayuda dentro del campo"
                />
              </div>
            </div>

            <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Texto de ayuda
                </label>
                <input
                  value={field.help_text || ''}
                  onChange={(e) => {
                    const nextFields = [...(fields || [])]
                    nextFields[index] = { ...field, help_text: e.target.value }
                    onChange(nextFields)
                  }}
                  className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="Ej: Aclaranos si es primera vez o seguimiento"
                />
              </div>
              <button
                type="button"
                onClick={() => {
                  const nextFields = [...(fields || [])]
                  nextFields[index] = { ...field, required: !field.required }
                  onChange(nextFields)
                }}
                className="mt-7 px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all active:scale-95"
                style={field.required ? buttonStyles2000s.selected : buttonStyles2000s.default}
              >
                {field.required ? 'Obligatorio' : 'Opcional'}
              </button>
            </div>

            {field.type === 'select' && (
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Opciones
                </label>
                <textarea
                  value={serializeFieldOptions(field.options || [])}
                  onChange={(e) => {
                    const nextFields = [...(fields || [])]
                    nextFields[index] = {
                      ...field,
                      options: parseFieldOptions(e.target.value)
                    }
                    onChange(nextFields)
                  }}
                  className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
                  style={createSettingsInputStyle()}
                  placeholder={'Una opción por línea\nEj: Primera vez|primera_vez'}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    )}
  </div>
)
