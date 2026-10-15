import { fireEvent, render, screen } from '@testing-library/react'

import { BookingAddonsPicker } from './BookingAddonsPicker'

const addons = [
  { id: 'strass', name: 'Strass', unitPrice: 500, maxQuantity: 10 },
  { id: 'diseno', name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }
]

describe('BookingAddonsPicker', () => {
  it('sin adicionales no pinta nada', () => {
    const { container } = render(
      <BookingAddonsPicker addons={[]} quantities={{}} onChange={jest.fn()} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('muestra cada adicional con su precio por unidad y su cantidad', () => {
    render(<BookingAddonsPicker addons={addons} quantities={{ strass: 6 }} onChange={jest.fn()} />)

    expect(screen.getByRole('heading', { name: 'Adicionales' })).toBeInTheDocument()
    expect(screen.getByText('Strass')).toBeInTheDocument()
    expect(screen.getByText(/c\/u · hasta 10/)).toBeInTheDocument()
    expect(screen.getByLabelText('Cantidad de Strass')).toHaveTextContent('6')
    expect(screen.getByLabelText('Cantidad de Diseño')).toHaveTextContent('0')
  })

  it('el contador suma y resta de a uno', () => {
    const onChange = jest.fn()
    render(<BookingAddonsPicker addons={addons} quantities={{ strass: 6 }} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))
    expect(onChange).toHaveBeenLastCalledWith('strass', 7)

    fireEvent.click(screen.getByRole('button', { name: 'Quitar uno de Strass' }))
    expect(onChange).toHaveBeenLastCalledWith('strass', 5)
  })

  it('no baja de 0 ni pasa del maximo', () => {
    render(<BookingAddonsPicker addons={addons} quantities={{ diseno: 2 }} onChange={jest.fn()} />)

    expect(screen.getByRole('button', { name: 'Quitar uno de Strass' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Agregar uno de Diseño' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Agregar uno de Strass' })).not.toBeDisabled()
  })

  it('deshabilitado no deja cambiar nada', () => {
    render(
      <BookingAddonsPicker
        addons={addons}
        quantities={{ strass: 1 }}
        onChange={jest.fn()}
        disabled
      />
    )

    expect(screen.getByRole('button', { name: 'Agregar uno de Strass' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Quitar uno de Strass' })).toBeDisabled()
  })
})
