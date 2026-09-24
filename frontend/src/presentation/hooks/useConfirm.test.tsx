import { act, fireEvent, render, screen } from '@testing-library/react'

import { useConfirm } from './useConfirm'

let answer: Promise<boolean> | null = null

const Host = () => {
  const { confirm, confirmDialog } = useConfirm()
  return (
    <>
      <button
        type="button"
        onClick={() => {
          answer = confirm('¿Eliminar este usuario?')
        }}
      >
        Eliminar
      </button>
      {confirmDialog}
    </>
  )
}

const openDialog = () => {
  const trigger = screen.getByRole('button', { name: 'Eliminar' })
  trigger.focus()
  fireEvent.click(trigger)
  return { trigger, dialog: screen.getByRole('alertdialog', { name: '¿Eliminar este usuario?' }) }
}

describe('useConfirm + ConfirmDialog', () => {
  beforeEach(() => {
    answer = null
  })

  it('abre un dialogo modal con la pregunta y el foco en Cancelar', () => {
    render(<Host />)

    const { dialog } = openDialog()

    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: 'Cancelar' })).toHaveFocus()
  })

  it('Confirmar resuelve true, cierra y devuelve el foco', async () => {
    render(<Host />)
    const { trigger } = openDialog()

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

    await act(async () => {
      await expect(answer).resolves.toBe(true)
    })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('Cancelar resuelve false', async () => {
    render(<Host />)
    openDialog()

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))

    await act(async () => {
      await expect(answer).resolves.toBe(false)
    })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('Escape cancela', async () => {
    render(<Host />)
    const { dialog } = openDialog()

    fireEvent.keyDown(dialog, { key: 'Escape' })

    await act(async () => {
      await expect(answer).resolves.toBe(false)
    })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('Tab no se escapa del dialogo', () => {
    render(<Host />)
    const { dialog } = openDialog()

    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Confirmar' })).toHaveFocus()

    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('button', { name: 'Cancelar' })).toHaveFocus()
  })
})
