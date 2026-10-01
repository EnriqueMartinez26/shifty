import type { ReactElement, ReactNode } from 'react'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Outlet } from 'react-router'

import App from './App'

/**
 * Caracterizacion de la tabla de rutas (F12-06): ruta x rol -> que pagina
 * renderiza o adonde redirige. Caja negra: paginas, layouts, sesion y
 * `Sentry.ErrorBoundary` son marcadores; los roles esperados estan escritos a
 * mano aca, no importados de `App`, para que un rol mal transcrito falle.
 */

type Sesion = { token: string | null; user: { role: string; is_global_admin: boolean } | null }

type EstadoAuth = Sesion & {
  isLoading: boolean
  isReconnecting: boolean
  sessionUnavailable: boolean
  retrySession: () => void
}

let mockAuth: EstadoAuth

function mockPage(nombre: string) {
  return { __esModule: true, default: () => <span data-testid="marker">{`page:${nombre}`}</span> }
}

function mockLayout(nombre: string) {
  return {
    __esModule: true,
    default: () => (
      <>
        <span data-testid="marker">{`layout:${nombre}`}</span>
        <Outlet />
      </>
    )
  }
}

function mockAuthProvider({ children }: { children: ReactNode }) {
  return (
    <>
      <span data-testid="marker">auth</span>
      {children}
    </>
  )
}

function mockErrorBoundary({
  children,
  fallback
}: {
  children: ReactNode
  fallback: ReactElement<{ title: string }>
}) {
  return (
    <>
      <span data-testid="marker">{`boundary:${fallback.props.title}`}</span>
      {children}
    </>
  )
}

jest.mock('./infrastructure/observability/sentry', () => ({
  Sentry: { ErrorBoundary: mockErrorBoundary }
}))
jest.mock('./presentation/context/AuthContext', () => ({
  AuthProvider: mockAuthProvider,
  useAuth: () => mockAuth
}))
jest.mock('./presentation/pages/Login', () => mockPage('Login'))
jest.mock('./presentation/pages/ForgotPassword', () => mockPage('ForgotPassword'))
jest.mock('./presentation/pages/ResetPassword', () => mockPage('ResetPassword'))
jest.mock('./presentation/layouts/AdminLayout', () => mockLayout('Admin'))
jest.mock('./presentation/layouts/SuperAdminLayout', () => mockLayout('SuperAdmin'))
jest.mock('./presentation/pages/Dashboard', () => mockPage('Dashboard'))
jest.mock('./presentation/pages/Calendar', () => mockPage('Calendar'))
jest.mock('./presentation/pages/Reports', () => mockPage('Reports'))
jest.mock('./presentation/pages/Payments', () => mockPage('Payments'))
jest.mock('./presentation/pages/Collections', () => mockPage('Collections'))
jest.mock('./presentation/pages/Promotions', () => mockPage('Promotions'))
jest.mock('./presentation/pages/Ledger', () => mockPage('Ledger'))
jest.mock('./presentation/pages/Services', () => mockPage('Services'))
jest.mock('./presentation/pages/Staff', () => mockPage('Staff'))
jest.mock('./presentation/pages/Waitlist', () => mockPage('Waitlist'))
jest.mock('./presentation/pages/SuperAdmin', () => mockPage('SuperAdmin'))
jest.mock('./presentation/pages/Users', () => mockPage('Users'))
jest.mock('./presentation/pages/PublicBooking', () => mockPage('PublicBooking'))
jest.mock('./presentation/pages/ClientAppointments', () => mockPage('ClientAppointments'))
jest.mock('./presentation/pages/Settings', () => mockPage('Settings'))
jest.mock('./presentation/pages/Legal', () => mockPage('Legal'))
jest.mock('./presentation/pages/Manual', () => mockPage('Manual'))

