import React from 'react'

import { Outlet } from 'react-router-dom'

import { colors2000s } from '../../theme/colors'
import Sidebar from '../components/navigation/Sidebar'

const AdminLayout: React.FC = () => {
  return (
    <div
      className="flex min-h-screen font-sans"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`,
        color: colors2000s.text.primary
      }}
    >
      <Sidebar />

      <main className="flex-1 ml-64 p-8">
        <header className="mb-10 flex justify-between items-center">
          <div>
            <h1
              className="text-2xl font-bold tracking-tight mb-1"
              style={{ color: colors2000s.orange.accent }}
            >
              Bienvenido de nuevo
            </h1>
            <p className="text-sm" style={{ color: colors2000s.text.secondary }}>
              Gestioná tus turnos, clientes y equipo en Shifty.
            </p>
          </div>

          <div className="flex items-center gap-4">
            <div
              className="rounded-xl px-4 py-2 text-sm font-bold"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.default}`,
                boxShadow: colors2000s.shadows.insetDark,
                color: colors2000s.text.secondary
              }}
            >
              Estado: <span style={{ color: '#22c55e' }}>En línea</span>
            </div>
          </div>
        </header>

        <div className="relative animate-in fade-in duration-500">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

export default AdminLayout
