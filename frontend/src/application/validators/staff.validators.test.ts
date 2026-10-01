import { createStaffSchema } from './staff.validators'

// Cobertura de F9-08 (2026-09-30): el schema solo se veia de costado en
// StaffService.test.ts (que se llame a parse). Tests solo de cobertura, verdes
// desde el principio: describen el comportamiento actual.

const issuesDe = (input: unknown) => {
  const result = createStaffSchema.safeParse(input)
  return result.success ? [] : result.error.issues.map((i) => [i.path.join('.'), i.message])
}

const recurso = { kind: 'resource', display_name: 'Cancha 1', service_ids: ['s1'] }

const persona = {
  kind: 'person',
  first_name: 'Ana',
  last_name: 'Perez',
  email: 'ana@example.com',
  display_name: 'Ana P.',
  service_ids: ['s1']
}

describe('createStaffSchema con un recurso', () => {
  it('pasa sin nombre, apellido ni email', () => {
    expect(issuesDe(recurso)).toEqual([])
  })

  it('exige display_name de al menos 2 caracteres', () => {
    expect(issuesDe({ ...recurso, display_name: 'C' })).toEqual([
      ['display_name', 'Nombre de muestra muy corto']
    ])
  })

  it('exige al menos un servicio', () => {
    expect(issuesDe({ ...recurso, service_ids: [] })).toEqual([
      ['service_ids', 'Debe tener al menos un servicio asignado']
    ])
  })
})

describe('createStaffSchema con una persona', () => {
  it('la persona completa pasa', () => {
    expect(issuesDe(persona)).toEqual([])
  })

  it.each([
    ['nombre de 1 caracter', { first_name: 'A' }, 'first_name', 'Nombre muy corto'],
    ['nombre de espacios', { first_name: '  A  ' }, 'first_name', 'Nombre muy corto'],
    ['apellido de 1 caracter', { last_name: 'P' }, 'last_name', 'Apellido muy corto'],
    ['email invalido', { email: 'ana@' }, 'email', 'Email inválido'],
    ['sin email', { email: undefined }, 'email', 'Email inválido']
  ])('%s falla con su mensaje', (_caso, cambio, campo, mensaje) => {
    expect(issuesDe({ ...persona, ...cambio })).toEqual([[campo, mensaje]])
  })

  it('tambien exige display_name y servicios', () => {
    expect(issuesDe({ ...persona, display_name: '', service_ids: [] })).toEqual([
      ['display_name', 'Nombre de muestra muy corto'],
      ['service_ids', 'Debe tener al menos un servicio asignado']
    ])
  })
})

describe('createStaffSchema sin kind', () => {
  it('el default es person: sin nombre, apellido ni email falla como persona', () => {
    const sinKind = { display_name: 'Cancha 1', service_ids: ['s1'] }

    expect(issuesDe(sinKind)).toEqual([
      ['first_name', 'Nombre muy corto'],
      ['last_name', 'Apellido muy corto'],
      ['email', 'Email inválido']
    ])
  })

  it('la salida parseada trae kind person', () => {
    const sinKind: Record<string, unknown> = { ...persona }
    delete sinKind.kind

    expect(createStaffSchema.parse(sinKind).kind).toBe('person')
  })
})
