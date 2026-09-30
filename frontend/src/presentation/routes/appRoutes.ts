import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

import { ROLES_ADMIN_SUPER, ROLES_ADMIN_SUPER_PRO, ROLES_SUPER } from '../context/roles'

/**
 * Tabla de rutas de la app (F12-06). `App.tsx` la recorre; aca solo hay datos.
 * Cada `lazy(() => import(...))` queda literal: Vite parte los chunks por el
 * `import()` y `main.tsx` / F4-14 dependen de esos chunks.
 */

/**
 * - `'authenticated'`: cualquier usuario con sesion (sin filtrar rol).
 * - lista: solo esos roles; el resto vuelve a su pantalla de inicio.
 * - ausente: sin guarda.
 */
type RouteAccess = 'authenticated' | readonly string[]

type RouteTarget = { page: LazyExoticComponent<ComponentType> } | { redirectTo: string }

export type AppRoute = RouteTarget & {
  path?: string
  index?: true
  access?: RouteAccess
  /** Titulo del `ModuleBoundary` que envuelve la ruta. */
  boundary?: string
  children?: AppRoute[]
}

const LoginPage = lazy(() => import('../pages/Login'))
const ForgotPasswordPage = lazy(() => import('../pages/ForgotPassword'))
const ResetPasswordPage = lazy(() => import('../pages/ResetPassword'))
const AdminLayout = lazy(() => import('../layouts/AdminLayout'))
const SuperAdminLayout = lazy(() => import('../layouts/SuperAdminLayout'))
const Dashboard = lazy(() => import('../pages/Dashboard'))
const CalendarPage = lazy(() => import('../pages/Calendar'))
const ReportsPage = lazy(() => import('../pages/Reports'))
const PaymentsPage = lazy(() => import('../pages/Payments'))
const CollectionsPage = lazy(() => import('../pages/Collections'))
const PromotionsPage = lazy(() => import('../pages/Promotions'))
const LedgerPage = lazy(() => import('../pages/Ledger'))
const ServicesPage = lazy(() => import('../pages/Services'))
const StaffPage = lazy(() => import('../pages/Staff'))
const WaitlistPage = lazy(() => import('../pages/Waitlist'))
const SuperAdminPage = lazy(() => import('../pages/SuperAdmin'))
const UsersPage = lazy(() => import('../pages/Users'))
const PublicBookingPage = lazy(() => import('../pages/PublicBooking'))
const ClientAppointmentsPage = lazy(() => import('../pages/ClientAppointments'))
const SettingsPage = lazy(() => import('../pages/Settings'))
const LegalPage = lazy(() => import('../pages/Legal'))
const ManualPage = lazy(() => import('../pages/Manual'))

const BOOKING_BOUNDARY = 'Booking is temporarily unavailable'

/** Rutas dentro del `AuthProvider` (panel y pantallas de sesion). */
export const SESSION_ROUTES: AppRoute[] = [
  { path: '/login', page: LoginPage },
  { path: '/forgot-password', page: ForgotPasswordPage },
  { path: '/reset-password', page: ResetPasswordPage },
  {
    path: '/dashboard',
    page: AdminLayout,
    access: 'authenticated',
    boundary: 'The admin area is temporarily unavailable',
    children: [
      { index: true, page: Dashboard },
      { path: 'manual', page: ManualPage },
      { path: 'calendar', page: CalendarPage },
      { path: 'waitlist', page: WaitlistPage },
      { path: 'reports', page: ReportsPage, access: ROLES_ADMIN_SUPER_PRO },
      {
        path: 'payments',
        page: PaymentsPage,
        access: ROLES_ADMIN_SUPER_PRO,
        boundary: 'Payments are temporarily unavailable'
      },
      { path: 'collections', page: CollectionsPage, access: ROLES_ADMIN_SUPER_PRO },
      { path: 'promotions', page: PromotionsPage, access: ROLES_ADMIN_SUPER },
      { path: 'ledger', page: LedgerPage, access: ROLES_ADMIN_SUPER_PRO },
      { path: 'services', page: ServicesPage, access: ROLES_ADMIN_SUPER },
      { path: 'staff', page: StaffPage, access: ROLES_ADMIN_SUPER },
      { path: 'superadmin', redirectTo: '/control-global', access: ROLES_SUPER },
      { path: 'users', page: UsersPage, access: ROLES_ADMIN_SUPER },
      { path: 'settings', page: SettingsPage, access: ROLES_ADMIN_SUPER }
    ]
  },
  {
    path: '/control-global',
    page: SuperAdminLayout,
    access: ROLES_SUPER,
    boundary: 'Global control is temporarily unavailable',
    children: [{ index: true, page: SuperAdminPage }]
  }
]

/** Portal publico: sin `AuthProvider` (D-20260928-04). */
export const PUBLIC_ROUTES: AppRoute[] = [
  { path: '/legal/:document', page: LegalPage },
  { path: '/legal', redirectTo: '/legal/terminos' },
  { path: '/booking/:slug', page: PublicBookingPage, boundary: BOOKING_BOUNDARY },
  { path: '/b/:slug/mis-turnos', page: ClientAppointmentsPage },
  { path: '/booking/:slug/mis-turnos', page: ClientAppointmentsPage },
  { path: '/b/:slug', page: PublicBookingPage, boundary: BOOKING_BOUNDARY }
]
