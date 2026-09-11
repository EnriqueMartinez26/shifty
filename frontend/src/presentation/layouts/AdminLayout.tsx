import React, { useEffect, useState } from 'react'

import { Menu } from 'lucide-react'
import { Outlet } from 'react-router'

import { colors2000s } from '../../theme/colors'
import { SubscriptionBanner } from '../components/molecules/SubscriptionBanner'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import NotificationsBell from '../components/navigation/NotificationsBell'
import Sidebar from '../components/navigation/Sidebar'
import { useStoreSettings, useStoreSubscription } from '../hooks/useStores'

/** El chip del encabezado deja de mentir "En linea": refleja el plan. */
const ESTADO_DEL_PLAN: Record<string, { label: string; color: string }> = {
  suspended: { label: 'Suspendida', color: '#dc2626' },
  past_due: { label: 'Vencida', color: '#d97706' },
  cancelled: { label: 'Cancelada', color: '#6b7280' }
}

const DESKTOP_QUERY = '(min-width: 1024px)'

const AdminLayout: React.FC = () => {
  const { data: subscription } = useStoreSubscription()
  const { data: store } = useStoreSettings()
  const estadoDelPlan = (subscription && ESTADO_DEL_PLAN[subscription.status]) ?? {
    label: 'En línea',
    color: '#22c55e'
  }
  // El sidebar es fixed+off-canvas por debajo de `lg`; a partir de ahi queda
  // siempre visible y este estado no se lee (Sidebar fuerza lg:translate-x-0).
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  // Un elemento con `translate-x-full` sigue siendo tabulable aunque no se
  // vea: sin esto, un usuario de teclado con el drawer cerrado en mobile
  // podia tabular hacia links invisibles. `inert` los saca del arbol de
  // accesibilidad, pero solo cuando el drawer esta REALMENTE fuera de
  // pantalla (mobile + cerrado) - en desktop el sidebar siempre esta
  // visible y jamas debe quedar inert.
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches
  )

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_QUERY)
    const onChange = () => setIsDesktop(query.matches)
    onChange()
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!isSidebarOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsSidebarOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    // Bloquea el scroll de fondo mientras el drawer esta abierto, patron
    // estandar de menus off-canvas.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [isSidebarOpen])

  return (
    <div
      className="flex min-h-screen font-sans"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`,
        color: colors2000s.text.primary
      }}
    >
      {isSidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <Sidebar
        isOpen={isSidebarOpen}
        onNavigate={() => setIsSidebarOpen(false)}
        inert={!isSidebarOpen && !isDesktop}
      />

      <main className="flex-1 lg:ml-64 p-4 sm:p-6 lg:p-8 min-w-0">
        <header className="mb-6 lg:mb-10 flex flex-wrap justify-between items-center gap-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setIsSidebarOpen(true)}
              aria-label="Abrir menu de navegacion"
              className="lg:hidden p-2.5 rounded-xl flex-shrink-0"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.default}`,
                boxShadow: colors2000s.shadows.insetDark,
                color: colors2000s.text.primary
              }}
            >
              <Menu size={20} />
            </button>
            <div>
              <h1
                className="text-xl sm:text-2xl font-bold tracking-tight mb-1"
                style={{ color: colors2000s.orange.accent }}
              >
                Bienvenido de nuevo
              </h1>
              <p className="text-sm" style={{ color: colors2000s.text.secondary }}>
                Gestioná tus turnos, clientes y equipo en Shifty.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <NotificationsBell />
            <div
              className="rounded-xl px-4 py-2 text-sm font-bold"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.default}`,
                boxShadow: colors2000s.shadows.insetDark,
                color: colors2000s.text.secondary
              }}
            >
              Estado: <span style={{ color: estadoDelPlan.color }}>{estadoDelPlan.label}</span>
            </div>
          </div>
        </header>

        <SubscriptionBanner subscription={subscription} storeName={store?.name} />

        <div className="relative animate-in fade-in duration-500">
          <Outlet />
        </div>

        <footer
          className="mt-12 pt-6"
          style={{ borderTop: `1px solid ${colors2000s.border.light}` }}
        >
          <LegalFooterLinks />
        </footer>
      </main>
    </div>
  )
}

export default AdminLayout
