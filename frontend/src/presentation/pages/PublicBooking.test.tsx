import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

import { NetworkError, NotFoundError, ServiceUnavailableError } from '@shared/errors'
import { savePriorDesignHandoff } from '@shared/utils/priorDesignHandoff'

import PublicBooking from './PublicBooking'

const mockRefetch = jest.fn()
const mockRefetchTienda = jest.fn()
let mockPago = {
  data: {
    payment_status: 'approved',
    appointment_status: 'confirmed',
    appointment_public_id: 'apt-9'
  },
  pollingStopped: false
}

const TIENDA_SOL = {
  data: {
    public_id: 'store-1',
    name: 'Peluqueria Sol',
    slug: 'sol',
    description: null as string | null,
    logo_url: null as string | null,
    cover_url: null as string | null,
    primary_color: '#000000',
    whatsapp_number: null as string | null,
    deposit_policy: null as string | null
  },
  isLoading: false,
  isError: false,
  error: null as unknown,
  isFetching: false
}
let mockTienda: typeof TIENDA_SOL | (Omit<typeof TIENDA_SOL, 'data'> & { data: undefined }) =
  TIENDA_SOL

jest.mock('../hooks/usePublic', () => ({
  usePublicStore: () => ({ ...mockTienda, refetch: mockRefetchTienda }),
  usePublicPaymentStatus: (_store: string | undefined, paymentId: string | undefined) => ({
    data: paymentId ? mockPago.data : undefined,
    pollingStopped: paymentId ? mockPago.pollingStopped : false,
    isError: false,
    isFetching: false,
    refetch: mockRefetch
  }),
  usePublicServices: () => ({ data: undefined, isLoading: false }),
  useRefreshPublicServices: () => jest.fn(),
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
    mockPago = {
      data: { payment_status, appointment_status, appointment_public_id: 'apt-9' },
      pollingStopped
    }
  }

  beforeEach(() => {
    mockRefetch.mockReset()
    mockTienda = TIENDA_SOL
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

    expect(screen.getByRole('main')).toBeInTheDocument()
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

  // QA 2026-10-21 (S3): la vuelta de Mercado Pago era toda naranja, sin la tienda.
  it('muestra la tienda arriba: su nombre es el titulo principal y el estado va debajo', () => {
    mockTienda = { ...TIENDA_SOL, data: { ...TIENDA_SOL.data, primary_color: '#ff70fa' } }
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Peluqueria Sol')
    expect(
      screen.getByRole('heading', { level: 2, name: 'Reserva confirmada' })
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Mis turnos' })).toHaveAttribute(
      'href',
      '/b/sol/mis-turnos'
    )
    expect(screen.getByRole('main').style.getPropertyValue('--brand-fill')).toBe('#ff70fa')
    const volver = screen.getByRole('button', { name: 'Volver a la tienda' })
    expect(volver.getAttribute('style')).toContain('var(--brand-fill,')
    expect(volver.getAttribute('style')).toContain('var(--brand-on-fill,')
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

// QA 2026-10-21 (S7, Mateo): "si tengo seña por mercado pago me paga y le sale
// una redireccion al numero de natalia para enviar el diseño junto con el turno
// respectivo". El paso de confirmacion guarda el resumen antes de ir a MP y la
// vuelta muestra el mismo bloque del diseño previo.
describe('PublicBooking: diseño previo al volver de Mercado Pago', () => {
  const BOTON = 'Enviar mi diseño por WhatsApp'
  const pagoCon = (payment_status: string, appointment_status: string) => {
    mockPago = {
      data: { payment_status, appointment_status, appointment_public_id: 'apt-9' },
      pollingStopped: false
    }
  }
  const guardarResumen = (appointmentPublicId = 'apt-9') =>
    savePriorDesignHandoff('store-1', {
      appointmentPublicId,
      serviceName: 'Uñas esculpidas',
      servicesLabel: null,
      addons: [{ name: 'Strass', quantity: 6 }],
      clientFirstName: 'Lucia',
      startsAt: '2026-10-23T18:00:00+00:00',
      message: 'Mandame una foto'
    })

  beforeEach(() => {
    window.sessionStorage.clear()
    pagoCon('approved', 'confirmed')
    mockTienda = { ...TIENDA_SOL, data: { ...TIENDA_SOL.data, whatsapp_number: '11 5555 0303' } }
  })

  afterEach(() => {
    jest.restoreAllMocks()
    mockTienda = TIENDA_SOL
  })

  it.each([
    ['aprobado', 'approved', 'confirmed', 'Reserva confirmada'],
    ['pendiente', 'pending', 'pending_payment', 'Estamos validando tu pago']
  ])(
    'con el pago %s y el resumen del turno muestra el mensaje y el boton de WhatsApp',
    (_caso, pago, turno, titulo) => {
      pagoCon(pago, turno)
      guardarResumen()
      renderEn('/booking/sol?payment_id=p1')

      expect(screen.getByRole('heading', { level: 2, name: titulo })).toBeInTheDocument()
      expect(screen.getByText('Mandame una foto')).toBeInTheDocument()
      const href = screen.getByRole('link', { name: BOTON }).getAttribute('href') ?? ''
      expect(href).toMatch(/^https:\/\/wa\.me\/5491155550303\?text=/)
      expect(decodeURIComponent(href.split('?text=')[1] ?? '')).toContain(
        'soy Lucia.\nReservé Uñas esculpidas (Strass x6) para el'
      )
      expect(decodeURIComponent(href)).toContain('(turno apt-9)')
    }
  )

  it.each([
    ['rechazado', 'rejected', 'expired'],
    ['vencido', 'expired', 'expired']
  ])('con el pago %s no lo muestra', (_caso, pago, turno) => {
    pagoCon(pago, turno)
    guardarResumen()
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { name: 'La seña no fue aprobada' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: BOTON })).not.toBeInTheDocument()
  })

  it('con el resumen de otro turno no lo muestra', () => {
    guardarResumen('apt-otro')
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { name: 'Reserva confirmada' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: BOTON })).not.toBeInTheDocument()
  })

  it('sin storage no muestra el bloque y el estado del pago sigue igual', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError')
    })
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('heading', { name: 'Reserva confirmada' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: BOTON })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Volver a la tienda' })).toBeInTheDocument()
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
    expect(link).toHaveClass('min-h-11', 'min-w-11', 'break-all')
  })

  it('un numero que no se puede leer se muestra sin link', () => {
    conWhatsApp('pedir en el local')
    renderEn('/booking/sol')

    expect(screen.getByText('pedir en el local').closest('a')).toBeNull()
  })
})