const SESIONES = {
  super_admin: { role: 'super_admin', is_global_admin: true },
  // Un admin de tienda con la llave global cuenta como super admin.
  admin_con_llave_global: { role: 'store_admin', is_global_admin: true },
  store_admin: { role: 'store_admin', is_global_admin: false },
  professional: { role: 'professional', is_global_admin: false },
  receptionist: { role: 'receptionist', is_global_admin: false },
  client: { role: 'client', is_global_admin: false },
  admin_legacy: { role: 'admin', is_global_admin: false },
  staff_legacy: { role: 'staff', is_global_admin: false }
} as const

type NombreSesion = keyof typeof SESIONES

const TODOS = Object.keys(SESIONES) as NombreSesion[]
const SUPER: NombreSesion[] = ['super_admin', 'admin_con_llave_global']
const ADMIN_SUPER: NombreSesion[] = [...SUPER, 'store_admin', 'admin_legacy']
const ADMIN_SUPER_PRO: NombreSesion[] = [...ADMIN_SUPER, 'professional', 'staff_legacy']

const BOUNDARY_ADMIN = 'boundary:The admin area is temporarily unavailable'
const BOUNDARY_GLOBAL = 'boundary:Global control is temporarily unavailable'
const BOUNDARY_BOOKING = 'boundary:Booking is temporarily unavailable'

type RutaPanel = {
  ruta: string
  permitidos: NombreSesion[]
  marcadores: string[]
  // Solo `/dashboard/superadmin`: el permitido termina en otra ruta.
  destino?: string
}

const PANEL_ADMIN = ['auth', BOUNDARY_ADMIN, 'layout:Admin']
const PANEL_GLOBAL = ['auth', BOUNDARY_GLOBAL, 'layout:SuperAdmin', 'page:SuperAdmin']

const RUTAS_PANEL: RutaPanel[] = [
  { ruta: '/dashboard', permitidos: TODOS, marcadores: [...PANEL_ADMIN, 'page:Dashboard'] },
  { ruta: '/dashboard/manual', permitidos: TODOS, marcadores: [...PANEL_ADMIN, 'page:Manual'] },
  { ruta: '/dashboard/calendar', permitidos: TODOS, marcadores: [...PANEL_ADMIN, 'page:Calendar'] },
  { ruta: '/dashboard/waitlist', permitidos: TODOS, marcadores: [...PANEL_ADMIN, 'page:Waitlist'] },
  {
    ruta: '/dashboard/reports',
    permitidos: ADMIN_SUPER_PRO,
    marcadores: [...PANEL_ADMIN, 'page:Reports']
  },
  {
    ruta: '/dashboard/payments',
    // Sin el profesional: el backend le niega la conciliacion, la cola de
    // envios y las devoluciones (FF-21, D-20260930-01).
    permitidos: ADMIN_SUPER,
    marcadores: [...PANEL_ADMIN, 'boundary:Payments are temporarily unavailable', 'page:Payments']
  },
  {
    ruta: '/dashboard/collections',
    permitidos: ADMIN_SUPER_PRO,
    marcadores: [...PANEL_ADMIN, 'page:Collections']
  },
  {
    ruta: '/dashboard/promotions',
    permitidos: ADMIN_SUPER,
    marcadores: [...PANEL_ADMIN, 'page:Promotions']
  },
  {
    ruta: '/dashboard/ledger',
    permitidos: ADMIN_SUPER_PRO,
    marcadores: [...PANEL_ADMIN, 'page:Ledger']
  },
  {
    ruta: '/dashboard/services',
    permitidos: ADMIN_SUPER,
    marcadores: [...PANEL_ADMIN, 'page:Services']
  },
  { ruta: '/dashboard/staff', permitidos: ADMIN_SUPER, marcadores: [...PANEL_ADMIN, 'page:Staff'] },
  { ruta: '/dashboard/users', permitidos: ADMIN_SUPER, marcadores: [...PANEL_ADMIN, 'page:Users'] },
  {
    ruta: '/dashboard/settings',
    permitidos: ADMIN_SUPER,
    marcadores: [...PANEL_ADMIN, 'page:Settings']
  },
  {
    ruta: '/dashboard/superadmin',
    permitidos: SUPER,
    marcadores: PANEL_GLOBAL,
    destino: '/control-global'
  },
  { ruta: '/control-global', permitidos: SUPER, marcadores: PANEL_GLOBAL }
]

