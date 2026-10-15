import { fireEvent, render, screen } from '@testing-library/react'

import { ServiceAddonsEditor } from './ServiceAddonsEditor'
import type { ServiceAddonFormValue } from '../../types/forms'

const strass: ServiceAddonFormValue = { key: 'a', name: 'Strass', unitPrice: 500, maxQuantity: 10 }
const diseno: ServiceAddonFormValue = { key: 'b', name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }

describe('ServiceAddonsEditor', () => {
  it('agrega un adicional vacio al final', () => {
    const onChange = jest.fn()
    render(<ServiceAddonsEditor addons={[strass]} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /Agregar adicional/ }))

    expect(onChange).toHaveBeenCalledWith([
      strass,
      { key: expect.any(String), name: '', unitPrice: 0, maxQuantity: 1 }
    ])
  })

  it('edita nombre, precio y maximo del adicional', () => {
    const onChange = jest.fn()
    render(<ServiceAddonsEditor addons={[strass]} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Nombre del adicional 1'), {
      target: { value: 'Strass dorado' }
    })
    expect(onChange).toHaveBeenLastCalledWith([{ ...strass, name: 'Strass dorado' }])

    fireEvent.change(screen.getByLabelText('Precio por unidad del adicional 1'), {
      target: { value: '750.5' }
    })
    expect(onChange).toHaveBeenLastCalledWith([{ ...strass, unitPrice: 750.5 }])

    fireEvent.change(screen.getByLabelText('Cantidad máxima del adicional 1'), {
      target: { value: '6' }
    })
    expect(onChange).toHaveBeenLastCalledWith([{ ...strass, maxQuantity: 6 }])
  })

  it('reordena y quita', () => {
    const onChange = jest.fn()
    render(<ServiceAddonsEditor addons={[strass, diseno]} onChange={onChange} />)

    expect(screen.getByRole('button', { name: 'Subir el adicional 1' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Bajar el adicional 2' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Subir el adicional 2' }))
    expect(onChange).toHaveBeenLastCalledWith([diseno, strass])

    fireEvent.click(screen.getByRole('button', { name: 'Quitar el adicional 1' }))
    expect(onChange).toHaveBeenLastCalledWith([diseno])
  })

  it('con 20 adicionales no deja agregar otro', () => {
    const veinte = Array.from({ length: 20 }, (_, i) => ({ ...strass, key: String(i) }))
    render(<ServiceAddonsEditor addons={veinte} onChange={jest.fn()} />)

    expect(screen.getByRole('button', { name: /Agregar adicional/ })).toBeDisabled()
    expect(screen.getByText(/máximo de 20 adicionales/)).toBeInTheDocument()
  })

  it('deshabilitado no deja editar', () => {
    render(<ServiceAddonsEditor addons={[strass]} onChange={jest.fn()} disabled />)

    expect(screen.getByLabelText('Nombre del adicional 1')).toBeDisabled()
    expect(screen.getByRole('button', { name: /Agregar adicional/ })).toBeDisabled()
  })
})
