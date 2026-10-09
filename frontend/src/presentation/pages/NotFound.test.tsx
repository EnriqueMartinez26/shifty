import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import NotFoundPage from './NotFound'
import { NotFoundScreen } from '../components/organisms/NotFoundScreen'

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <NotFoundPage />
    </MemoryRouter>
  )

describe('NotFoundPage', () => {
  it('explains the address does not exist and links back to the home page', () => {
    renderAt('/no-existe')

    expect(
      screen.getByRole('heading', { level: 1, name: 'Página no encontrada' })
    ).toBeInTheDocument()
    expect(screen.getByText('La dirección que abriste no existe o cambió.')).toBeInTheDocument()
    const home = screen.getByRole('link', { name: 'Ir al inicio' })
    expect(home).toHaveAttribute('href', '/')
    expect(screen.queryByRole('link', { name: 'Volver a la tienda' })).toBeNull()
  })

  it.each([
    ['/b/mi-tienda/no-existe', '/b/mi-tienda'],
    ['/booking/mi-tienda/algo/mas', '/booking/mi-tienda']
  ])('under a store (%s) offers going back to that store first', (path, store) => {
    renderAt(path)

    const links = screen.getAllByRole('link').slice(0, 2)
    expect(links.map((link) => link.textContent)).toEqual(['Volver a la tienda', 'Ir al inicio'])
    expect(links[0]).toHaveAttribute('href', store)
    expect(links[1]).toHaveAttribute('href', '/')
    // Y, como toda pantalla con la cascara de acceso, los enlaces legales.
    expect(screen.getByRole('link', { name: 'Términos y condiciones' })).toBeInTheDocument()
  })

  it.each(['/b', '/b/', '/bar/mi-tienda', '/b/mi-tienda', '/booking/mi-tienda/'])(
    '%s offers no "Volver a la tienda" (not a store, or already its front page)',
    (path) => {
      renderAt(path)

      expect(screen.queryByRole('link', { name: 'Volver a la tienda' })).toBeNull()
      expect(screen.getByRole('link', { name: 'Ir al inicio' })).toHaveAttribute('href', '/')
    }
  )

  it('a store-level caller can name what was not found', () => {
    render(
      <MemoryRouter initialEntries={['/b/mi-tienda']}>
        <NotFoundScreen
          title="Negocio no encontrado"
          subtitle="No encontramos una tienda en esta dirección."
        />
      </MemoryRouter>
    )

    expect(
      screen.getByRole('heading', { level: 1, name: 'Negocio no encontrado' })
    ).toBeInTheDocument()
    expect(screen.getByText('No encontramos una tienda en esta dirección.')).toBeInTheDocument()
  })
})
