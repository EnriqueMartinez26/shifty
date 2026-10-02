import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

import PublicBooking from './PublicBooking'

const mockRefetch = jest.fn()
let mockPago = {
  data: { payment_status: 'approved', appointment_status: 'confirmed' },
  pollingStopped: false
}

const TIENDA_SOL = {
  data: {
    public_id: 'store-1',
    name: 'Peluqueria Sol',
    slug: 'sol',
    description: null,
    whatsapp_number: null as string | null
  },
  isLoading: false,
  isError: false
}
let mockTienda: { data: typeof TIENDA_SOL.data | undefined; isLoading: boolean; isError: boolean } =
  TIENDA_SOL

jest.mock('../hooks/usePublic', () => ({
  usePublicStore: () => mockTienda,
  usePublicPaymentStatus: (_store: string | undefined, paymentId: string | undefined) => ({
    data: paymentId ? mockPago.data : undefined,
    pollingStopped: paymentId ? mockPago.pollingStopped : false,
    isError: false,
    isFetching: false,
    refetch: mockRefetch
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
  const pagoCon = (payment_status: string, appointment_status: string, pollingStopped = false) => {
    mockPago = { data: { payment_status, appointment_status }, pollingStopped }
  }

  beforeEach(() => {
    mockRefetch.mockReset()
    pagoCon('approved', 'confirmed')
  })

  const avisoDeCorte =
    'Todavía no recibimos la confirmación del pago. Si ya pagaste, tu turno se confirma cuando Mercado Pago avise; podés volver a consultar o hablar con la tienda.'

  it('con el pago pendiente pide no cerrar la pantalla y todavia no ofrece reconsultar', () => {
    pagoCon('pending', 'pending_payment')
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { name: 'Estamos validando tu pago' })).toBeInTheDocument()
    expect(screen.getByText(/No cierres esta pantalla/)).toBeInTheDocument()
    expect(screen.queryByText(avisoDeCorte)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Volver a consultar' })).not.toBeInTheDocument()
  })

  it('con el pago aprobado y el turno confirmado muestra la reserva confirmada', () => {
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { name: 'Reserva confirmada' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Volver a consultar' })).not.toBeInTheDocument()
  })

  it('con el pago rechazado avisa que la seña no fue aprobada', () => {
    pagoCon('rejected', 'expired')
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { name: 'La seña no fue aprobada' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Volver a consultar' })).not.toBeInTheDocument()
  })

  it('al cortar el sondeo avisa, ofrece reconsultar y no da el turno por confirmado (F4-05)', () => {
    // F4-05 (2026-09-30): sondeo fijo de 2 s sin corte, unas 900 requests en
    // 30 min. Con el corte la pantalla lo dice y deja reconsultar a mano; la
    // confirmacion sigue siendo solo del webhook (regla 7).
    pagoCon('pending', 'pending_payment', true)
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByText(avisoDeCorte)).toBeInTheDocument()
    expect(screen.queryByText(/No cierres esta pantalla/)).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Reserva confirmada' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Volver a consultar' }))

    expect(mockRefetch).toHaveBeenCalledTimes(1)
  })

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

// 2026-10-02, QA en navegador: el WhatsApp de la tienda es texto libre y solo
// se limpiaba de simbolos; un numero local armaba un wa.me de otro pais.
describe('PublicBooking: WhatsApp de la tienda', () => {
  const conWhatsApp = (whatsapp_number: string) => {
    mockTienda = { ...TIENDA_SOL, data: { ...TIENDA_SOL.data, whatsapp_number } }
  }

  afterEach(() => {
    mockTienda = TIENDA_SOL
  })

  it('un numero local arma el link con 549 adelante', () => {
    conWhatsApp('351 555-1234')
    renderEn('/booking/sol')

    const link = screen.getByRole('link', { name: '351 555-1234' })
    expect(link.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/5493515551234\?text=/)
  })

  it('un numero que no se puede leer se muestra sin link', () => {
    conWhatsApp('pedir en el local')
    renderEn('/booking/sol')

    expect(screen.getByText('pedir en el local').closest('a')).toBeNull()
  })
})

describe('PublicBooking con una tienda que no existe', () => {
  afterEach(() => {
    mockTienda = TIENDA_SOL
  })

  it('muestra la pantalla de no encontrado con salida al inicio', () => {
    // Antes: un texto suelto "Negocio no encontrado" sin ningun link.
    mockTienda = { data: undefined, isLoading: false, isError: true }
    renderEn('/booking/no-existe')

    expect(
      screen.getByRole('heading', { level: 1, name: 'Negocio no encontrado' })
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ir al inicio' })).toHaveAttribute('href', '/')
    // Ya esta en la portada de esa tienda: "volver" a ella no saca de ningun lado.
    expect(screen.queryByRole('link', { name: 'Volver a la tienda' })).toBeNull()
  })
})
