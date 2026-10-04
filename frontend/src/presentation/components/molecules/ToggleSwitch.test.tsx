import type React from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { ToggleSwitch } from './ToggleSwitch'
import { colors2000s } from '../../../theme/colors'

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

  it('prendido conserva el relleno de marca y suma un anillo acento contra el blanco', () => {
    // Solo el naranja de marca contra la tarjeta blanca da 2.31:1 (N4); el
    // anillo orange.accent lleva el borde a 6.50:1.
    render(<ToggleSwitch label="Seña" checked onToggle={jest.fn()} />)

    const interruptor = screen.getByRole('switch', { name: 'Seña' })
    expect(interruptor.style.boxShadow).toContain(`inset 0 0 0 1px ${colors2000s.orange.accent}`)
    expect(interruptor.style.background).toBe('rgb(255, 140, 66)')
  })
})

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15): el interruptor acepta disabled y su motivo.
describe('ToggleSwitch: deshabilitado', () => {
  it('deshabilitado muestra el motivo y no avisa el click', () => {
    const onToggle = jest.fn()
    render(<ToggleSwitch label="Pagos" checked onToggle={onToggle} disabled title="Suspendida" />)

    const interruptor = screen.getByRole('switch', { name: 'Pagos' })
    fireEvent.click(interruptor)

    expect(interruptor).toBeDisabled()
    expect(interruptor).toHaveAttribute('title', 'Suspendida')
    expect(onToggle).not.toHaveBeenCalled()
  })
})
