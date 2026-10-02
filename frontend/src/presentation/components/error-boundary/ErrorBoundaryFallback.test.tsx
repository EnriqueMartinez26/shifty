import { render, screen } from '@testing-library/react'

import { ErrorBoundaryFallback } from './ErrorBoundaryFallback'

// 2026-10-02, QA en navegador: el respaldo de un error de render se veia en
// ingles ("Something went wrong", "Refresh page").
describe('ErrorBoundaryFallback', () => {
  it('por defecto habla en castellano', () => {
    render(<ErrorBoundaryFallback />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Algo salió mal')
    expect(
      screen.getByText('Actualizá la página o probá de nuevo en unos minutos.')
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Actualizar página' })).toBeInTheDocument()
  })

  it('usa el titulo y la descripcion de quien lo monta', () => {
    render(<ErrorBoundaryFallback title="Pagos no disponibles" description="Probá en un rato." />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Pagos no disponibles')
    expect(screen.getByText('Probá en un rato.')).toBeInTheDocument()
  })
})
