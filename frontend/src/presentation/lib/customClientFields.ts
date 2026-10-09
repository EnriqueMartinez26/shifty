/**
 * Campos extra del booking: helpers puros del editor de Configuracion
 * (F11b-08). Las opciones de un campo "Lista" se editan como texto, una por
 * linea, con la forma `Etiqueta|valor`; sin `|` la etiqueta es el valor.
 */

import type {
  StoreCustomField,
  StoreCustomFieldOption
} from '@application/services/StoreSettingsService'

export const createEmptyCustomField = (index: number): StoreCustomField => ({
  key: `campo_${index}`,
  label: '',
  type: 'text',
  required: false,
  placeholder: '',
  help_text: '',
  options: []
})

export const serializeFieldOptions = (options: StoreCustomFieldOption[]) =>
  options
    .map((option) =>
      option.label === option.value ? option.value : `${option.label}|${option.value}`
    )
    .join('\n')

export const parseFieldOptions = (rawValue: string): StoreCustomFieldOption[] =>
  rawValue
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [labelPart, valuePart] = line.split('|')
      const label = (labelPart || '').trim()
      const value = (valuePart || labelPart || '').trim()
      return { label, value }
    })
