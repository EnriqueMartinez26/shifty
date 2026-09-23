import type React from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { ToggleSwitch } from './ToggleSwitch'

describe('ToggleSwitch', () => {
  it('se anuncia como interruptor con su nombre y su estado', () => {
    // F11b-12: las copias a mano eran un <button> mudo; un lector de pantalla
    // no sabia que controlaban ni si estaban prendidas.
    const { rerender } = render(
      <ToggleSwitch label="Recordatorios 24hs" checked={false} onToggle={jest.fn()} />
    )

    const interruptor = screen.getByRole('switch', { name: 'Recordatorios 24hs' })
    expect(interruptor).toHaveAttribute('aria-checked', 'false')

    rerender(<ToggleSwitch label="Recordatorios 24hs" checked onToggle={jest.fn()} />)
    expect(interruptor).toHaveAttribute('aria-checked', 'true')
  })

  it('avisa el click y no envia el formulario que lo contiene', () => {
    const onToggle = jest.fn()
    const onSubmit = jest.fn((event: React.FormEvent) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <ToggleSwitch label="Promoción activa" checked onToggle={onToggle} />
      </form>
    )

    fireEvent.click(screen.getByRole('switch', { name: 'Promoción activa' }))

    expect(onToggle).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
