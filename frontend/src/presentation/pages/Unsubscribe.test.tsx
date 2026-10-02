import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { NetworkError, ValidationError } from '@shared/errors'

import UnsubscribePage from './Unsubscribe'

// 2026-10-02, QA en navegador: el link de baja del mail "volve a reservar"
// apuntaba a GET /public/unsubscribe de la API y la persona veia
// {"status":"unsubscribed"} crudo. Ademas un escaner de correo que abre los
// links la daba de baja sin que lo pidiera. La pagina /baja pide confirmar y
// recien ahi hace el POST.
const mockPost = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: { post: (...args: unknown[]) => mockPost(...args) }
}))

const TOKEN = 'tienda.cliente.1790000000.firma'

const renderAt = (path: string) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <UnsubscribePage />
      </MemoryRouter>
    </QueryClientProvider>
  )

const confirmar = () => fireEvent.click(screen.getByRole('button', { name: 'Darme de baja' }))

describe('UnsubscribePage', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  it('al abrir el link no da de baja: pide confirmar', () => {
    renderAt(`/baja?token=${encodeURIComponent(TOKEN)}`)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Dejar de recibir invitaciones'
    )
    expect(screen.getByRole('button', { name: 'Darme de baja' })).not.toBeDisabled()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('al confirmar manda el token por POST y muestra la baja registrada', async () => {
    mockPost.mockResolvedValueOnce({ data: { status: 'unsubscribed' } })
    renderAt(`/baja?token=${encodeURIComponent(TOKEN)}`)

    confirmar()

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Baja registrada' })
    ).toBeInTheDocument()
    expect(mockPost).toHaveBeenCalledWith('/public/unsubscribe', { token: TOKEN })
    expect(screen.getByText(/se siguen enviando/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Darme de baja' })).toBeNull()
    expect(screen.queryByText(/unsubscribed/)).toBeNull()
  })

  it('un link adulterado o vencido dice que no es valido, sin reintentar', async () => {
    mockPost.mockRejectedValueOnce(
      new ValidationError('Link invalido', {
        statusCode: 400,
        errorCode: 'UNSUBSCRIBE_LINK_INVALID'
      })
    )
    renderAt(`/baja?token=${encodeURIComponent(TOKEN)}`)

    confirmar()

    expect(
      await screen.findByRole('heading', { level: 1, name: 'El enlace no es válido' })
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Darme de baja' })).toBeNull()
    expect(screen.queryByText('Link invalido')).toBeNull()
  })

  it('una falla de red deja reintentar y no da el link por invalido', async () => {
    mockPost
      .mockRejectedValueOnce(new NetworkError('No se pudo conectar con el servidor.'))
      .mockResolvedValueOnce({ data: { status: 'unsubscribed' } })
    renderAt(`/baja?token=${encodeURIComponent(TOKEN)}`)

    confirmar()

    expect(await screen.findByRole('alert')).toHaveTextContent('No pudimos registrar la baja')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Dejar de recibir invitaciones'
    )

    confirmar()

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Baja registrada' })
    ).toBeInTheDocument()
    expect(mockPost).toHaveBeenCalledTimes(2)
  })

  it('sin token en la direccion no ofrece la baja ni llama a la API', () => {
    renderAt('/baja')

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('El enlace no es válido')
    expect(screen.queryByRole('button', { name: 'Darme de baja' })).toBeNull()
    expect(mockPost).not.toHaveBeenCalled()
  })
})
