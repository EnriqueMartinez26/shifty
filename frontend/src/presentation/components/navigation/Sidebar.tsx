import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  mdiAccountGroup,
  mdiBriefcase,
  mdiCashClock,
  mdiCalendar,
  mdiChartBar,
  mdiChevronRight,
  mdiCog,
  mdiCreditCardOutline,
  mdiLogout,
  mdiShieldCheck,
  mdiStore,
  mdiTagOutline,
  mdiViewDashboard,
  mdiWalletOutline
} from '@mdi/js'

import { Icon2000s } from '../legacy/Icon2000s'
import { useAuth } from '../../context/AuthContext'
import {
  ROLE_PROFESSIONAL,
  ROLE_RECEPTIONIST,
  ROLE_STORE_ADMIN,
  ROLE_SUPER_ADMIN,
  hasAnyRole
} from '../../context/roles'
import { buttonStyles2000s, colors2000s } from '../../../theme/colors'

type MenuItem = {
  iconPath: string
  label: string
  path: string
  roles: string[]
}

const menuItems: MenuItem[] = [
  {
    iconPath: mdiViewDashboard,
    label: 'Dashboard',
    path: '/dashboard',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL, ROLE_RECEPTIONIST]
  },
  {
    iconPath: mdiCalendar,
    label: 'Agenda',
    path: '/dashboard/calendar',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL, ROLE_RECEPTIONIST]
  },
  {
    iconPath: mdiChartBar,
    label: 'Reportes',
    path: '/dashboard/reports',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]
  },
  {
    iconPath: mdiCreditCardOutline,
    label: 'Cobros online',
    path: '/dashboard/payments',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]
  },
  {
    iconPath: mdiCashClock,
    label: 'Cobros',
    path: '/dashboard/collections',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]
  },
  {
    iconPath: mdiTagOutline,
    label: 'Promociones',
    path: '/dashboard/promotions',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]
  },
  {
    iconPath: mdiWalletOutline,
    label: 'Cuentas pendientes',
    path: '/dashboard/ledger',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN, ROLE_PROFESSIONAL]
  },
  {
    iconPath: mdiShieldCheck,
    label: 'Usuarios',
    path: '/dashboard/users',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]
  },
  {
    iconPath: mdiBriefcase,
    label: 'Servicios',
    path: '/dashboard/services',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]
  },
  {
    iconPath: mdiAccountGroup,
    label: 'Personal',
    path: '/dashboard/staff',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]
  },
  {
    iconPath: mdiCog,
    label: 'Configuración',
    path: '/dashboard/settings',
    roles: [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN]
  }
]

const Sidebar: React.FC = () => {
  const location = useLocation()
  const { logout, user } = useAuth()
  const visibleItems = menuItems.filter((item) =>
    hasAnyRole(user?.role, item.roles, user?.is_global_admin)
  )

  return (
    <aside
      className="w-64 h-screen flex flex-col fixed left-0 top-0 z-50"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        borderRight: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.outerMedium
      }}
    >
      <div className="p-6 flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center relative overflow-hidden"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
            boxShadow: colors2000s.shadows.outerOrange,
            border: `1px solid ${colors2000s.orange.accent}`
          }}
        >
          <div className="absolute top-0 left-0 right-0 h-1/2 bg-white/20 pointer-events-none" />
          <Icon2000s path={mdiStore} size={20} variant="active" />
        </div>
        <div>
          <h2
            className="font-black leading-none mb-1 uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Shifty
          </h2>
          <span
            className="text-[10px] uppercase tracking-wider font-bold"
            style={{ color: colors2000s.text.secondary }}
          >
            Admin Panel
          </span>
        </div>
      </div>

      <nav className="flex-1 px-4 py-6 space-y-1 overflow-y-auto">
        {visibleItems.map((item) => {
          const isActive = location.pathname === item.path
          const linkStyle = isActive
            ? buttonStyles2000s.selected
            : {
                ...buttonStyles2000s.default,
                background: 'transparent',
                border: '1px solid transparent',
                boxShadow: 'none'
              }

          return (
            <Link
              key={item.path}
              to={item.path}
              className="flex items-center justify-between px-4 py-3 rounded-xl transition-all group"
              style={linkStyle}
              onMouseEnter={(e) => {
                if (!isActive) {
                  Object.assign(e.currentTarget.style, buttonStyles2000s.hover)
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  Object.assign(e.currentTarget.style, {
                    background: 'transparent',
                    border: '1px solid transparent',
                    boxShadow: 'none',
                    color: colors2000s.text.primary
                  })
                }
              }}
            >
              <div className="flex items-center gap-3">
                <Icon2000s path={item.iconPath} size={20} variant={isActive ? 'active' : 'idle'} />
                <span
                  className="font-bold text-sm"
                  style={{ color: isActive ? colors2000s.text.onOrange : colors2000s.text.primary }}
                >
                  {item.label}
                </span>
              </div>
              {isActive && <Icon2000s path={mdiChevronRight} size={16} variant="active" />}
            </Link>
          )
        })}
      </nav>

      <div className="p-4 mt-auto" style={{ borderTop: `1px solid ${colors2000s.border.light}` }}>
        <div
          className="flex items-center gap-3 p-3 mb-4 rounded-xl"
          style={{
            background: 'white',
            boxShadow: colors2000s.shadows.insetDark,
            border: `1px solid ${colors2000s.border.light}`
          }}
        >
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center font-black text-xs uppercase flex-shrink-0"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.disabledBottom} 100%)`,
              color: colors2000s.text.secondary,
              border: `1px solid ${colors2000s.border.default}`,
              boxShadow: colors2000s.shadows.insetLight
            }}
          >
            {user?.first_name?.[0] || user?.email?.[0]}
          </div>
          <div className="flex-1 min-w-0">
            <p
              className="text-sm font-black truncate uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {user?.first_name || 'Usuario'}
            </p>
            <p
              className="text-[10px] truncate font-bold"
              style={{ color: colors2000s.text.secondary }}
            >
              {user?.email}
            </p>
          </div>
        </div>

        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-bold group"
          style={{
            ...buttonStyles2000s.default,
            background: 'rgba(239,68,68,0.05)',
            color: '#ef4444'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(239,68,68,0.12)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(239,68,68,0.05)'
          }}
        >
          <Icon2000s
            path={mdiLogout}
            size={18}
            variant="idle"
            color="#ef4444"
            style={{
              filter: [
                'drop-shadow(0 1px 0 rgba(255,255,255,0.6))',
                'drop-shadow(0 1px 2px rgba(239,68,68,0.2))'
              ].join(' ')
            }}
          />
          <span>Cerrar sesión</span>
        </button>
      </div>
    </aside>
  )
}

export default Sidebar
