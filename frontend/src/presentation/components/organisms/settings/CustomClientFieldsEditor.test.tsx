import { fireEvent, render, screen } from '@testing-library/react'

import type { StoreCustomField } from '@application/services/StoreSettingsService'

import { CustomClientFieldsEditor } from './CustomClientFieldsEditor'

// 2026-10-02: el editor de campos extra salio de Settings.tsx (F11b-08).
// Devuelve la lista completa con el cambio; la pagina la suma al borrador.

const motivo: StoreCustomField = {
  key: 'motivo',
  label: 'Motivo',
  type: 'text',
  required: false,
  placeholder: '',
  help_text: '',
  options: []
}

describe('CustomClientFieldsEditor', () => {
  it('sin campos lo dice y "Agregar campo" devuelve campo_1', () => {
    const onChange = jest.fn()
    render(<CustomClientFieldsEditor fields={[]} onChange={onChange} />)

    expect(screen.getByText(/No hay campos extra configurados/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Agregar campo' }))

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ key: 'campo_1' })])
  })

  it('agregar con un campo existente numera el siguiente', () => {
    const onChange = jest.fn()
    render(<CustomClientFieldsEditor fields={[motivo]} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Agregar campo' }))

    expect(onChange).toHaveBeenCalledWith([motivo, expect.objectContaining({ key: 'campo_2' })])
  })

  it('cambiar a Lista conserva las opciones y salir de Lista las vacia', () => {
    const onChange = jest.fn()
    const lista = { ...motivo, type: 'select' as const, options: [{ label: 'A', value: 'a' }] }
    render(<CustomClientFieldsEditor fields={[lista]} onChange={onChange} />)

    expect(screen.getByDisplayValue('A|a')).toBeInTheDocument()
    fireEvent.change(screen.getByDisplayValue('Lista'), { target: { value: 'email' } })

    expect(onChange).toHaveBeenCalledWith([{ ...lista, type: 'email', options: [] }])
  })

  it('el boton de borrar quita ese campo', () => {
    const onChange = jest.fn()
    const otro = { ...motivo, key: 'otro', label: 'Otro' }
    const { container } = render(
      <CustomClientFieldsEditor fields={[motivo, otro]} onChange={onChange} />
    )

    // El boton de borrar no tiene nombre accesible: es el unico con solo icono.
    const borrar = container.querySelectorAll<HTMLButtonElement>('button[type="button"]')[1]
    if (!borrar) throw new Error('Falta el boton de borrar')
    fireEvent.click(borrar)

    expect(onChange).toHaveBeenCalledWith([otro])
  })
})
