import { createServiceSchema, updateServiceSchema } from './service.validators'

// Cobertura de F9-08 (2026-09-30): el schema no tenia test propio.
//
// D-20260930-09 (2026-10-01): el formulario rechaza lo que el backend
// (backend/modules/services/schemas.py) ya rechaza: porcentaje de sena mayor a
// 100, monto de sena menor o igual a 0, precio mayor a 10.000.000, descripcion
// mayor a 1000 y nombre mayor a 255. El color de 6 digitos, la duracion minima
// de 5 y el nombre minimo de 3 se mantienen; el minimo de 2 del backend no se
// adopta.

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
    ['duración de 4 minutos', { duration_minutes: 4 }, 'duration_minutes', 'Mínimo 5 minutos'],
    ['duración de 481 minutos', { duration_minutes: 481 }, 'duration_minutes', 'Máximo 8 horas'],
    ['precio negativo', { price: -1 }, 'price', 'El precio no puede ser negativo'],
    ['color sin numeral', { color: 'abcdef' }, 'color', 'Color inválido'],
    ['imagen que no es URL', { image_url: 'no es una url' }, 'image_url', 'URL inválida'],
    [
      'trailer que no es URL',
      { youtube_trailer_url: 'youtube' },
      'youtube_trailer_url',
      'URL inválida'
    ]
  ])('%s falla con su mensaje', (_caso, cambio, campo, mensaje) => {
    const issues = issuesDe({ ...minimo, ...cambio })

    expect(issues.length).toBeGreaterThan(0)
    expect(issues).toContainEqual([campo, mensaje])
  })

  it.each([
    ['duración de 5 minutos', { duration_minutes: 5 }],
    ['duración de 480 minutos', { duration_minutes: 480 }],
    ['color de 6 digitos', { color: '#AbC123' }],
    ['color vacío', { color: '' }],
    ['URLs vacias', { image_url: '', youtube_trailer_url: '' }],
    [
      'URLs validas',
      { image_url: 'https://x.com/a.png', youtube_trailer_url: 'https://youtu.be/x' }
    ]
  ])('%s pasa', (_caso, cambio) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([])
  })
})

describe('createServiceSchema: topes del backend (D-20260930-09)', () => {
  // D-20260930-09 (2026-10-01): el front aceptaba un nombre de 256, una
  // descripcion de 1001 y un precio de 10.000.001; el backend los rechaza con
  // 422 y el panel recien se enteraba despues del viaje.
  it.each([
    [
      'nombre de 256 caracteres',
      { name: 'a'.repeat(256) },
      'name',
      'El nombre no puede superar los 255 caracteres'
    ],
    [
      'descripción de 1001 caracteres',
      { description: 'a'.repeat(1001) },
      'description',
      'La descripción no puede superar los 1000 caracteres'
    ],
    [
      'precio de 10.000.001',
      { price: 10_000_001 },
      'price',
      'El precio no puede superar 10.000.000'
    ]
  ])('%s falla con su mensaje', (_caso, cambio, campo, mensaje) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([[campo, mensaje]])
  })

  it.each([
    ['nombre de 255 caracteres', { name: 'a'.repeat(255) }],
    ['descripción de 1000 caracteres', { description: 'a'.repeat(1000) }],
    ['descripción vacia', { description: '' }],
    ['precio de 10.000.000', { price: 10_000_000 }]
  ])('%s pasa', (_caso, cambio) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([])
  })

  it('un nombre de 2 caracteres sigue fallando', () => {
    // D-20260930-09: el minimo de 3 se mantiene; el de 2 del backend no se
    // adopta.
    expect(issuesDe({ ...minimo, name: 'Co' })).toEqual([
      ['name', 'El nombre debe tener al menos 3 caracteres']
    ])
  })

  it('un color #abc sigue fallando', () => {
    // D-20260930-09: el color de 6 digitos se mantiene aunque el backend
    // acepte tambien el de 3.
    expect(issuesDe({ ...minimo, color: '#abc' })).toEqual([['color', 'Color inválido']])
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
    ['none con fixed', { deposit_mode: 'none', deposit_type: 'fixed' }],
    ['none con monto 0', { deposit_mode: 'none', deposit_type: 'fixed', deposit_amount: 0 }]
  ])('%s no exige monto', (_caso, cambio) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([])
  })

  it.each([
    [-1, 'El monto de la seña no puede ser negativo'],
    [10_000_001, 'El monto de la seña es demasiado alto']
  ])('un monto de %d falla', (deposit_amount, mensaje) => {
    const input = { ...minimo, deposit_mode: 'required', deposit_type: 'fixed', deposit_amount }

    expect(issuesDe(input)).toEqual([['deposit_amount', mensaje]])
  })

  it.each(['none', 'optional', 'required', 'otro'])('deposit_mode %s', (deposit_mode) => {
    const esperado = ['none', 'optional', 'required'].includes(deposit_mode)
    const input = { ...minimo, deposit_mode, deposit_type: 'full' }

    expect(createServiceSchema.safeParse(input).success).toBe(esperado)
  })

  it.each(['required', 'optional', 'none'])(
    'un porcentaje de 150 con seña %s falla (D-20260930-09)',
    (deposit_mode) => {
      // D-20260930-09 (2026-10-01): el front lo aceptaba y el backend lo
      // rechaza con cualquier modo ("un porcentaje de sena no puede superar
      // 100"), igual que la base (ck_services_deposit_percent_max).
      const input = { ...minimo, deposit_mode, deposit_type: 'percent', deposit_amount: 150 }

      expect(issuesDe(input)).toEqual([
        ['deposit_amount', 'El porcentaje de la seña no puede superar 100']
      ])
    }
  )

  it('un porcentaje de 100 pasa', () => {
    const input = {
      ...minimo,
      deposit_mode: 'required',
      deposit_type: 'percent',
      deposit_amount: 100
    }

    expect(issuesDe(input)).toEqual([])
  })

  it.each([
    ['required', 'fixed'],
    ['optional', 'fixed'],
    ['required', 'percent'],
    ['optional', 'percent']
  ])('una seña %s de tipo %s con monto 0 falla (D-20260930-09)', (deposit_mode, deposit_type) => {
    // D-20260930-09 (2026-10-01): el front aceptaba una sena de 0 y el backend
    // la rechaza ("una sena necesita un monto mayor a 0"): el turno se
    // reservaba sin cobrar.
    const input = { ...minimo, deposit_mode, deposit_type, deposit_amount: 0 }

    expect(issuesDe(input)).toEqual([
      ['deposit_amount', 'El monto de la seña tiene que ser mayor a 0']
    ])
  })
})

