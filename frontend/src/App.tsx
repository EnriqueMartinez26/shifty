import React, { Suspense, lazy } from 'react'

import { Loader2 } from 'lucide-react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router'

import { Sentry } from './infrastructure/observability/sentry'
import { ErrorBoundaryFallback } from './presentation/components/error-boundary'
import { LoadingScreen } from './presentation/components/molecules/LoadingScreen'
import { AuthShell } from './presentation/components/organisms/AuthShell'
import { AuthProvider, useAuth } from './presentation/context/AuthContext'
import { getDefaultAppRoute, hasAnyRole } from './presentation/context/roles'
import { PUBLIC_ROUTES, SESSION_ROUTES, type AppRoute } from './presentation/routes/appRoutes'
import { buttonStyles2000s, colors2000s } from './theme/colors'

const NotFoundPage = lazy(() => import('./presentation/pages/NotFound'))
// Link de baja del mail promocional (`modules/legal/unsubscribe.py`). Vive
// aca y no en la tabla de rutas, como el 404: es publica y sin sesion.
const UnsubscribePage = lazy(() => import('./presentation/pages/Unsubscribe'))

const ModuleBoundary = ({ children, title }: { children: React.ReactNode; title: string }) => (
  <Sentry.ErrorBoundary
    fallback={
      <ErrorBoundaryFallback
        title={title}
        description="No pudimos cargar esta sección. Actualizá la página y probá de nuevo."
      />
    }
  >
    {children}
  </Sentry.ErrorBoundary>
)

/**
 * La sesion no se pudo validar por una falla transitoria (red, 429, 503):
 * no es un logout, asi que no se manda a /login (D-20260928-03).
 */
const SessionUnavailable = () => {
  const { retrySession } = useAuth()
  return (
    <div role="alert">
      <AuthShell title="Sin conexión" subtitle="No pudimos conectar con el servidor.">
        <div className="space-y-4">
          <p
            className="text-sm font-medium text-center"
            style={{ color: colors2000s.text.primary }}
          >
            Tu sesión sigue abierta.
          </p>
          <button
            type="button"
            onClick={retrySession}
            className="w-full font-bold py-4 rounded-2xl transition-all active:scale-[0.98]"
            style={buttonStyles2000s.selected}
          >
            Reintentar
          </button>
        </div>
      </AuthShell>
    </div>
  )
}

const ProtectedRoute = ({
  children,
  allowedRoles
}: {
  children: React.ReactNode
  allowedRoles?: readonly string[]
}) => {
  const { token, isLoading, user, sessionUnavailable } = useAuth()
  const { pathname, search } = useLocation()

  if (isLoading) return <LoadingScreen />
  if (!token && sessionUnavailable) return <SessionUnavailable />
  // Se recuerda adonde iba: el login vuelve ahi si es segura (FF-36).
  if (!token) return <Navigate to="/login" replace state={{ from: pathname + search }} />
  if (allowedRoles && user && !hasAnyRole(user.role, allowedRoles, user.is_global_admin)) {
    return <Navigate to={getDefaultAppRoute(user.role, user.is_global_admin)} replace />
  }

  return children
}

const RootRedirect = () => {
  const { token, isLoading, user, sessionUnavailable } = useAuth()

  if (isLoading) return <LoadingScreen />
  if (!token && sessionUnavailable) return <SessionUnavailable />
  if (!token) return <Navigate to="/login" replace />

  return <Navigate to={getDefaultAppRoute(user?.role, user?.is_global_admin)} replace />
}

const ReconnectingBanner = () => {
  const { isReconnecting } = useAuth()
  if (!isReconnecting) return null
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-3 inset-x-0 z-50 flex justify-center px-4 pointer-events-none"
    >
      <span
        className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-bold"
        style={{
          background: colors2000s.status.warning.bg,
          border: `1px solid ${colors2000s.status.warning.border}`,
          color: colors2000s.status.warning.text,
          boxShadow: colors2000s.shadows.outerMedium
        }}
      >
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
        Reconectando...
      </span>
    </div>
  )
}

/**
 * Sesion solo en el arbol autenticado (D-20260928-04): el portal publico
 * (/booking, /b, /legal) no monta AuthProvider y no hace un POST /auth/refresh
 * inutil en cada visita.
 */
const AuthLayout = () => (
  <AuthProvider>
    <ReconnectingBanner />
    <Outlet />
  </AuthProvider>
)

/**
 * Envuelve la pagina como lo hacia el JSX a mano: la guarda por fuera, el
 * `ModuleBoundary` por dentro.
 */
const routeElement = (route: AppRoute) => {
  const target = 'page' in route ? <route.page /> : <Navigate to={route.redirectTo} replace />
  const bounded = route.boundary ? (
    <ModuleBoundary title={route.boundary}>{target}</ModuleBoundary>
  ) : (
    target
  )
  if (!route.access) return bounded
  return (
    <ProtectedRoute allowedRoles={route.access === 'authenticated' ? undefined : route.access}>
      {bounded}
    </ProtectedRoute>
  )
}

const renderRoute = (route: AppRoute): React.ReactNode => {
  const element = routeElement(route)
  if (route.index) return <Route key="index" index element={element} />
  return (
    <Route key={route.path} path={route.path} element={element}>
      {route.children?.map(renderRoute)}
    </Route>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingScreen />}>
        <Routes>
          <Route element={<AuthLayout />}>
            {SESSION_ROUTES.map(renderRoute)}
            <Route path="/" element={<RootRedirect />} />
          </Route>
          {/* Portal publico: sin AuthProvider (D-20260928-04). */}
          {PUBLIC_ROUTES.map(renderRoute)}
          <Route path="/baja" element={<UnsubscribePage />} />
          {/* Cualquier ruta desconocida (p.ej. el viejo /register) es un 404
              propio, fuera del AuthProvider: no espera a la sesion y ofrece
              volver al inicio (o a la tienda, si la direccion es de una). */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
