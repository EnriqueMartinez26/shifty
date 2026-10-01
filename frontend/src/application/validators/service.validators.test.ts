import { createServiceSchema } from './service.validators'

// Cobertura de F9-08 (2026-09-30): el schema no tenia test propio. Tests solo
// de cobertura, verdes desde el principio: describen el comportamiento actual.
//
// Deriva con el backend (backend/modules/services/schemas.py), documentada y
// SIN arreglar: pendiente de decision del dueno.
// - El comentario de service.validators.ts (el backend "acepta hasta
//   10.000.000 para cualquier tipo") esta desactualizado:
//   deposit_policy_error rechaza un porcentaje mayor a 100 y, con sena
//   required u optional de tipo percent o fixed, un monto menor o igual a 0.
//   El front acepta los dos.
// - Nombre: el front exige 3 caracteres; ServiceBase, min_length=2.
// - Color: el front exige hex de 6 digitos; el backend (y el value object
//   ServiceColor del dominio) acepta tambien el de 3.
// - Duracion: el front exige 5 minutos; el backend, gt=0.

const minimo = { name: 'Corte', duration_minutes: 30, price: 1000 }

const issuesDe = (input: unknown) => {
  const result = createServiceSchema.safeParse(input)
  return result.success ? [] : result.error.issues.map((i) => [i.path.join('.'), i.message])
}

describe('createServiceSchema', () => {
  it('el minimo valido pasa y nace sin sena', () => {
    expect(createServiceSchema.parse(minimo)).toMatchObject({
      deposit_mode: 'none',
      deposit_type: 'percent'
    })
  })

  it.each([
    ['sin nombre', { name: '' }, 'name', 'El nombre debe tener al menos 3 caracteres'],
    ['duracion de 4 minutos', { duration_minutes: 4 }, 'duration_minutes', 'Minimo 5 minutos'],
    ['duracion de 481 minutos', { duration_minutes: 481 }, 'duration_minutes', 'Maximo 8 horas'],
    ['precio negativo', { price: -1 }, 'price', 'El precio no puede ser negativo'],
    ['color sin numeral', { color: 'abcdef' }, 'color', 'Color invalido'],
    ['imagen que no es URL', { image_url: 'no es una url' }, 'image_url', 'URL invalida'],
    [
      'trailer que no es URL',
      { youtube_trailer_url: 'youtube' },
      'youtube_trailer_url',
      'URL invalida'
    ]
  ])('%s falla con su mensaje', (_caso, cambio, campo, mensaje) => {
    const issues = issuesDe({ ...minimo, ...cambio })

    expect(issues.length).toBeGreaterThan(0)
    expect(issues).toContainEqual([campo, mensaje])
  })

  it.each([
    ['duracion de 5 minutos', { duration_minutes: 5 }],
    ['duracion de 480 minutos', { duration_minutes: 480 }],
    ['color de 6 digitos', { color: '#AbC123' }],
    ['color vacio', { color: '' }],
    ['URLs vacias', { image_url: '', youtube_trailer_url: '' }],
    [
      'URLs validas',
      { image_url: 'https://x.com/a.png', youtube_trailer_url: 'https://youtu.be/x' }
    ]
  ])('%s pasa', (_caso, cambio) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([])
  })
})

describe('createServiceSchema con sena', () => {
  it.each([
    ['required', 'percent', 'Indicá el porcentaje de la seña'],
    ['optional', 'percent', 'Indicá el porcentaje de la seña'],
    ['required', 'fixed', 'Indicá el monto fijo de la seña']
  ])('%s con %s y sin monto pide el monto', (deposit_mode, deposit_type, mensaje) => {
    expect(issuesDe({ ...minimo, deposit_mode, deposit_type })).toEqual([
      ['deposit_amount', mensaje]
    ])
    expect(issuesDe({ ...minimo, deposit_mode, deposit_type, deposit_amount: null })).toEqual([
      ['deposit_amount', mensaje]
    ])
  })

  it.each([
    ['required con full', { deposit_mode: 'required', deposit_type: 'full' }],
    ['none con percent', { deposit_mode: 'none', deposit_type: 'percent' }],
    ['none con fixed', { deposit_mode: 'none', deposit_type: 'fixed' }]
  ])('%s no exige monto', (_caso, cambio) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([])
  })

  it.each([
    [-1, 'El monto de la sena no puede ser negativo'],
    [10_000_001, 'El monto de la sena es demasiado alto']
  ])('un monto de %d falla', (deposit_amount, mensaje) => {
    const input = { ...minimo, deposit_mode: 'required', deposit_type: 'fixed', deposit_amount }

    expect(issuesDe(input)).toEqual([['deposit_amount', mensaje]])
  })

  it.each(['none', 'optional', 'required', 'otro'])('deposit_mode %s', (deposit_mode) => {
    const esperado = ['none', 'optional', 'required'].includes(deposit_mode)
    const input = { ...minimo, deposit_mode, deposit_type: 'full' }

    expect(createServiceSchema.safeParse(input).success).toBe(esperado)
  })
})

describe('createServiceSchema: deriva con el backend', () => {
  it('un porcentaje de 150 pasa en el front', () => {
    // Deriva con el backend, pendiente de decision del dueno: el backend lo
    // rechaza ("un porcentaje de sena no puede superar 100").
    const input = {
      ...minimo,
      deposit_mode: 'required',
      deposit_type: 'percent',
      deposit_amount: 150
    }

    expect(issuesDe(input)).toEqual([])
  })

  it.each(['required', 'optional'])('una sena %s de monto 0 pasa en el front', (deposit_mode) => {
    // Deriva con el backend, pendiente de decision del dueno: el backend exige
    // un monto mayor a 0 ("una sena necesita un monto mayor a 0").
    const input = { ...minimo, deposit_mode, deposit_type: 'fixed', deposit_amount: 0 }

    expect(issuesDe(input)).toEqual([])
  })

  it('un nombre de 2 caracteres falla en el front', () => {
    // Deriva con el backend, pendiente de decision del dueno: min_length=2.
    expect(issuesDe({ ...minimo, name: 'Co' })).toEqual([
      ['name', 'El nombre debe tener al menos 3 caracteres']
    ])
  })

  it('un color #abc falla en el front', () => {
    // Deriva con el backend, pendiente de decision del dueno: el patron del
    // backend acepta el hex de 3 digitos.
    expect(issuesDe({ ...minimo, color: '#abc' })).toEqual([['color', 'Color invalido']])
  })
})
