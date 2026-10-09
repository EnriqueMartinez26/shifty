import {
  createEmptyCustomField,
  parseFieldOptions,
  serializeFieldOptions
} from './customClientFields'

// 2026-10-02: helpers de los campos extra, sacados de Settings.tsx (F11b-08).

describe('customClientFields', () => {
  it('createEmptyCustomField arma campo_N vacio, de texto y opcional', () => {
    expect(createEmptyCustomField(3)).toEqual({
      key: 'campo_3',
      label: '',
      type: 'text',
      required: false,
      placeholder: '',
      help_text: '',
      options: []
    })
  })

  it('parseFieldOptions lee Etiqueta|valor, recorta y saltea lineas vacias', () => {
    expect(parseFieldOptions('Primera vez|primera_vez\r\n  Control  \n\n|solo_valor')).toEqual([
      { label: 'Primera vez', value: 'primera_vez' },
      { label: 'Control', value: 'Control' },
      { label: '', value: 'solo_valor' }
    ])
  })

  it('serializeFieldOptions omite el valor cuando es igual a la etiqueta', () => {
    expect(
      serializeFieldOptions([
        { label: 'Primera vez', value: 'primera_vez' },
        { label: 'Control', value: 'Control' }
      ])
    ).toBe('Primera vez|primera_vez\nControl')
  })

  it('serializar y volver a leer conserva las opciones', () => {
    const options = [
      { label: 'Corte', value: 'corte' },
      { label: 'Color', value: 'Color' }
    ]

    expect(parseFieldOptions(serializeFieldOptions(options))).toEqual(options)
  })
})
