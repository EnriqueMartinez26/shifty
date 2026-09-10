import { render, screen } from '@testing-library/react'

import { Staff } from '@domain/entities/Staff'

import { StaffCard } from './StaffCard'

describe('StaffCard', () => {
  it('muestra el email de una persona', () => {
    const persona = Staff.fromPrimitives({
      public_id: 'st-1',
      kind: 'person',
      first_name: 'Ana',
      last_name: 'Perez',
      email: 'ana@example.com',
      display_name: 'Ana P.',
      is_active: true,
      service_ids: ['s1']
    })

    render(<StaffCard staff={persona} onEdit={jest.fn()} onDelete={jest.fn()} />)

    expect(screen.getByText('ana@example.com')).toBeInTheDocument()
    expect(screen.getByText('Ana Perez')).toBeInTheDocument()
  })

  it('un recurso sin email no rompe la pagina de personal', () => {
    // Regresion Fase 2 (2026-09-10): Email.create('') tiraba una excepcion y
    // se caia la pagina entera cuando el backend devolvia un staff sin email.
    const cancha = Staff.fromPrimitives({
      public_id: 'cancha-1',
      kind: 'resource',
      first_name: '',
      last_name: '',
      email: null,
      display_name: 'Cancha 1',
      is_active: true,
      service_ids: ['s1']
    })

    render(<StaffCard staff={cancha} onEdit={jest.fn()} onDelete={jest.fn()} />)

    expect(screen.getByText('Cancha 1')).toBeInTheDocument()
    expect(screen.getByText('Recurso')).toBeInTheDocument()
    expect(screen.getByText('Cancha, sala o box: sin usuario')).toBeInTheDocument()
  })
})
