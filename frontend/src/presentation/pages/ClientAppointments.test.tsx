import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'

import { NetworkError, NotFoundError } from '@shared/errors'

import ClientAppointmentsPage from './ClientAppointments'

const mockGetStoreRef = jest.fn()
const mockGetStore = jest.fn()
const mockContainer = jest.fn()

jest.mock('@application/services/PublicBookingService', () => ({
  publicBookingService: {
    getStoreRef: (...args: unknown[]) => mockGetStoreRef(...args),
    getStore: (...args: unknown[]) => mockGetStore(...args)
  }
}))

// La puerta del telefono y la lista son del container (tiene su propio test):
// aca importa que tienda le llega.
jest.mock('@presentation/containers/ClientAppointmentsContainer', () => ({
  ClientAppointmentsContainer: (props: { store: { name: string } }) => {
    mockContainer(props)
    return <div>Mis turnos de {props.store.name}</div>
  }
}))

const renderEn = (entrada: string) =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[entrada]}>
        <Routes>
          <Route path="/b/:slug/mis-turnos" element={<ClientAppointmentsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )

const AVISO_SUSPENDIDA =
  'Este negocio no está tomando reservas nuevas por ahora. Podés ver, cambiar o cancelar tus turnos.'

describe('ClientAppointmentsPage', () => {
  beforeEach(() => {
    mockGetStoreRef.mockReset()
    mockGetStore.mockReset()
    mockContainer.mockReset()
  })

  it('con la tienda suspendida deja entrar a "Mis turnos" y oculta la reserva nueva (FF-16)', async () => {
    // FF-16 (2026-10-01): con la suscripcion suspendida la vitrina
    // (/public/stores/{slug}) da 404 y la pagina mostraba "Negocio no
    // encontrado": el cliente no podia cancelar ni reprogramar, que el
    // backend sigue permitiendo.
    mockGetStoreRef.mockResolvedValue({
      store_public_id: 'store-1',
      name: 'Peluqueria Sol',
      accepts_new_bookings: false
    })

    renderEn('/b/Sol/mis-turnos')

    expect(await screen.findByText('Mis turnos de Peluqueria Sol')).toBeInTheDocument()
    expect(mockGetStoreRef).toHaveBeenCalledWith('Sol')
    expect(mockContainer).toHaveBeenLastCalledWith({
      store: { public_id: 'store-1', name: 'Peluqueria Sol', slug: 'sol' }
    })
    expect(screen.getByText(AVISO_SUSPENDIDA)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reservar un turno nuevo' })).not.toBeInTheDocument()
    expect(screen.queryByText('Negocio no encontrado')).not.toBeInTheDocument()
    // La vitrina daria 404: ni se pide.
    expect(mockGetStore).not.toHaveBeenCalled()
  })

  it('una tienda inexistente sigue mostrando "Negocio no encontrado" (FF-16)', async () => {
    // FF-16 (2026-10-01): el 404 neutro del ref no tiene que caer en la
    // pantalla de turnos con una tienda vacia.
    mockGetStoreRef.mockRejectedValue(
      new NotFoundError('No encontrado', { errorCode: 'STORE_NOT_FOUND', statusCode: 404 })
    )

    renderEn('/b/nadie/mis-turnos')

    expect(await screen.findByText('Negocio no encontrado')).toBeInTheDocument()
    expect(mockContainer).not.toHaveBeenCalled()
    expect(mockGetStore).not.toHaveBeenCalled()
  })

  it('sin conexion no dice que la tienda no existe y deja reintentar', async () => {
    // 2026-10-02, QA en navegador: con la API caida "Mis turnos" decia
    // "Negocio no encontrado" para cualquier falla. Solo un 404 es "no existe".
    mockGetStoreRef
      .mockRejectedValueOnce(new NetworkError('No se pudo conectar con el servidor.'))
      .mockResolvedValueOnce({
        store_public_id: 'store-1',
        name: 'Peluqueria Sol',
        accepts_new_bookings: false
      })

    renderEn('/b/sol/mis-turnos')

    expect(
      await screen.findByRole('heading', { level: 1, name: 'No pudimos cargar la tienda' })
    ).toBeInTheDocument()
    expect(screen.queryByText('Negocio no encontrado')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))

    expect(await screen.findByText('Mis turnos de Peluqueria Sol')).toBeInTheDocument()
    expect(mockGetStoreRef).toHaveBeenCalledTimes(2)
  })

  it('una tienda que toma reservas muestra el link y la politica de sena (FF-16)', async () => {
    // FF-16 (2026-10-01): la pagina pasa a resolver la tienda por el ref; con
    // la tienda al dia no se pierde el link de reserva ni la politica del pie.
    mockGetStoreRef.mockResolvedValue({
      store_public_id: 'store-1',
      name: 'Peluqueria Sol',
      accepts_new_bookings: true
    })
    mockGetStore.mockResolvedValue({
      public_id: 'store-1',
      name: 'Peluqueria Sol',
      slug: 'sol',
      deposit_policy: 'Sena no reembolsable'
    })

    renderEn('/b/sol/mis-turnos')

    const link = await screen.findByRole('link', { name: 'Reservar un turno nuevo' })
    expect(link).toHaveAttribute('href', '/b/sol')
    expect(screen.queryByText(AVISO_SUSPENDIDA)).not.toBeInTheDocument()
    expect(await screen.findByText('Política de seña publicada por la tienda')).toBeInTheDocument()
    expect(mockGetStore).toHaveBeenCalledWith('sol')
  })
})