// Quien no pasa la guarda de una ruta cae en su pantalla de inicio.
const INICIO_PANEL = { ruta: '/dashboard', marcadores: [...PANEL_ADMIN, 'page:Dashboard'] }

const CASOS_PANEL = RUTAS_PANEL.flatMap((r) =>
  TODOS.map((sesion) => ({ ...r, sesion, permitido: r.permitidos.includes(sesion) }))
)

const CASOS_INICIO = TODOS.map((sesion) => ({
  sesion,
  destino: SUPER.includes(sesion) ? '/control-global' : '/dashboard'
}))

const RUTAS_DE_LA_SESION = [
  { ruta: '/login', marcadores: ['auth', 'page:Login'] },
  { ruta: '/forgot-password', marcadores: ['auth', 'page:ForgotPassword'] },
  { ruta: '/reset-password', marcadores: ['auth', 'page:ResetPassword'] }
]

const RUTAS_PUBLICAS = [
  { ruta: '/legal/terminos', marcadores: ['page:Legal'], destino: '/legal/terminos' },
  { ruta: '/legal', marcadores: ['page:Legal'], destino: '/legal/terminos' },
  { ruta: '/booking/mi-tienda', marcadores: [BOUNDARY_BOOKING, 'page:PublicBooking'] },
  { ruta: '/b/mi-tienda', marcadores: [BOUNDARY_BOOKING, 'page:PublicBooking'] },
  { ruta: '/booking/mi-tienda/mis-turnos', marcadores: ['page:ClientAppointments'] },
  { ruta: '/b/mi-tienda/mis-turnos', marcadores: ['page:ClientAppointments'] }
]

const sinSesion = (): EstadoAuth => ({
  token: null,
  user: null,
  isLoading: false,
  isReconnecting: false,
  sessionUnavailable: false,
  retrySession: jest.fn()
})

const conSesion = (nombre: NombreSesion): EstadoAuth => ({
  ...sinSesion(),
  token: 'token',
  user: SESIONES[nombre]
})

const marcadores = () => screen.queryAllByTestId('marker').map((el) => el.textContent)

const abrir = (ruta: string) => {
  window.history.pushState({}, '', ruta)
  render(<App />)
}

const esperar = async (pathname: string, esperados: string[]) => {
  await waitFor(() => {
    expect(marcadores()).toEqual(esperados)
    expect(window.location.pathname).toBe(pathname)
  })
}

beforeEach(() => {
  mockAuth = sinSesion()
})

afterEach(() => {
  cleanup()
  window.history.pushState({}, '', '/')
})

describe('rutas del panel por rol', () => {
  it.each(CASOS_PANEL)('$ruta con $sesion (permitido: $permitido)', async (caso) => {
    mockAuth = conSesion(caso.sesion)
    abrir(caso.ruta)

    if (caso.permitido) {
      await esperar(caso.destino ?? caso.ruta, caso.marcadores)
    } else {
      await esperar(INICIO_PANEL.ruta, INICIO_PANEL.marcadores)
    }
  })
})

