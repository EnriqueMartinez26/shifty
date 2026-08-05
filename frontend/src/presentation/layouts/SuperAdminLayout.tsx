import React from 'react'

import { ArrowLeftRight, LogOut, ShieldCheck } from 'lucide-react'
import { Outlet } from 'react-router'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { useAuth } from '../context/AuthContext'

const SuperAdminLayout: React.FC = () => {
  const { logout, user } = useAuth()

  return (
    <div
      className="min-h-screen"
      style={{
        background: [
          'radial-gradient(circle at top right, rgba(30,64,175,0.10), transparent 28%)',
          `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`
        ].join(', '),
        color: colors2000s.text.primary
      }}
    >
      <header
        className="sticky top-0 z-40 border-b px-6 py-4 backdrop-blur"
        style={{
          background: 'rgba(245,245,245,0.92)',
          borderColor: colors2000s.border.default,
          boxShadow: colors2000s.shadows.outerMedium
        }}
      >
        <div className="mx-auto flex max-w-[1600px] flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div
              className="flex h-12 w-12 items-center justify-center rounded-2xl relative overflow-hidden"
              style={{
                background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                border: `1px solid ${colors2000s.orange.accent}`,
                boxShadow: colors2000s.shadows.outerOrange
              }}
            >
              <div className="absolute inset-x-0 top-0 h-1/2 bg-white/20 pointer-events-none" />
              <ShieldCheck className="h-6 w-6 text-white" />
            </div>

            <div>
              <div className="flex items-center gap-2">
                <span
                  className="text-xl font-black uppercase tracking-tight"
                  style={{ color: colors2000s.text.primary }}
                >
                  Shifty Platform
                </span>
                <span
                  className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-[0.18em]"
                  style={{
                    background: '#eff6ff',
                    border: '1px solid #bfdbfe',
                    color: '#1d4ed8'
                  }}
                >
                  Super Admin
                </span>
              </div>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                Control multi-tenant separado del backoffice de tienda.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div
              className="rounded-2xl px-4 py-3 text-xs font-bold"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.default}`,
                boxShadow: colors2000s.shadows.insetDark,
                color: colors2000s.text.secondary
              }}
            >
              Sesión: <span style={{ color: colors2000s.text.primary }}>{user?.email}</span>
            </div>

            <button
              type="button"
              onClick={logout}
              className="inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-[0.18em]"
              style={{
                ...buttonStyles2000s.default,
                background: 'rgba(239,68,68,0.05)',
                color: '#ef4444'
              }}
            >
              <LogOut className="h-4 w-4" />
              Salir
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-8">
        <div
          className="mb-6 flex items-center gap-3 rounded-[1.5rem] px-5 py-4"
          style={{
            background: 'rgba(255,255,255,0.72)',
            border: `1px solid ${colors2000s.border.light}`,
            boxShadow: colors2000s.shadows.outer
          }}
        >
          <ArrowLeftRight className="h-5 w-5" style={{ color: colors2000s.orange.accent }} />
          <p className="text-sm font-bold" style={{ color: colors2000s.text.secondary }}>
            Esta superficie administra dueños de tiendas y configuración SaaS global. No navega
            dentro de una tienda ni reutiliza el backoffice tenant.
          </p>
        </div>

        <Outlet />
      </main>
    </div>
  )
}

export default SuperAdminLayout