// 2026-10-21 (S1, S2): el encabezado decia "Reservar turno" sobre un icono
// generico; ahora es la tienda (logo, nombre, WhatsApp) con su portada.
describe('PublicBooking: encabezado y portada de la tienda', () => {
  const conTienda = (data: Partial<typeof TIENDA_SOL.data>) => {
    mockTienda = { ...TIENDA_SOL, data: { ...TIENDA_SOL.data, ...data } }
  }

  afterEach(() => {
    mockTienda = TIENDA_SOL
  })

  it('el titulo principal es el nombre de la tienda, no "Reservar turno"', () => {
    renderEn('/booking/sol')

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Peluqueria Sol')
    expect(screen.queryByText('Reservar turno')).not.toBeInTheDocument()
  })

  it('muestra el logo y la portada que subio la tienda', () => {
    conTienda({ logo_url: '/media/logo.png', cover_url: '/media/cover.webp' })
    const { container } = renderEn('/booking/sol')

    expect(screen.getByRole('img', { name: 'Logo de Peluqueria Sol' })).toHaveAttribute(
      'src',
      '/media/logo.png'
    )
    expect(container.querySelector('img[src="/media/cover.webp"]')).toHaveAttribute('alt', '')
  })

  it('sin logo ni portada usa la inicial y la franja con el color de la tienda', () => {
    conTienda({ primary_color: '#123456' })
    renderEn('/booking/sol')

    expect(screen.getByText('P').style.background).toBe('rgb(18, 52, 86)')
    expect(screen.getByTestId('store-cover-band').style.background).toBe('rgb(18, 52, 86)')
  })

  it('sin WhatsApp no dice "Reserva por web disponible"', () => {
    renderEn('/booking/sol')

    expect(screen.queryByText('Reserva por web disponible')).not.toBeInTheDocument()
  })

  it('la descripcion y el wizard siguen debajo', () => {
    conTienda({ description: 'Cortes y color en el centro.' })
    renderEn('/booking/sol')

    expect(screen.getByText('Cortes y color en el centro.')).toBeInTheDocument()
    expect(screen.getByText('Wizard de reserva')).toBeInTheDocument()
  })
})

describe('PublicBooking: objetivos táctiles', () => {
  it('expone el contenido de la reserva dentro de un landmark principal', () => {
    renderEn('/booking/sol')

    expect(screen.getByRole('main')).toBeInTheDocument()
  })

  it('mantiene Mis turnos y los enlaces legales con altura mínima de 44 px', () => {
    renderEn('/booking/sol')

    const misTurnos = screen.getByRole('link', { name: 'Mis turnos' })
    expect(misTurnos).toHaveClass('min-h-11')
    expect(misTurnos).toHaveAttribute('href', '/b/sol/mis-turnos')
    expect(screen.getByRole('link', { name: 'Términos y condiciones' })).toHaveClass('min-h-11')
    expect(screen.getByRole('link', { name: 'Privacidad' })).toHaveClass('min-h-11')
  })

  it('conserva objetivos legales en el retorno del pago', () => {
    renderEn('/booking/sol?payment_id=p1')

    expect(screen.getByRole('link', { name: 'Términos y condiciones' })).toHaveClass('min-h-11')
    expect(screen.getByRole('link', { name: 'Privacidad' })).toHaveClass('min-h-11')
  })

  // QA 2026-10-21 (S5): en el celular la barra fija de pago tapaba los links
  // del pie al final de la pagina.
  it('en la confirmacion la pagina reserva abajo el alto de la barra fija, solo en el celular', () => {
    renderEn('/booking/sol?step=2')

    expect(screen.getByRole('main')).toHaveClass(
      'pb-[calc(8rem+env(safe-area-inset-bottom))]',
      'sm:pb-12'
    )
  })

  it('en los otros pasos la pagina no reserva ese espacio', () => {
    renderEn('/booking/sol?step=1')

    expect(screen.getByRole('main')).not.toHaveClass('pb-[calc(8rem+env(safe-area-inset-bottom))]')
    expect(screen.getByRole('main')).toHaveClass('py-8')
  })
})