describe('updateServiceSchema: el PATCH con los mismos topes (D-20260930-09)', () => {
  // D-20260930-09 (2026-10-01): la edicion no validaba nada en el cliente; un
  // porcentaje de 150 o una sena de 0 viajaban y el backend respondia 422.
  // Semantica de PATCH: lo ausente no se valida y null borra donde el
  // backend lo deja (B6-04).
  const issuesDelPatch = (input: unknown) => {
    const result = updateServiceSchema.safeParse(input)
    return result.success ? [] : result.error.issues.map((i) => [i.path.join('.'), i.message])
  }

  it.each([
    ['un PATCH vacío', {}],
    ['solo reactivar', { is_active: true }],
    ['solo el nombre', { name: 'Corte nuevo' }],
    [
      'null en los campos que se pueden borrar',
      { description: null, color: null, youtube_trailer_url: null, deposit_amount: null }
    ],
    ['una imagen subida (URL relativa de medios)', { image_url: '/api/stores/media/abc' }],
    ['un monto sin tipo ni modo (lo valida el backend contra la fila)', { deposit_amount: 500 }],
    [
      'el formulario entero válido',
      {
        name: 'Corte premium',
        description: '',
        duration_minutes: 45,
        price: 12000,
        color: '#3b82f6',
        image_url: '',
        youtube_trailer_url: '',
        deposit_mode: 'required',
        deposit_type: 'percent',
        deposit_amount: 50
      }
    ]
  ])('%s pasa', (_caso, input) => {
    expect(issuesDelPatch(input)).toEqual([])
  })

  it.each([
    [
      'nombre de 256',
      { name: 'a'.repeat(256) },
      'name',
      'El nombre no puede superar los 255 caracteres'
    ],
    ['nombre de 2', { name: 'Co' }, 'name', 'El nombre debe tener al menos 3 caracteres'],
    [
      'descripción de 1001',
      { description: 'a'.repeat(1001) },
      'description',
      'La descripción no puede superar los 1000 caracteres'
    ],
    [
      'precio de 10.000.001',
      { price: 10_000_001 },
      'price',
      'El precio no puede superar 10.000.000'
    ],
    ['color #abc', { color: '#abc' }, 'color', 'Color inválido'],
    [
      'porcentaje de 150',
      { deposit_type: 'percent', deposit_amount: 150 },
      'deposit_amount',
      'El porcentaje de la seña no puede superar 100'
    ],
    [
      'seña required fija de 0',
      { deposit_mode: 'required', deposit_type: 'fixed', deposit_amount: 0 },
      'deposit_amount',
      'El monto de la seña tiene que ser mayor a 0'
    ],
    [
      'seña optional en porcentaje que borra el monto',
      { deposit_mode: 'optional', deposit_type: 'percent', deposit_amount: null },
      'deposit_amount',
      'Indicá el porcentaje de la seña'
    ]
  ])('%s falla con su mensaje', (_caso, input, campo, mensaje) => {
    expect(issuesDelPatch(input)).toEqual([[campo, mensaje]])
  })

  it.each(['name', 'duration_minutes', 'price', 'deposit_mode', 'deposit_type'])(
    'null en %s (columna NOT NULL) falla',
    (campo) => {
      // B6-04: el backend responde 422 ("no puede ser null").
      expect(updateServiceSchema.safeParse({ [campo]: null }).success).toBe(false)
    }
  )
})
