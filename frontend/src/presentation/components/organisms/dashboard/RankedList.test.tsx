import { render, screen } from '@testing-library/react'

import RankedList from './RankedList'
import type { RankedItem } from './types'

// Rama por rama de `RankedList` (F11b-09): el detalle es opcional y los literales
// de la fila no los fija la pagina.

const item = (overrides: Partial<RankedItem> = {}): RankedItem => ({
  id: 'r1',
  label: 'Corte clasico',
  value: '30',
  ...overrides
})

describe('RankedList', () => {
  it('muestra su texto vacio fijo cuando no hay datos', () => {
    render(<RankedList items={[]} />)

    expect(screen.getByText('Sin datos para este periodo.')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('numera desde 1, con altura 70, relleno 14 y fondo blanco al 65%', () => {
    render(<RankedList items={[item(), item({ id: 'r2', label: 'Color', value: '10' })]} />)

    const rows = screen.getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual(['1Corte clasico30', '2Color10'])
    const [first] = rows as [HTMLElement, ...HTMLElement[]]
    expect(first.style.minHeight).toBe('70px')
    expect(first.style.padding).toBe('14px')
    expect(first.style.background).toBe('rgba(255, 255, 255, 0.65)')
  })

  it('pinta el numero y el valor con el naranja de acento', () => {
    render(<RankedList items={[item()]} />)

    const row = screen.getByRole('listitem')
    const badge = row.querySelector('span') as HTMLElement
    expect(badge.textContent).toBe('1')
    expect(badge.style.color).toBe('rgb(154, 69, 7)')
    expect(badge.style.background).toBe('rgba(255, 140, 66, 0.12)')
    expect(screen.getByText('30').style.color).toBe('rgb(154, 69, 7)')
  })

  it('omite el detalle cuando no viene', () => {
    render(<RankedList items={[item()]} />)

    expect(screen.getByRole('listitem').querySelector('small')).toBeNull()
  })

  it('muestra el detalle cuando viene', () => {
    render(<RankedList items={[item({ detail: '30 reservas' })]} />)

    expect(screen.getByText('30 reservas').tagName).toBe('SMALL')
  })
})
