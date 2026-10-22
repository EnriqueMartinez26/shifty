import { render, screen } from '@testing-library/react'

import { BulkCancelResultNotice } from './BulkCancelResultNotice'

describe('BulkCancelResultNotice', () => {
  it('dice cuantas se cancelaron y por que se salteo cada una', () => {
    render(
      <BulkCancelResultNotice
        cancelledCount={2}
        skipped={[
          { id: 'apt-3', code: 'APPOINTMENT_ALREADY_CANCELLED' },
          { id: 'apt-4', code: 'APPOINTMENT_ALREADY_STARTED' },
          { id: 'apt-5', code: 'APPOINTMENT_NOT_FOUND' },
          { id: 'apt-6', code: 'OTRO' }
        ]}
        labels={{ 'apt-3': 'Lucia', 'apt-4': 'Juan', 'apt-5': 'Marta' }}
      />
    )

    const aviso = screen.getByRole('status')
    expect(aviso).toHaveTextContent('Cancelamos 2 reservas.')
    expect(aviso).toHaveTextContent('4 no se cancelaron:')
    expect(screen.getByText('Lucia: Ya estaba cancelada.')).toBeInTheDocument()
    expect(screen.getByText('Juan: El turno ya empezó.')).toBeInTheDocument()
    expect(screen.getByText('Marta: No la encontramos en esta tienda.')).toBeInTheDocument()
    // Sin nombre conocido no se muestra el id crudo.
    expect(screen.getByText('Una reserva: No se pudo cancelar.')).toBeInTheDocument()
    expect(aviso).not.toHaveTextContent('OTRO')
  })

  it('una sola cancelada y ninguna salteada', () => {
    render(<BulkCancelResultNotice cancelledCount={1} skipped={[]} labels={{}} />)

    expect(screen.getByRole('status')).toHaveTextContent('Cancelamos 1 reserva.')
    expect(screen.queryByText(/no se cancel/)).not.toBeInTheDocument()
  })

  it('ninguna cancelada', () => {
    render(
      <BulkCancelResultNotice
        cancelledCount={0}
        skipped={[{ id: 'apt-1', code: 'APPOINTMENT_ALREADY_CANCELLED' }]}
        labels={{ 'apt-1': 'Lucia' }}
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent('No se canceló ninguna reserva.')
    expect(screen.getByRole('status')).toHaveTextContent('1 no se canceló:')
  })
})
