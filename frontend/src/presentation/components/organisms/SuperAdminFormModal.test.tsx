import { useState, type FormEvent } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { SuperAdminFormModal } from './SuperAdminFormModal'

interface HostProps {
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>
}

const Host = ({ onSubmit }: HostProps) => {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>
        Abrir formulario
      </button>
      <SuperAdminFormModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        onSubmit={onSubmit}
        title="Crear plan"
        subtitle="Definí el plan para la tienda."
        submitLabel="Guardar plan"
      >
        <label className="block" htmlFor="plan-name">
          Nombre del plan
        </label>
        <input id="plan-name" name="name" />
        <label className="block" htmlFor="plan-price">
          Precio
        </label>
        <input id="plan-price" name="price" />
      </SuperAdminFormModal>
    </>
  )
}

const openModal = () => {
  const trigger = screen.getByRole('button', { name: 'Abrir formulario' })
  trigger.focus()
  fireEvent.click(trigger)
  return trigger
}

describe('SuperAdminFormModal', () => {
  it('abre un diálogo modal nombrado y enfoca el primer campo', () => {
    render(<Host onSubmit={jest.fn()} />)
    openModal()

    const dialog = screen.getByRole('dialog', { name: 'Crear plan' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-describedby')
    const closeButton = screen.getByRole('button', { name: 'Cerrar ventana' })
    expect(closeButton).toHaveClass('h-11', 'w-11')
    expect(screen.getByLabelText('Nombre del plan')).toHaveFocus()
  })

  it('mantiene Tab y Shift+Tab dentro del diálogo', () => {
    render(<Host onSubmit={jest.fn()} />)
    openModal()

    const closeButton = screen.getByRole('button', { name: 'Cerrar ventana' })
    const saveButton = screen.getByRole('button', { name: 'Guardar plan' })

    closeButton.focus()
    fireEvent.keyDown(closeButton, { key: 'Tab', shiftKey: true })
    expect(saveButton).toHaveFocus()

    fireEvent.keyDown(saveButton, { key: 'Tab' })
    expect(closeButton).toHaveFocus()
  })

  it('Escape cierra el modal y devuelve el foco al disparador', () => {
    render(<Host onSubmit={jest.fn()} />)
    const trigger = openModal()

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Escape' })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('cierra desde el botón accesible de cierre', () => {
    render(<Host onSubmit={jest.fn()} />)
    const trigger = openModal()

    fireEvent.click(screen.getByRole('button', { name: 'Cerrar ventana' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('conserva el envío del formulario y entrega el evento original', () => {
    const onSubmit = jest.fn()
    render(<Host onSubmit={onSubmit} />)
    openModal()

    fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement)

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ type: 'submit' }))
  })
})
