import React from 'react'

import { Building2, Filter, Search } from 'lucide-react'

import type { SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { superAdminPalette, superAdminSelectedControlStyle } from './palette'
import {
  daysUntil,
  emptyStateStyle,
  expiryLabel,
  innerCardStyle,
  panelStyle,
  scopeBadgeStyle,
  statusBadgeStyle,
  statusLabel,
  type ActivityFilter,
  type QueryState,
  type SubscriptionFilter
} from './shared'
import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { QuerySectionFeedback } from '../../components/molecules/QuerySectionFeedback'
import { subscriptionStatusLabel } from '../../lib/enumLabels'
import { formatDateEsAr } from '../../lib/formatters'
import { create2000sInputStyle } from '../../lib/surfaceStyles'
import { buttonFocusVisibleClassName, MiniButton } from '../SuperAdminUi'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

/** Listado paginado (FF-24): `total` es null si el backend no mando el header. */
interface StoresQueryState extends QueryState<SuperAdminStoreRow[]> {
  total: number | null
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => unknown
}

interface StoresSectionProps {
  /** Texto tipeado; la consulta se aplica con espera en SuperAdmin.tsx (F4-10). */
  search: string
  onSearchChange: (value: string) => void
  activityFilter: ActivityFilter
  setActivityFilter: React.Dispatch<React.SetStateAction<ActivityFilter>>
  subscriptionFilter: SubscriptionFilter
  setSubscriptionFilter: React.Dispatch<React.SetStateAction<SubscriptionFilter>>
  selectedStoreId: string | null
  setSelectedStoreId: React.Dispatch<React.SetStateAction<string | null>>
  /** "Ver": elige la tienda y lleva la vista a su detalle (2026-10-10). */
  onViewStore: (storePublicId: string) => void
  storesQuery: StoresQueryState
  openEditStoreFor: (store: SuperAdminStoreRow) => void
  toggleStoreActive: (store: SuperAdminStoreRow) => Promise<void>
}

export const StoresSection: React.FC<StoresSectionProps> = ({
  search,
  onSearchChange,
  activityFilter,
  setActivityFilter,
  subscriptionFilter,
  setSubscriptionFilter,
  selectedStoreId,
  setSelectedStoreId,
  onViewStore,
  storesQuery,
  openEditStoreFor,
  toggleStoreActive
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    {/* Titulo arriba y filtros abajo, que pasan de linea: en una fila, los
        de suscripcion quedaban tapados por la columna derecha (QA 2026-10-02). */}
    <div className="flex flex-col gap-4">
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
          Operación por tienda
        </h2>
        <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          Filtros por estado y suscripción para revisar rápido.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search
            className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2"
            style={{ color: colors2000s.text.disabled }}
          />
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Buscar por nombre o slug"
            aria-label="Buscar tienda"
            maxLength={100}
            className="w-full rounded-2xl py-3 pl-11 pr-4 text-sm font-bold outline-none md:w-72"
            style={create2000sInputStyle()}
          />
        </div>

        <div
          role="group"
          aria-label="Filtrar tiendas por estado"
          className="flex flex-wrap items-center gap-2 rounded-2xl p-2"
          style={innerCardStyle}
        >
          <Filter
            aria-hidden="true"
            className="h-4 w-4"
            style={{ color: colors2000s.text.secondary }}
          />
          {[
            { value: 'active', label: 'Activas' },
            { value: 'inactive', label: 'Inactivas' },
            { value: 'all', label: 'Todas' }
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setActivityFilter(item.value as ActivityFilter)}
              aria-pressed={activityFilter === item.value}
              className={`min-h-11 rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest ${buttonFocusVisibleClassName}`}
              style={
                activityFilter === item.value
                  ? superAdminSelectedControlStyle
                  : buttonStyles2000s.default
              }
            >
              {item.label}
            </button>
          ))}
        </div>

        <div
          role="group"
          aria-label="Filtrar tiendas por suscripción"
          className="flex flex-wrap items-center gap-2 rounded-2xl p-2"
          style={innerCardStyle}
        >
          {[
            { value: 'all', label: 'Todas' },
            { value: 'with', label: 'Con suscripción' },
            { value: 'without', label: 'Sin suscripción' }
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setSubscriptionFilter(item.value as SubscriptionFilter)}
              aria-pressed={subscriptionFilter === item.value}
              className={`min-h-11 rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest ${buttonFocusVisibleClassName}`}
              style={
                subscriptionFilter === item.value
                  ? superAdminSelectedControlStyle
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
      <QuerySectionFeedback
        loading={storesQuery.isLoading || (!storesQuery.data && !storesQuery.error)}
        loadingMessage={storesQuery.data ? 'Actualizando tiendas...' : 'Cargando tiendas...'}
        error={storesQuery.error}
        errorMessage={
          storesQuery.data
            ? 'No se pudieron actualizar las tiendas. Se muestran los últimos datos disponibles.'
            : 'No se pudieron cargar las tiendas. Reintentá para actualizar el listado.'
        }
        isFetching={storesQuery.isFetching}
        onRetry={storesQuery.refetch}
      />
      {storesQuery.data?.length ? (
        <>
          <p
            className="mb-2 px-4 pt-3 text-[10px] font-bold sm:hidden"
            style={{ color: colors2000s.text.secondary }}
          >
            Deslizá horizontalmente para ver todas las columnas.
          </p>
          <div className="overflow-x-auto overscroll-x-contain">
            <table className="min-w-full text-left">
              <thead style={{ background: colors2000s.bg.disabled }}>
                <tr>
                  {[
                    'Tienda',
                    'Estado',
                    'Recordatorios',
                    'Usuarios',
                    'Suscripción',
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
                      aria-current={isSelected ? 'true' : undefined}
                      className="cursor-pointer transition-colors"
                      style={
                        isSelected
                          ? {
                              background: superAdminPalette.orangePale,
                              boxShadow: `inset 4px 0 0 ${superAdminPalette.orangeDark}`
                            }
                          : { background: 'transparent' }
                      }
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
                            {store.is_internal ? (
                              <span
                                className="mt-1 mr-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-black uppercase tracking-widest"
                                style={scopeBadgeStyle('global')}
                              >
                                Interna
                              </span>
                            ) : null}
                            {isSelected ? (
                              <span
                                className="mt-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-black uppercase tracking-widest"
                                style={scopeBadgeStyle('tenant')}
                              >
                                Seleccionada
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <span
                          className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                          style={
                            store.is_active
                              ? statusBadgeStyle('success')
                              : statusBadgeStyle('danger')
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
                          Confirmación:{' '}
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
                          {store.subscription_status
                            ? subscriptionStatusLabel(store.subscription_status)
                            : 'Sin suscripción'}
                        </p>
                      </td>
                      <td
                        className="px-4 py-4 text-sm font-bold"
                        style={{ color: colors2000s.text.primary }}
                      >
                        {formatDateEsAr(store.current_period_end)}
                        <span
                          className="block text-[10px] font-black uppercase tracking-widest"
                          style={{
                            color:
                              (daysUntil(store.current_period_end) ?? 99) < 0
                                ? '#dc2626'
                                : (daysUntil(store.current_period_end) ?? 99) <= 7
                                  ? '#d97706'
                                  : colors2000s.text.secondary
                          }}
                        >
                          {expiryLabel(store.current_period_end)}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap gap-2">
                          <MiniButton
                            label="Ver"
                            onClick={(event) => {
                              event.stopPropagation()
                              onViewStore(store.public_id)
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
        </>
      ) : storesQuery.data ? (
        <div className="rounded-[1.5rem] p-10 text-center" style={emptyStateStyle}>
          <Building2 className="mx-auto mb-3 h-10 w-10 opacity-25" />
          <p
            className="text-sm font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.primary }}
          >
            No hay tiendas para este filtro
          </p>
          <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Ajustá la búsqueda, el estado o la suscripción para ver resultados.
          </p>
        </div>
      ) : null}
    </div>

    {!storesQuery.error && storesQuery.data?.length ? (
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Mostrando {storesQuery.data.length}
          {storesQuery.total === null ? '' : ` de ${storesQuery.total}`}
        </p>
        {storesQuery.hasNextPage ? (
          <MiniButton
            label={storesQuery.isFetchingNextPage ? 'Cargando...' : 'Cargar más'}
            onClick={() => void storesQuery.fetchNextPage()}
            disabled={storesQuery.isFetchingNextPage}
          />
        ) : null}
      </div>
    ) : null}
  </section>
)
