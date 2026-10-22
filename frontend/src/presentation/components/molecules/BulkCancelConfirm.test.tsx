import type { ComponentProps } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { BulkCancelConfirm } from './BulkCancelConfirm'

const renderConfirm = (props: Partial<ComponentProps<typeof BulkCancelConfirm>> = {}) => {
  const onReasonChange = jest.fn()
  const onConfirm = jest.fn()
  const onBack = jest.fn()
  render(
    <BulkCancelConfirm
      count={3}
      reason=""
      onReasonChange={onReasonChange}
      onConfirm={onConfirm}
      onBack={onBack}
      isPending={false}
      {...props}
    />
  )
  return { onReasonChange, onConfirm, onBack }
}

describe('BulkCancelConfirm', () => {
  it('dice cuantas se cancelan y que se avisa a quien dejo email', () => {
    renderConfirm()

    expect(screen.getByRole('region', { name: 'Confirmar cancelación' })).toHaveTextContent(
      'Vas a cancelar 3 reservas. A los clientes que dejaron email les va a llegar el aviso de cancelación.'
    )
  })

  it('una sola reserva va en singular', () => {
    renderConfirm({ count: 1 })

    expect(screen.getByText(/Vas a cancelar 1 reserva\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sí, cancelar 1 reserva' })).toBeInTheDocument()
  })

  it('el motivo es opcional y tiene tope de 200 caracteres', () => {
    const { onReasonChange } = renderConfirm({ reason: 'Bot' })

    const motivo = screen.getByLabelText('Motivo (opcional)')
    expect(motivo).toHaveAttribute('maxLength', '200')
    expect(screen.getByText('3/200')).toBeInTheDocument()
    fireEvent.change(motivo, { target: { value: 'Reservas falsas' } })
    expect(onReasonChange).toHaveBeenCalledWith('Reservas falsas')
  })

  it('confirmar y volver avisan al contenedor', () => {
    const { onConfirm, onBack } = renderConfirm()

    fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar 3 reservas' }))
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('mientras cancela no deja confirmar dos veces', () => {
    const { onConfirm } = renderConfirm({ isPending: true })

    const boton = screen.getByRole('button', { name: /Cancelando/ })
    expect(boton).toBeDisabled()
    fireEvent.click(boton)
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
