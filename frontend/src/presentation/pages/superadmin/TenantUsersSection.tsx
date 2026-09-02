import React from 'react'

import { BadgeCheck, Loader2, Shield, Users } from 'lucide-react'

import type {
  SuperAdminStoreOverview,
  SuperAdminStoreRow,
  SuperAdminUser
} from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { MiniButton } from '../SuperAdminUi'
import {
  emptyStateStyle,
  innerCardStyle,
  panelStyle,
  roleLabel,
  scopeBadgeStyle,
  type QueryState
} from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface TenantUsersSectionProps {
  selectedStore: SuperAdminStoreRow | null
  overview: SuperAdminStoreOverview | undefined
  overviewQuery: QueryState<SuperAdminStoreOverview>
  openEditUserModal: (targetUser: SuperAdminUser) => void
  toggleUserActive: (targetUser: SuperAdminUser) => Promise<void>
  toggleGlobalAdmin: (targetUser: SuperAdminUser) => Promise<void>
}

export const TenantUsersSection: React.FC<TenantUsersSectionProps> = ({
  selectedStore,
  overview,
  overviewQuery,
  openEditUserModal,
  toggleUserActive,
  toggleGlobalAdmin
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="mb-4 flex items-center justify-between">
      <div>
        <span
          className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
          style={scopeBadgeStyle('tenant')}
        >
          Admins y Usuarios
        </span>
        <h2
          className="mt-2 text-xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Detalle del tenant
        </h2>
      </div>
      {overviewQuery.isFetching ? (
        <Loader2 className="h-4 w-4 animate-spin" style={{ color: colors2000s.orange.accent }} />
      ) : null}
    </div>

    {!overview && overviewQuery.isLoading ? (
      <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
        <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin" />
        <p
          className="text-sm font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.primary }}
        >
          Cargando contexto
        </p>
      </div>
    ) : overview ? (
      <div className="space-y-4">
        {!selectedStore?.is_active ? (
          <div
            className="rounded-[1.5rem] px-4 py-3 text-xs font-bold"
            style={scopeBadgeStyle('danger')}
          >
            Contexto de tienda inactiva. Crear admins, asignar planes y canjear cupones puede quedar
            bloqueado por reglas de backend.
          </div>
        ) : null}

        <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
          <div className="mb-3 flex items-center gap-2">
            <Shield className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
            <p
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Admins
            </p>
          </div>
          {overview.users.admins.length ? (
            <div className="space-y-3">
              {overview.users.admins.map((admin) => (
                <div
                  key={admin.public_id}
                  className="rounded-2xl p-3"
                  style={{ background: colors2000s.bg.button }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-black" style={{ color: colors2000s.text.primary }}>
                        {[admin.first_name, admin.last_name].filter(Boolean).join(' ') ||
                          admin.email}
                      </p>
                      <p
                        className="text-[10px] font-bold uppercase tracking-widest"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        {admin.email}
                      </p>
                    </div>
                    <span
                      className="rounded-full px-2 py-1 text-[10px] font-black uppercase tracking-widest"
                      style={
                        admin.is_global_admin
                          ? scopeBadgeStyle('danger')
                          : scopeBadgeStyle('tenant')
                      }
                    >
                      {roleLabel(admin.role, admin.is_global_admin)}
                    </span>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <MiniButton
                      label="Editar"
                      onClick={(event) => {
                        event.stopPropagation()
                        openEditUserModal(admin)
                      }}
                      tone="primary"
                    />
                    <MiniButton
                      label={admin.is_active ? 'Desactivar' : 'Activar'}
                      onClick={(event) => {
                        event.stopPropagation()
                        void toggleUserActive(admin)
                      }}
                      tone={admin.is_active ? 'danger' : 'default'}
                    />
                    <MiniButton
                      label={admin.is_global_admin ? 'Revocar SuperAdmin' : 'Promover SuperAdmin'}
                      onClick={(event) => {
                        event.stopPropagation()
                        void toggleGlobalAdmin(admin)
                      }}
                      tone={admin.is_global_admin ? 'danger' : 'default'}
                      disabled={!admin.is_global_admin && !admin.is_active}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-[1.25rem] p-6 text-center" style={emptyStateStyle}>
              <Shield className="mx-auto mb-3 h-8 w-8 opacity-25" />
              <p
                className="text-sm font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.primary }}
              >
                No hay admins creados
              </p>
            </div>
          )}
        </div>

        <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
          <div className="mb-3 flex items-center gap-2">
            <Users className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
            <p
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Usuarios
            </p>
          </div>
          <div className="mb-3 grid grid-cols-3 gap-2 text-center">
            {[
              { label: 'Admins', value: overview.users.admins_count },
              { label: 'Usuarios', value: overview.users.users_count },
              { label: 'Activos', value: overview.users.active_users_count }
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-2xl p-3"
                style={{ background: colors2000s.bg.button }}
              >
                <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>
                  {item.value}
                </p>
                <p
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {item.label}
                </p>
              </div>
            ))}
          </div>
          <div className="space-y-2">
            {overview.users.users.length ? (
              overview.users.users.map((tenantUser) => (
                <div
                  key={tenantUser.public_id}
                  className="rounded-2xl px-3 py-3"
                  style={{ background: colors2000s.bg.button }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                        {[tenantUser.first_name, tenantUser.last_name].filter(Boolean).join(' ') ||
                          tenantUser.email}
                      </p>
                      <p
                        className="text-[10px] font-bold uppercase tracking-widest"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        {roleLabel(tenantUser.role, tenantUser.is_global_admin)}
                      </p>
                    </div>
                    {tenantUser.is_global_admin ? (
                      <BadgeCheck className="h-4 w-4" style={{ color: '#be123c' }} />
                    ) : (
                      <span
                        className="text-[10px] font-black uppercase tracking-widest"
                        style={{ color: tenantUser.is_active ? '#15803d' : '#b91c1c' }}
                      >
                        {tenantUser.is_active ? 'Activo' : 'Inactivo'}
                      </span>
                    )}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <MiniButton
                      label="Editar"
                      onClick={(event) => {
                        event.stopPropagation()
                        openEditUserModal(tenantUser)
                      }}
                      tone="primary"
                    />
                    <MiniButton
                      label={tenantUser.is_active ? 'Desactivar' : 'Activar'}
                      onClick={(event) => {
                        event.stopPropagation()
                        void toggleUserActive(tenantUser)
                      }}
                      tone={tenantUser.is_active ? 'danger' : 'default'}
                    />
                    <MiniButton
                      label={
                        tenantUser.is_global_admin ? 'Revocar SuperAdmin' : 'Promover SuperAdmin'
                      }
                      onClick={(event) => {
                        event.stopPropagation()
                        void toggleGlobalAdmin(tenantUser)
                      }}
                      tone={tenantUser.is_global_admin ? 'danger' : 'default'}
                    />
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-[1.25rem] p-6 text-center" style={emptyStateStyle}>
                <Users className="mx-auto mb-3 h-8 w-8 opacity-25" />
                <p
                  className="text-sm font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.primary }}
                >
                  No hay usuarios del tenant
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    ) : (
      <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
        <Users className="mx-auto mb-3 h-10 w-10 opacity-25" />
        <p
          className="text-sm font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.primary }}
        >
          Selecciona una tienda
        </p>
      </div>
    )}
  </section>
)
