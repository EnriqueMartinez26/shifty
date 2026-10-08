import { fireEvent, render, screen } from '@testing-library/react'

import { Staff } from '@domain/entities/Staff'

import { StaffCard } from './StaffCard'

describe('StaffCard', () => {
  // 2026-10-02, QA en navegador (S\45): los servicios salian como "S-1, S-2".
  it('muestra los servicios por nombre', () => {
    const persona = Staff.fromPrimitives({
      public_id: 'st-1',
      kind: 'person',
      first_name: 'Ana',
      last_name: 'Perez',
      email: 'ana@example.com',
      display_name: 'Ana P.',
      is_active: true,
      service_ids: ['s1', 's2']
    })
    const nombres = new Map([
      ['s1', 'Corte'],
      ['s2', 'Color']
    ])

    render(
      <StaffCard
        staff={persona}
        serviceNames={nombres}
        onEdit={jest.fn()}
        onDelete={jest.fn()}
        onEditSchedule={jest.fn()}
      />
    )

    expect(screen.getByText('Corte')).toBeInTheDocument()
    expect(screen.getByText('Color')).toBeInTheDocument()
    expect(screen.queryByText(/^S-\d/)).not.toBeInTheDocument()
  })

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

    render(
      <StaffCard
        staff={persona}
        onEdit={jest.fn()}
        onDelete={jest.fn()}
        onEditSchedule={jest.fn()}
      />
    )

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

    render(
      <StaffCard
        staff={cancha}
        onEdit={jest.fn()}
        onDelete={jest.fn()}
        onEditSchedule={jest.fn()}
      />
    )

    expect(screen.getByText('Cancha 1')).toBeInTheDocument()
    expect(screen.getByText('Recurso')).toBeInTheDocument()
    expect(screen.getByText('Cancha, sala o box: sin usuario')).toBeInTheDocument()
  })

  // 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
  // verse deshabilitada (FF-15). PUT y DELETE /staff/{id} no estan en
  // SUSPENSION_ALLOWED_WRITES; los servicios se editan desde "Editar".
  it('con la tienda suspendida Editar y Eliminar quedan deshabilitados con el motivo', () => {
    const onEdit = jest.fn()
    const persona = Staff.fromPrimitives({
      public_id: 'st-1',
      kind: 'person',
      first_name: 'Ana',
      last_name: 'Perez',
      email: 'ana@example.com',
      display_name: 'Ana P.',
      is_active: true,
      service_ids: []
    })

    render(
      <StaffCard
        staff={persona}
        onEdit={onEdit}
        onDelete={jest.fn()}
        onEditSchedule={jest.fn()}
        readOnlyReason="Suspendida"
      />
    )

    for (const name of [/editar/i, /eliminar/i]) {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', 'Suspendida')
    }
    fireEvent.click(screen.getByRole('button', { name: /editar/i }))
    expect(onEdit).not.toHaveBeenCalled()
  })
  // 2026-10-08: no habia forma de cargar los dias y horas de cada persona.
  describe('horarios', () => {
    const conFranjas = (
      schedules: { day_of_week: number; start_time: string; end_time: string }[]
    ) =>
      Staff.fromPrimitives({
        public_id: 'st-1',
        kind: 'person',
        first_name: 'Lucas',
        last_name: 'Diaz',
        email: 'lucas@example.com',
        display_name: 'Lucas',
        is_active: true,
        service_ids: [],
        schedules
      })

    it('sin franjas propias dice que usa el horario de la tienda', () => {
      render(
        <StaffCard
          staff={conFranjas([])}
          onEdit={jest.fn()}
          onDelete={jest.fn()}
          onEditSchedule={jest.fn()}
        />
      )

      expect(screen.getByText('Horario de la tienda')).toBeInTheDocument()
    })

    it('con franjas propias lista los dias que atiende', () => {
      render(
        <StaffCard
          staff={conFranjas([
            { day_of_week: 5, start_time: '09:00:00', end_time: '13:00:00' },
            { day_of_week: 1, start_time: '09:00:00', end_time: '13:00:00' },
            { day_of_week: 1, start_time: '14:00:00', end_time: '18:00:00' }
          ])}
          onEdit={jest.fn()}
          onDelete={jest.fn()}
          onEditSchedule={jest.fn()}
        />
      )

      expect(screen.getByText('Mar, Sáb')).toBeInTheDocument()
    })

    it('Horarios abre el editor aun con la tienda suspendida (solo lectura)', () => {
      const onEditSchedule = jest.fn()
      const lucas = conFranjas([])

      render(
        <StaffCard
          staff={lucas}
          onEdit={jest.fn()}
          onDelete={jest.fn()}
          onEditSchedule={onEditSchedule}
          readOnlyReason="Suspendida"
        />
      )
      fireEvent.click(screen.getByRole('button', { name: /horarios/i }))

      expect(onEditSchedule).toHaveBeenCalledWith(lucas)
    })

    // #130 + #133: la tarjeta propia del dueno conserva sus marcas y el editor.
    it('la tarjeta propia muestra (vos), Quitarme y Horarios', () => {
      const onEditSchedule = jest.fn()
      const duenio = conFranjas([])

      render(
        <StaffCard
          staff={duenio}
          isSelf
          onEdit={jest.fn()}
          onDelete={jest.fn()}
          onEditSchedule={onEditSchedule}
        />
      )

      expect(screen.getByText('Lucas Diaz (vos)')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /quitarme/i })).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: /horarios/i }))
      expect(onEditSchedule).toHaveBeenCalledWith(duenio)
    })
  })
})
