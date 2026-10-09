import { fireEvent, render, screen } from '@testing-library/react'

import OpportunityList from './OpportunityList'
import type { OpportunityItem } from './types'

// Rama por rama de `OpportunityList` (F11b-09): el boton exige `actionLabel` Y
// `onSelect`, y el fondo de la tarjeta es un literal que la pagina no fija.

const item = (overrides: Partial<OpportunityItem> = {}): OpportunityItem => ({
  id: 'o1',
  title: 'Dia con capacidad libre',
  description: 'Queda 37,5% sin ocupar.',
  ...overrides
})

const cardOf = (title: string) =>
  screen.getByText(title).parentElement?.parentElement as HTMLElement

describe('OpportunityList', () => {
  it('muestra el texto vacio cuando no hay oportunidades', () => {
    render(<OpportunityList items={[]} emptyText="Sin oportunidades destacadas por ahora." />)

    expect(screen.getByText('Sin oportunidades destacadas por ahora.')).toBeInTheDocument()
  })

  it('arma la tarjeta con fondo blanco al 62%, relleno 16 y el borde del tono', () => {
    render(<OpportunityList items={[item({ tone: 'success' })]} emptyText="vacio" />)

    const card = cardOf('Dia con capacidad libre')
    expect(card.style.background).toBe('rgba(255, 255, 255, 0.62)')
    expect(card.style.padding).toBe('16px')
    expect(card.style.border).toBe('1px solid rgba(16, 185, 129, 0.45)')
    expect(screen.getByText('Queda 37,5% sin ocupar.')).toBeInTheDocument()
  })

  it('muestra el boton con el acento del tono y el clic llama a onSelect', () => {
    const onSelect = jest.fn()
    render(
      <OpportunityList
        items={[item({ tone: 'primary', actionLabel: 'Ver agenda', onSelect })]}
        emptyText="vacio"
      />
    )

    const button = screen.getByRole('button', { name: 'Ver agenda' })
    expect(button.style.color).toBe('rgb(154, 69, 7)')
    fireEvent.click(button)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('no muestra el boton sin actionLabel', () => {
    render(<OpportunityList items={[item({ onSelect: jest.fn() })]} emptyText="vacio" />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('no muestra el boton sin onSelect', () => {
    render(<OpportunityList items={[item({ actionLabel: 'Ver agenda' })]} emptyText="vacio" />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