describe('rutas del panel sin sesion', () => {
  it.each(RUTAS_PANEL)('$ruta manda a /login y recuerda adonde iba', async ({ ruta }) => {
    abrir(`${ruta}?semana=2`)

    await esperar('/login', ['auth', 'page:Login'])
    expect(window.history.state?.usr).toEqual({ from: `${ruta}?semana=2` })
  })

  it('con la sesion cargandose muestra "Cargando..." y no redirige', () => {
    mockAuth = { ...sinSesion(), isLoading: true }
    abrir('/dashboard/reports')

    expect(screen.getByRole('status')).toHaveTextContent('Cargando...')
    expect(marcadores()).toEqual(['auth'])
    expect(window.location.pathname).toBe('/dashboard/reports')
  })

  it.each(['/dashboard', '/dashboard/reports', '/control-global', '/'])(
    'con la sesion no verificable (%s) ofrece reintentar y no manda a /login',
    async (ruta) => {
      mockAuth = { ...sinSesion(), sessionUnavailable: true }
      abrir(ruta)

      expect(await screen.findByRole('alert')).toHaveTextContent('Tu sesión sigue abierta.')
      expect(marcadores()).toEqual(['auth'])
      expect(window.location.pathname).toBe(ruta)
    }
  )
})

describe('rutas dentro del arbol de sesion, abiertas', () => {
  it.each(RUTAS_DE_LA_SESION)('$ruta sin sesion', async ({ ruta, marcadores: esperados }) => {
    abrir(ruta)

    await esperar(ruta, esperados)
  })

  it.each(RUTAS_DE_LA_SESION)('$ruta con sesion no redirige', async (caso) => {
    mockAuth = conSesion('store_admin')
    abrir(caso.ruta)

    await esperar(caso.ruta, caso.marcadores)
  })
})

describe('raiz y comodin', () => {
  it.each(['/', '/register', '/dashboard/no-existe-2', '/cualquier/cosa'])(
    'sin sesion %s va al login sin recordar la ruta',
    async (ruta) => {
      abrir(ruta)

      await esperar('/login', ['auth', 'page:Login'])
      expect(window.history.state?.usr ?? null).toBeNull()
    }
  )

  describe.each(['/', '/register', '/cualquier/cosa'])('con sesion %s', (ruta) => {
    it.each(CASOS_INICIO)('$sesion va a $destino', async ({ sesion, destino }) => {
      mockAuth = conSesion(sesion)
      abrir(ruta)

      await esperar(
        destino,
        destino === '/control-global' ? PANEL_GLOBAL : [...PANEL_ADMIN, 'page:Dashboard']
      )
    })
  })

  it('con token y sin usuario cargado va al panel', async () => {
    mockAuth = { ...sinSesion(), token: 'token' }
    abrir('/')

    await esperar('/dashboard', [...PANEL_ADMIN, 'page:Dashboard'])
  })

  it('una ruta desconocida bajo /dashboard cae en el comodin, no en el panel', async () => {
    mockAuth = conSesion('professional')
    abrir('/dashboard/no-existe')

    await esperar('/dashboard', [...PANEL_ADMIN, 'page:Dashboard'])
  })
})

describe('portal publico: fuera del AuthProvider', () => {
  it.each(RUTAS_PUBLICAS)('$ruta sin sesion', async (caso) => {
    abrir(caso.ruta)

    await esperar(caso.destino ?? caso.ruta, caso.marcadores)
  })

  it.each(RUTAS_PUBLICAS)('$ruta con sesion no la usa ni redirige', async (caso) => {
    mockAuth = conSesion('store_admin')
    abrir(caso.ruta)

    await esperar(caso.destino ?? caso.ruta, caso.marcadores)
  })
})

describe('banner de reconexion', () => {
  it('aparece en el panel', async () => {
    mockAuth = { ...conSesion('store_admin'), isReconnecting: true }
    abrir('/dashboard')

    expect(await screen.findByText('Reconectando...')).toBeInTheDocument()
  })

  it('no existe en el portal publico', async () => {
    mockAuth = { ...conSesion('store_admin'), isReconnecting: true }
    abrir('/booking/mi-tienda')

    await esperar('/booking/mi-tienda', [BOUNDARY_BOOKING, 'page:PublicBooking'])
    expect(screen.queryByText('Reconectando...')).not.toBeInTheDocument()
  })
})
