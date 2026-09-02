import React from 'react'

import { Building2, Filter, Loader2, Search } from 'lucide-react'

import type { SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { formatDateEsAr } from '../../lib/formatters'
import { create2000sInputStyle } from '../../lib/surfaceStyles'
import { MiniButton } from '../SuperAdminUi'
import {
  emptyStateStyle,
  innerCardStyle,
  panelStyle,
  scopeBadgeStyle,
  statusLabel,
  type ActivityFilter,
  type QueryState,
  type SubscriptionFilter
} from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface StoresSectionProps {
  search: string
  setSearch: React.Dispatch<React.SetStateAction<string>>
  activityFilter: ActivityFilter
  setActivityFilter: React.Dispatch<React.SetStateAction<ActivityFilter>>
  subscriptionFilter: SubscriptionFilter
  setSubscriptionFilter: React.Dispatch<React.SetStateAction<SubscriptionFilter>>
  selectedStoreId: string | null
  setSelectedStoreId: React.Dispatch<React.SetStateAction<string | null>>
  storesQuery: QueryState<SuperAdminStoreRow[]>
  openEditStoreFor: (store: SuperAdminStoreRow) => void
  toggleStoreActive: (store: SuperAdminStoreRow) => Promise<void>
}

export const StoresSection: React.FC<StoresSectionProps> = ({
  search,
  setSearch,
  activityFilter,
  setActivityFilter,
  subscriptionFilter,
  setSubscriptionFilter,
  selectedStoreId,
  setSelectedStoreId,
  storesQuery,
  openEditStoreFor,
  toggleStoreActive
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <span
            className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
            style={scopeBadgeStyle('global')}
          >
            Tiendas
          </span>
        </div>
        <h2
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Operacion por tenant
        </h2>
        <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          Filtros directos por estado y suscripcion para triage operativo rapido.
        </p>
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative">
          <Search
            className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2"
            style={{ color: colors2000s.text.disabled }}
          />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar por nombre o slug"
            className="w-full rounded-2xl py-3 pl-11 pr-4 text-sm font-bold outline-none md:w-72"
            style={create2000sInputStyle()}
          />
        </div>

        <div className="flex items-center gap-2 rounded-2xl p-2" style={innerCardStyle}>
          <Filter className="h-4 w-4" style={{ color: colors2000s.text.secondary }} />
          {[
            { value: 'active', label: 'Activas' },
            { value: 'inactive', label: 'Inactivas' },
            { value: 'all', label: 'Todas' }
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setActivityFilter(item.value as ActivityFilter)}
              className="rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
              style={
                activityFilter === item.value
                  ? buttonStyles2000s.selected
                  : buttonStyles2000s.default
              }
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 rounded-2xl p-2" style={innerCardStyle}>
          {[
            { value: 'all', label: 'Todas' },
            { value: 'with', label: 'Con suscripcion' },
            { value: 'without', label: 'Sin suscripcion' }
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setSubscriptionFilter(item.value as SubscriptionFilter)}
              className="rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
              style={
                subscriptionFilter === item.value
                  ? buttonStyles2000s.selected
                  : buttonStyles2000s.default
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </div>

    <div className="mt-6 overflow-hidden rounded-[1.75rem]" style={innerCardStyle}>
      {storesQuery.isLoading ? (
        <div
          className="flex items-center justify-center gap-3 p-10"
          style={{ color: colors2000s.text.secondary }}
        >
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="font-bold">Cargando tiendas...</span>
        </div>
      ) : storesQuery.data?.length ? (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left">
            <thead style={{ background: colors2000s.bg.disabled }}>
              <tr>
                {[
                  'Tienda',
                  'Estado',
                  'Recordatorios',
                  'Usuarios',
                  'Suscripcion',
                  'Renueva',
                  'Acciones'
                ].map((label) => (
                  <th
                    key={label}
                    className="px-4 py-3 text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {storesQuery.data.map((store) => {
                const isSelected = store.public_id === selectedStoreId
                return (
                  <tr
                    key={store.public_id}
                    onClick={() => setSelectedStoreId(store.public_id)}
                    className="cursor-pointer transition-colors"
                    style={{
                      background: isSelected ? '#fff7ed' : 'transparent',
                      borderTop: `1px solid ${colors2000s.border.light}`
                    }}
                  >
                    <td className="px-4 py-4">
                      <div className="flex items-center gap-3">
                        <span
                          className="h-4 w-4 rounded-full border"
                          style={{
                            background: store.primary_color,
                            borderColor: colors2000s.border.default
                          }}
                        />
                        <div>
                          <p className="font-black" style={{ color: colors2000s.text.primary }}>
                            {store.name}
                          </p>
                          <p
                            className="text-[10px] font-bold uppercase tracking-widest"
                            style={{ color: colors2000s.text.secondary }}
                          >
                            {store.slug}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <span
                        className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                        style={
                          store.is_active ? scopeBadgeStyle('tenant') : scopeBadgeStyle('danger')
                        }
                      >
                        {statusLabel(store.is_active)}
                      </span>
                    </td>
                    <td
                      className="px-4 py-4 text-[10px] font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      <div>
                        Confirmacion:{' '}
                        <span style={{ color: colors2000s.text.primary }}>
                          {store.send_email_confirmation ? 'On' : 'Off'}
                        </span>
                      </div>
                      <div className="mt-1">
                        Reminders:{' '}
                        <span style={{ color: colors2000s.text.primary }}>
                          {store.send_email_reminders ? 'On' : 'Off'}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <p className="font-black" style={{ color: colors2000s.text.primary }}>
                        {store.active_users_count}/{store.users_count}
                      </p>
                      <p
                        className="text-[10px] font-bold uppercase tracking-widest"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        {store.admins_count} admins
                      </p>
                    </td>
                    <td className="px-4 py-4">
                      <p className="font-black" style={{ color: colors2000s.text.primary }}>
                        {store.current_plan_name || 'Sin plan'}
                      </p>
                      <p
                        className="text-[10px] font-bold uppercase tracking-widest"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        {store.subscription_status || 'Sin suscripcion'}
                      </p>
                    </td>
                    <td
                      className="px-4 py-4 text-sm font-bold"
                      style={{ color: colors2000s.text.primary }}
                    >
                      {formatDateEsAr(store.current_period_end)}
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex flex-wrap gap-2">
                        <MiniButton
                          label="Ver"
                          onClick={(event) => {
                            event.stopPropagation()
                            setSelectedStoreId(store.public_id)
                          }}
                        />
                        <MiniButton
                          label="Editar"
                          onClick={(event) => {
                            event.stopPropagation()
                            setSelectedStoreId(store.public_id)
                            openEditStoreFor(store)
                          }}
                          tone="primary"
                        />
                        <MiniButton
                          label={store.is_active ? 'Desactivar' : 'Activar'}
                          onClick={(event) => {
                            event.stopPropagation()
                            void toggleStoreActive(store)
                          }}
                          tone={store.is_active ? 'danger' : 'default'}
                        />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-[1.5rem] p-10 text-center" style={emptyStateStyle}>
          <Building2 className="mx-auto mb-3 h-10 w-10 opacity-25" />
          <p
            className="text-sm font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.primary }}
          >
            No hay tiendas para este filtro
          </p>
          <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Ajusta busqueda, estado o suscripcion para recuperar resultados.
          </p>
        </div>
      )}
    </div>
  </section>
)
