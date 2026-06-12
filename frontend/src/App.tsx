import React, { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider, useAuth } from './presentation/context/AuthContext'
import {
  ROLE_PROFESSIONAL,
  ROLE_STORE_ADMIN,
  ROLE_SUPER_ADMIN,
  getDefaultAppRoute,
  hasAnyRole
} from './presentation/context/roles'

const LoginPage = lazy(() => import('./presentation/pages/Login'))
const RegisterPage = lazy(() => import('./presentation/pages/Register'))
const ForgotPasswordPage = lazy(() => import('./presentation/pages/ForgotPassword'))
const ResetPasswordPage = lazy(() => import('./presentation/pages/ResetPassword'))
const AdminLayout = lazy(() => import('./presentation/layouts/AdminLayout'))
const SuperAdminLayout = lazy(() => import('./presentation/layouts/SuperAdminLayout'))
const Dashboard = lazy(() => import('./presentation/pages/Dashboard'))
const CalendarPage = lazy(() => import('./presentation/pages/Calendar'))
const ReportsPage = lazy(() => import('./presentation/pages/Reports'))
const PaymentsPage = lazy(() => import('./presentation/pages/Payments'))
const CollectionsPage = lazy(() => import('./presentation/pages/Collections'))
const PromotionsPage = lazy(() => import('./presentation/pages/Promotions'))
const LedgerPage = lazy(() => import('./presentation/pages/Ledger'))
const ServicesPage = lazy(() => import('./presentation/pages/Services'))
const StaffPage = lazy(() => import('./presentation/pages/Staff'))
const SuperAdminPage = lazy(() => import('./presentation/pages/SuperAdmin'))
const UsersPage = lazy(() => import('./presentation/pages/Users'))
const PublicBookingPage = lazy(() => import('./presentation/pages/PublicBooking'))
const SettingsPage = lazy(() => import('./presentation/pages/Settings'))

const ProtectedRoute = ({
  children,
  allowedRoles
}: {
  children: React.ReactNode
  allowedRoles?: string[]
}) => {
  const { token, isLoading, user } = useAuth()

  if (isLoading) return <div>Cargando...</div>
  if (!token) return <Navigate to="/login" replace />
  if (allowedRoles && user && !hasAnyRole(user.role, allowedRoles, user.is_global_admin)) {
    return <Navigate to={getDefaultAppRoute(user.role, user.is_global_admin)} replace />
  }

  return children
}

const RootRedirect = () => {
  const { token, isLoading, user } = useAuth()

  if (isLoading) return <div>Cargando...</div>
  if (!token) return <Navigate to="/login" replace />

  return <Navigate to={getDefaultAppRoute(user?.role, user?.is_global_admin)} replace />
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense
          fallback={
            <div className="min-h-screen flex items-center justify-center">Cargando...</div>
          }
        >
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <AdminLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="calendar" element={<CalendarPage />} />
              <Route
                path="reports"
                element={
                  <ProtectedRoute
                    allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]}
                  >
                    <ReportsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="payments"
                element={
                  <ProtectedRoute
                    allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]}
                  >
                    <PaymentsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="collections"
                element={
                  <ProtectedRoute
                    allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]}
                  >
                    <CollectionsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="promotions"
                element={
                  <ProtectedRoute allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]}>
                    <PromotionsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="ledger"
                element={
                  <ProtectedRoute
                    allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]}
                  >
                    <LedgerPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="services"
                element={
                  <ProtectedRoute allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]}>
                    <ServicesPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="staff"
                element={
                  <ProtectedRoute allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]}>
                    <StaffPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="superadmin"
                element={
                  <ProtectedRoute allowedRoles={[ROLE_SUPER_ADMIN]}>
                    <Navigate to="/control-global" replace />
                  </ProtectedRoute>
                }
              />
              <Route
                path="users"
                element={
                  <ProtectedRoute allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]}>
                    <UsersPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="settings"
                element={
                  <ProtectedRoute allowedRoles={[ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]}>
                    <SettingsPage />
                  </ProtectedRoute>
                }
              />
            </Route>
            <Route path="/booking/:slug" element={<PublicBookingPage />} />
            <Route path="/b/:slug" element={<PublicBookingPage />} />
            <Route
              path="/control-global"
              element={
                <ProtectedRoute allowedRoles={[ROLE_SUPER_ADMIN]}>
                  <SuperAdminLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<SuperAdminPage />} />
            </Route>
            <Route path="/" element={<RootRedirect />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
