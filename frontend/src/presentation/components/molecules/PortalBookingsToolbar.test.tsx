import type { ComponentProps } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { PortalBookingsToolbar } from './PortalBookingsToolbar'

const renderToolbar = (props: Partial<ComponentProps<typeof PortalBookingsToolbar>> = {}) => {
  const onHoursChange = jest.fn()
  const onCancelSelected = jest.fn()
  render(
    <PortalBookingsToolbar
      hours={72}
      onHoursChange={onHoursChange}
      selectedCount={2}
      onCancelSelected={onCancelSelected}
      {...props}
    />
  )
  return { onHoursChange, onCancelSelected }
}

describe('PortalBookingsToolbar', () => {
  it('ofrece 24 h, 72 h y 7 dias y marca la ventana elegida', () => {
    const { onHoursChange } = renderToolbar()

    expect(screen.getByRole('button', { name: 'Últimas 72 h' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: 'Últimas 24 h' })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
    fireEvent.click(screen.getByRole('button', { name: 'Últimos 7 días' }))
    fireEvent.click(screen.getByRole('button', { name: 'Últimas 24 h' }))

    expect(onHoursChange).toHaveBeenNthCalledWith(1, 168)
    expect(onHoursChange).toHaveBeenNthCalledWith(2, 24)
  })

  it('cancelar dice cuantas hay elegidas', () => {
    const { onCancelSelected } = renderToolbar()

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar seleccionadas (2)' }))

    expect(onCancelSelected).toHaveBeenCalledTimes(1)
  })

  it('sin seleccion cancelar queda deshabilitado', () => {
    renderToolbar({ selectedCount: 0 })

    expect(screen.getByRole('button', { name: /Cancelar seleccionadas/ })).toBeDisabled()
  })

  it('con la tienda suspendida cancelar queda deshabilitado con el motivo a la vista', () => {
    const { onCancelSelected } = renderToolbar({ readOnlyReason: 'Tienda suspendida' })

    const boton = screen.getByRole('button', { name: /Cancelar seleccionadas/ })
    expect(boton).toBeDisabled()
    expect(boton).toHaveAttribute('title', 'Tienda suspendida')
    expect(screen.getByText('Tienda suspendida')).toBeInTheDocument()
    fireEvent.click(boton)
    expect(onCancelSelected).not.toHaveBeenCalled()
  })

  it('los botones tienen un area tactil de 44 px', () => {
    renderToolbar()

    for (const boton of screen.getAllByRole('button')) {
      expect(boton).toHaveClass('min-h-11')
    }
  })
})