// 2026-10-16 (pedido de Mateo): en el paso de confirmacion la politica de seña
// salia entera junto a la seña y el pie la volvia a nombrar. Se muestra antes
// de confirmar (Legal.tsx) en el paso mismo; el pie la nombra en los demas.
describe('PublicBooking: politica de seña en el pie', () => {
  const POLITICA_EN_EL_PIE = 'Política de seña publicada por la tienda'

  beforeEach(() => {
    mockTienda = {
      ...TIENDA_SOL,
      data: { ...TIENDA_SOL.data, deposit_policy: 'La seña no se devuelve.' }
    }
  })

  afterEach(() => {
    mockTienda = TIENDA_SOL
  })

  it('en el servicio y el horario el pie nombra la politica de la tienda', () => {
    renderEn('/booking/sol?step=1')

    expect(screen.getByText(POLITICA_EN_EL_PIE)).toBeInTheDocument()
  })

  it('en el paso de confirmacion el pie no la repite y deja terminos y privacidad', () => {
    renderEn('/booking/sol?step=2')

    expect(screen.queryByText(POLITICA_EN_EL_PIE)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Términos y condiciones' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Privacidad' })).toBeInTheDocument()
  })
})

const sinTienda = (error: unknown) => {
  mockTienda = { ...TIENDA_SOL, data: undefined, isError: true, error }
}

describe('PublicBooking con una tienda que no existe', () => {
  afterEach(() => {
    mockTienda = TIENDA_SOL
  })

  it('muestra la pantalla de no encontrado con salida al inicio', () => {
    // Antes: un texto suelto "Negocio no encontrado" sin ningun link.
    sinTienda(new NotFoundError('Tienda no encontrada', { statusCode: 404 }))
    renderEn('/booking/no-existe')

    expect(
      screen.getByRole('heading', { level: 1, name: 'Negocio no encontrado' })
    ).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ir al inicio' })).toHaveAttribute('href', '/')
    // Ya esta en la portada de esa tienda: "volver" a ella no saca de ningun lado.
    expect(screen.queryByRole('link', { name: 'Volver a la tienda' })).toBeNull()
  })
})

// 2026-10-02, QA en navegador: con la API caida (red o 5xx) el portal decia
// "Negocio no encontrado", como si la tienda no existiera, y no habia forma de
// reintentar. Solo un 404 es "no existe"; lo demas es una falla pasajera.
describe('PublicBooking cuando la tienda no se pudo consultar', () => {
  afterEach(() => {
    mockTienda = TIENDA_SOL
    mockRefetchTienda.mockReset()
  })

  it.each([
    ['sin conexión', new NetworkError('No se pudo conectar con el servidor.')],
    ['un 503', new ServiceUnavailableError('Servicio no disponible', { statusCode: 503 })]
  ])('con %s no dice que la tienda no existe y deja reintentar', (_caso, error) => {
    sinTienda(error)
    renderEn('/booking/sol')

    expect(screen.queryByText('Negocio no encontrado')).not.toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'No pudimos cargar la tienda'
    )

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))

    expect(mockRefetchTienda).toHaveBeenCalledTimes(1)
  })

  it('mientras reintenta deshabilita el boton', () => {
    mockTienda = {
      ...TIENDA_SOL,
      data: undefined,
      isError: true,
      error: new NetworkError('No se pudo conectar con el servidor.'),
      isFetching: true
    }
    renderEn('/booking/sol')

    expect(screen.getByRole('button', { name: 'Reintentando...' })).toBeDisabled()
  })
})

// 2026-10-03: ninguna pagina fijaba document.title; la pestaña (y el link
// guardado) decia "Shifty" en cualquier tienda.
describe('PublicBooking: titulo de la pestaña', () => {
  beforeEach(() => {
    document.title = 'Shifty'
  })

  afterEach(() => {
    mockTienda = TIENDA_SOL
  })

  it('lleva el nombre de la tienda y lo devuelve al salir', () => {
    const { unmount } = renderEn('/booking/sol')

    expect(document.title).toBe('Peluqueria Sol · Reservá tu turno')

    unmount()
    expect(document.title).toBe('Shifty')
  })

  it('una tienda que no existe titula la pestaña como el 404', () => {
    sinTienda(new NotFoundError('Tienda no encontrada', { statusCode: 404 }))
    renderEn('/booking/no-existe')

    expect(document.title).toBe('Negocio no encontrado · Shifty')
  })
})
