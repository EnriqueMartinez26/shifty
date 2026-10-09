import { fireEvent, render, screen } from '@testing-library/react'

import ActionList from './ActionList'
import type { ActionItem } from './types'

// Rama por rama de `ActionList` (F11b-09): lo que la caracterizacion de la pagina
// no ve porque ahi todas las acciones traen descripcion, meta y `onSelect`.

const item = (overrides: Partial<ActionItem> = {}): ActionItem => ({
  id: 'a1',
  title: 'Confirmar turnos',
  ...overrides
})

const buttonOf = (title: string) => screen.getByText(title).closest('button') as HTMLButtonElement

describe('ActionList', () => {
  it('muestra el texto vacio cuando no hay acciones', () => {
    render(<ActionList items={[]} emptyText="No hay tareas criticas por resolver." />)

    expect(screen.getByText('No hay tareas criticas por resolver.')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('usa la altura y el relleno normales: 72 y 16', () => {
    render(<ActionList items={[item()]} emptyText="vacio" />)

    expect(buttonOf('Confirmar turnos').style.minHeight).toBe('72px')
    expect(buttonOf('Confirmar turnos').style.padding).toBe('16px')
  })

  it('en modo compacto baja la altura y el relleno: 64 y 14', () => {
    render(<ActionList items={[item()]} emptyText="vacio" compact />)

    expect(buttonOf('Confirmar turnos').style.minHeight).toBe('64px')
    expect(buttonOf('Confirmar turnos').style.padding).toBe('14px')
  })

  it('con onSelect el cursor es pointer y el clic lo llama', () => {
    const onSelect = jest.fn()
    render(<ActionList items={[item({ onSelect })]} emptyText="vacio" />)

    expect(buttonOf('Confirmar turnos').style.cursor).toBe('pointer')
    fireEvent.click(buttonOf('Confirmar turnos'))
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('sin onSelect el cursor es default', () => {
    render(<ActionList items={[item()]} emptyText="vacio" />)

    expect(buttonOf('Confirmar turnos').style.cursor).toBe('default')
  })

  it('omite la descripcion y la meta cuando no vienen', () => {
    render(<ActionList items={[item()]} emptyText="vacio" />)

    const button = buttonOf('Confirmar turnos')
    expect(button.querySelector('small')).toBeNull()
    expect(button.querySelector('em')).toBeNull()
  })

  it('muestra la descripcion y la meta, esta con el acento del tono', () => {
    render(
      <ActionList
        items={[item({ description: 'Reservas esperando decision', meta: '3', tone: 'danger' })]}
        emptyText="vacio"
      />
    )

    expect(screen.getByText('Reservas esperando decision')).toBeInTheDocument()
    const meta = screen.getByText('3')
    expect(meta.tagName).toBe('EM')
    expect(meta.style.color).toBe('rgb(209, 59, 59)')
  })

  it('pinta el borde y el fondo del tono en cada boton', () => {
    render(<ActionList items={[item({ tone: 'warning', description: 'x' })]} emptyText="vacio" />)

    const button = buttonOf('Confirmar turnos')
    expect(button.style.border).toBe('1px solid rgba(245, 158, 11, 0.42)')
    expect(button.style.background).toBe('rgba(245, 158, 11, 0.12)')
  })
})
