import { render, screen } from '@testing-library/react'

import { MessageBanner } from './MessageBanner'
import { PageHeader } from './PageHeader'
import { SummaryCards } from './SummaryCards'

// F11b-15: encabezado, aviso y fila de indicadores estaban copiados en
// Cobros, Cobros online, Promociones y Cuentas pendientes.
describe('piezas compartidas de las pantallas operativas', () => {
  it('PageHeader muestra titulo y bajada, y el indicador solo mientras carga', () => {
    const { rerender } = render(
      <PageHeader
        title="Cobros"
        description="Turnos para cobrar."
        isLoading={false}
        loadingText="Cargando cobros..."
      />
    )

    expect(screen.getByRole('heading', { level: 2, name: 'Cobros' })).toBeInTheDocument()
    expect(screen.getByText('Turnos para cobrar.')).toBeInTheDocument()
    expect(screen.queryByText('Cargando cobros...')).not.toBeInTheDocument()

    rerender(
      <PageHeader
        title="Cobros"
        description="Turnos para cobrar."
        isLoading
        loadingText="Cargando cobros..."
      />
    )
    expect(screen.getByText('Cargando cobros...')).toBeInTheDocument()
  })

  it('MessageBanner no ocupa lugar sin mensaje y lo muestra cuando hay uno', () => {
    const { container, rerender } = render(<MessageBanner message="" />)
    expect(container.childElementCount).toBe(0)

    rerender(<MessageBanner message="Devolucion registrada: pay_1" />)
    expect(screen.getByText('Devolucion registrada: pay_1')).toBeInTheDocument()
  })

  it('SummaryCards muestra cada etiqueta con su valor', () => {
    render(
      <SummaryCards
        columns={4}
        cards={[
          { label: 'Por revisar', value: 3 },
          { label: 'Total cobrado', value: '$ 15.000' }
        ]}
      />
    )

    const valorDe = (label: string) => screen.getByText(label).nextElementSibling?.textContent
    expect(valorDe('Por revisar')).toBe('3')
    expect(valorDe('Total cobrado')).toBe('$ 15.000')
  })
})
