import React, { Suspense, lazy } from 'react'

import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router'

import { Sentry } from './infrastructure/observability/sentry'
import { ErrorBoundaryFallback } from './presentation/components/error-boundary'
import { AuthProvider, useAuth } from './presentation/context/AuthContext'
import { getDefaultAppRoute, hasAnyRole } from './presentation/context/roles'
import { PUBLIC_ROUTES, SESSION_ROUTES, type AppRoute } from './presentation/routes/appRoutes'

const NotFoundPage = lazy(() => import('./presentation/pages/NotFound'))

const ModuleBoundary = ({ children, title }: { children: React.ReactNode; title: string }) => (
  <Sentry.ErrorBoundary
    fallback={
      <ErrorBoundaryFallback
        title={title}
        description="This section could not be loaded safely. Please refresh and try again."
      />
    }
  >
    {children}
  </Sentry.ErrorBoundary>
)

const Loading = () => (
  <div role="status" aria-live="polite">
    Cargando...
  </div>
)

/**
 * La sesion no se pudo validar por una falla transitoria (red, 429, 503):
 * no es un logout, asi que no se manda a /login (D-20260928-03).
 */
const SessionUnavailable = () => {
  const { retrySession } = useAuth()
  return (
    <div role="alert" className="min-h-screen flex flex-col items-center justify-center gap-4">
      <p>No pudimos conectar con el servidor. Tu sesión sigue abierta.</p>
      <button type="button" onClick={retrySession} className="underline">
        Reintentar
      </button>
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

  if (isLoading) return <Loading />
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

  if (isLoading) return <Loading />
  if (!token && sessionUnavailable) return <SessionUnavailable />
  if (!token) return <Navigate to="/login" replace />

  return <Navigate to={getDefaultAppRoute(user?.role, user?.is_global_admin)} replace />
}

const ReconnectingBanner = () => {
  const { isReconnecting } = useAuth()
  if (!isReconnecting) return null
  return (
    <div role="status" aria-live="polite" className="fixed top-0 inset-x-0 z-50 text-center">
      Reconectando...
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
      <Suspense
        fallback={
          <div
            className="min-h-screen flex items-center justify-center"
            role="status"
            aria-live="polite"
          >
            Cargando...
          </div>
        }
      >
        <Routes>
          <Route element={<AuthLayout />}>
            {SESSION_ROUTES.map(renderRoute)}
            <Route path="/" element={<RootRedirect />} />
          </Route>
          {/* Portal publico: sin AuthProvider (D-20260928-04). */}
          {PUBLIC_ROUTES.map(renderRoute)}
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
