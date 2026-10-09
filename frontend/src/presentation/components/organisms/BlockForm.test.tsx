import { render, screen } from '@testing-library/react'

import { BlockForm, type BlockFormState } from './BlockForm'

// QA movil 2026-10-08: Desde y Hasta eran dos horas sin rotulo visible (solo
// aria-label); en el telefono no se sabia cual era cual.
const form: BlockFormState = {
  staff_id: '',
  date: null,
  starts_at: '13:00',
  ends_at: '14:00',
  reason: 'Almuerzo',
  recurrence: 'daily',
  recurrence_until: null
}

describe('BlockForm', () => {
  it.each([
    'Profesional',
    'Motivo interno',
    'Fecha',
    'Desde',
    'Hasta',
    'Recurrencia',
    'Repetir hasta'
  ])('%s tiene un rotulo visible asociado a su campo', (rotulo) => {
    render(
      <BlockForm
        form={form}
        blockDate="2026-10-08"
        recurrenceUntil="2026-10-15"
        staffId="st-1"
        staffMembers={[{ id: 'st-1', displayName: 'Ana' }]}
        templates={[]}
        isEditing={false}
        occurrences={8}
        canSave
        onChange={jest.fn()}
        onSave={jest.fn()}
        onReset={jest.fn()}
      />
    )
    const text = screen.getByText(rotulo, { selector: 'span' })
    const label = text.closest('label')
    expect(label).not.toBeNull()
    expect(screen.getByLabelText(rotulo)).toBe(label?.querySelector('input, select'))
  })
})
