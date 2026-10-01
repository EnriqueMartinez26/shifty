import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

import PublicBooking from './PublicBooking'

jest.mock('../hooks/usePublic', () => ({
  usePublicStore: () => ({
    data: { public_id: 'store-1', name: 'Peluqueria Sol', slug: 'sol', description: null },
    isLoading: false,
    isError: false
  }),
  usePublicPaymentStatus: (_store: string | undefined, paymentId: string | undefined) => ({
    data: paymentId ? { payment_status: 'approved', appointment_status: 'confirmed' } : undefined,
    isError: false
  }),
  usePublicServices: () => ({ data: undefined, isLoading: false }),
  usePublicStaff: () => ({ data: undefined, isLoading: false })
}))

jest.mock('@presentation/components/organisms/booking/BookingWizardContainer', () => ({
  BookingWizardContainer: () => <div>Wizard de reserva</div>
}))

const Ubicacion = () => {
  const location = useLocation()
  return <output aria-label="ubicacion">{`${location.pathname}${location.search}`}</output>
}

const renderEn = (entrada: string) =>
  render(
    <MemoryRouter initialEntries={[entrada]}>
      <Routes>
        <Route
          path="/booking/:slug"
          element={
            <>
              <PublicBooking />
              <Ubicacion />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  )

describe('PublicBooking al volver del pago', () => {
  it('"Volver a la tienda" monta un wizard nuevo sin recargar la pagina (F11b-20)', () => {
    // F11b-20 (2026-09-30): el boton hacia window.location.assign, una recarga
    // completa de la SPA para volver a la misma tienda. Quitar payment_id de la
    // URL alcanza para dejar el estado del pago y montar un wizard nuevo.
    renderEn('/booking/sol?payment_id=p1')
    expect(screen.getByRole('heading', { name: 'Reserva confirmada' })).toBeInTheDocument()
    expect(screen.queryByText('Wizard de reserva')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Volver a la tienda' }))

    expect(screen.getByText('Wizard de reserva')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Reserva confirmada' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('ubicacion')).toHaveTextContent(/^\/booking\/sol$/)
  })
})
