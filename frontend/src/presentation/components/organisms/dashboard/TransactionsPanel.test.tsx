import { fireEvent, render, screen } from '@testing-library/react'

import TransactionsPanel from './TransactionsPanel'
import type { TransactionItem } from './types'

// Rama por rama de `TransactionsPanel` (F11b-09): subtitulo opcional, el tono de
// cada estado (la pagina solo cubre confirmed/completed/cancelled) y el vacio.

const item = (overrides: Partial<TransactionItem> = {}): TransactionItem => ({
  id: 't1',
  title: 'Ana Lopez',
  amount: '$ 15.000',
  status: 'completed',
  ...overrides
})

const renderPanel = (items: TransactionItem[], onViewAll = jest.fn()) =>
  render(
    <TransactionsPanel
      title="Transacciones"
      description="Ultimos turnos del periodo con su estado y monto."
      items={items}
      emptyText="No hay turnos registrados en el periodo."
      viewAllLabel="Ver todas"
      onViewAll={onViewAll}
    />
  )

const rowOf = (title: string) => screen.getByText(title).parentElement?.parentElement as HTMLElement

describe('TransactionsPanel', () => {
  it('muestra el titulo, la descripcion y el texto vacio sin transacciones', () => {
    renderPanel([])

    expect(screen.getByRole('heading', { name: 'Transacciones' })).toBeInTheDocument()
    expect(
      screen.getByText('Ultimos turnos del periodo con su estado y monto.')
    ).toBeInTheDocument()
    expect(screen.getByText('No hay turnos registrados en el periodo.')).toBeInTheDocument()
  })

  it('el boton "Ver todas" llama a onViewAll, tambien sin transacciones', () => {
    const onViewAll = jest.fn()
    renderPanel([], onViewAll)

    const button = screen.getByRole('button', { name: 'Ver todas' })
    expect(button.style.color).toBe('rgb(154, 69, 7)')
    fireEvent.click(button)
    expect(onViewAll).toHaveBeenCalledTimes(1)
  })

  it('arma la fila con relleno 12, fondo blanco al 68% y borde del tono', () => {
    renderPanel([item({ tone: 'danger', status: 'cancelled' })])

    const row = rowOf('Ana Lopez')
    expect(row.style.padding).toBe('12px')
    expect(row.style.background).toBe('rgba(255, 255, 255, 0.68)')
    expect(row.style.border).toBe('1px solid rgba(239, 68, 68, 0.38)')
    expect(screen.getByText('$ 15.000')).toBeInTheDocument()
  })

  it.each([
    ['warning', 'pending', 'rgb(183, 106, 0)', 'rgba(245, 158, 11, 0.12)'],
    ['success', 'completed', 'rgb(15, 159, 110)', 'rgba(16, 185, 129, 0.1)'],
    ['danger', 'cancelled', 'rgb(209, 59, 59)', 'rgba(239, 68, 68, 0.1)'],
    ['primary', 'confirmed', 'rgb(154, 69, 7)', 'rgba(255, 140, 66, 0.12)'],
    [undefined, 'otro', 'rgb(92, 92, 92)', 'rgba(255, 255, 255, 0.45)']
  ] as const)(
    'con tono %s el estado "%s" lleva acento %s y fondo %s',
    (tone, status, accent, background) => {
      renderPanel([item({ tone, status })])

      const pill = screen.getByText(status)
      expect(pill.style.color).toBe(accent)
      expect(pill.style.background).toBe(background)
    }
  )

  it('omite el subtitulo cuando no viene', () => {
    renderPanel([item()])

    expect(rowOf('Ana Lopez').querySelector('small')).toBeNull()
  })

  it('muestra el subtitulo cuando viene', () => {
    renderPanel([item({ subtitle: 'Corte clasico - 28/09 11:00' })])

    expect(screen.getByText('Corte clasico - 28/09 11:00').tagName).toBe('SMALL')
  })
})
