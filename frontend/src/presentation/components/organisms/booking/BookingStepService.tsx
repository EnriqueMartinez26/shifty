import React, { useId } from 'react'

import { Briefcase, Clock, Loader2, Check } from 'lucide-react'

import {
  MAX_SERVICES_PER_BOOKING,
  ServiceSelection,
  type ServiceBlockReason,
  type ServicePerformer
} from '@domain/value-objects/ServiceSelection'

import { publicServiceOptions } from '@application/mappers/PublicServiceOptionMapper'
import type { PublicService } from '@application/services/PublicBookingService'

import { usePublicServices } from '@presentation/hooks/usePublic'

import { formatCurrency } from '@shared/utils/currency'

import { addonsTotalOf, type ServiceAddonsGroup } from './addonGroups'
import { BookingAddonsPicker } from './BookingAddonsPicker'
import { BookingServicesBar } from './BookingServicesBar'
import { colors2000s } from '../../../../theme/colors'
import { brandCtaStyle, brandColor, brandGlowShadow } from '../../../lib/brandTheme'
import { createBookingChoiceCardStyle } from '../../../lib/surfaceStyles'

/** Elegir varios servicios para un mismo turno (`multi_service_booking`). */
interface MultiServiceChoice {
  /** En el orden elegido: el primero es el principal. */
  selectedIds: readonly string[]
  onToggle: (id: string) => void
  onContinue: () => void
  /**
   * Quien hace que (`service_ids` de /public/staff), lo trae el contenedor.
   * Sin la lista (cargando) no se apaga nada por profesional.
   */
  performers?: readonly ServicePerformer[]
}

/**
 * Adicionales de lo elegido (S4, 2026-10-21): se abren debajo de cada servicio
 * elegido. Los grupos los arma el contenedor con `groupAddonsByService`.
 */
interface ServiceAddonsChoice {
  /** Un grupo por servicio elegido, en el orden elegido. */
  groups: readonly ServiceAddonsGroup[]
  onChange: (serviceId: string, addonId: string, quantity: number) => void
  /** Sin varios servicios: seguir al horario despues de elegir los adicionales. */
  onContinue: () => void
}

interface BookingStepServiceProps {
  storePublicId: string
  selectedId: string | null
  onSelect: (id: string) => void
  /** Presente: tocar un servicio lo suma o lo quita y se sigue con la barra. */
  multiService?: MultiServiceChoice
  addons?: ServiceAddonsChoice
}

const BLOCK_HINTS: Record<ServiceBlockReason, string> = {
  limit: `Podés sumar hasta ${MAX_SERVICES_PER_BOOKING} servicios por turno.`,
  too_long: 'Ya no entra en un turno.',
  no_performer: 'Ningún profesional lo hace junto con lo que elegiste.'
}

interface ServiceCardProps {
  service: PublicService
  isSelected: boolean
  /** Por que no se puede sumar (null: se puede). */
  blockHint: string | null
  multi: boolean
  /** Con adicionales: si su contador esta abierto (sin adicionales, undefined). */
  expanded?: boolean
  /** Id del contador abierto debajo de la tarjeta. */
  controls?: string
  onClick: () => void
}

const ServiceCard: React.FC<ServiceCardProps> = ({
  service: svc,
  isSelected,
  blockHint,
  multi,
  expanded,
  controls,
  onClick
}) => {
  const serviceColor = svc.color || brandColor.fill
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={blockHint !== null}
      aria-pressed={multi ? isSelected : undefined}
      aria-expanded={expanded}
      aria-controls={controls}
      className="w-full text-left p-3 pl-4 sm:p-5 flex items-center gap-2 sm:gap-4 transition-all active:scale-98 group border relative overflow-hidden disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100"
      style={
        isSelected
          ? {
              ...createBookingChoiceCardStyle(true),
              background: brandColor.fillGradient,
              borderColor: brandColor.fillBottom,
              boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
            }
          : createBookingChoiceCardStyle(false)
      }
    >
      {/* Left dynamic accented border */}
      <div className="absolute left-0 top-0 bottom-0 w-2.5" style={{ background: serviceColor }} />

      {/* Glossy avatar */}
      <div
        className="w-9 h-9 sm:w-14 sm:h-14 rounded-md flex items-center justify-center flex-shrink-0 overflow-hidden"
        style={{
          background: isSelected
            ? 'linear-gradient(135deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0.15) 100%)'
            : 'linear-gradient(135deg, #ffffff 0%, #f3f4f6 100%)',
          boxShadow: isSelected
            ? 'inset 0 1px 2px rgba(255,255,255,0.5)'
            : colors2000s.shadows.insetDark,
          // Neutro (S9): un tono de marca no se lee igual en cada color de tienda.
          color: isSelected ? brandColor.onFill : colors2000s.text.primary
        }}
      >
        {svc.image_url ? (
          <img
            src={svc.image_url}
            alt={svc.name}
            loading="lazy"
            decoding="async"
            width={56}
            height={56}
            className="w-full h-full object-cover"
          />
        ) : (
          <Briefcase className="w-6 h-6 group-hover:scale-110 transition-transform duration-300" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        {/* En 390 px el nombre salia cortado ("BARBA Y PERFILAD"), el precio
            recortado y el circulo encima del titulo (QA movil 2026-10-08). */}
        <p
          className="text-base sm:text-lg font-black uppercase tracking-tight leading-tight mb-2 break-words"
          style={{
            color: isSelected ? brandColor.onFill : colors2000s.text.primary
          }}
        >
          {svc.name}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          {/* Recessed spec fields */}
          <span
            className="text-xs font-black px-3 py-1 rounded-md flex items-center gap-1 whitespace-nowrap"
            style={{
              background: '#ffffff',
              boxShadow: colors2000s.shadows.insetDark,
              color: colors2000s.text.primary
            }}
          >
            <Clock className="w-3.5 h-3.5" style={{ color: colors2000s.text.secondary }} />{' '}
            {svc.duration_minutes} min
          </span>

          <span
            className="text-xs font-black px-3 py-1 rounded-md whitespace-nowrap"
            style={{
              background: '#ffffff',
              boxShadow: colors2000s.shadows.insetDark,
              color: colors2000s.text.primary
            }}
          >
            {formatCurrency(svc.price)}
          </span>
        </div>

        {blockHint && (
          <p className="mt-2 text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
            {blockHint}
          </p>
        )}
      </div>

      <div
        className="w-6 h-6 sm:w-7 sm:h-7 flex-shrink-0 rounded-full flex items-center justify-center transition-all"
        style={{
          background: isSelected
            ? `linear-gradient(180deg, ${colors2000s.status.success.light} 0%, ${colors2000s.status.success.dark} 100%)`
            : '#ffffff',
          boxShadow: isSelected
            ? 'inset 0 1px 0 rgba(255,255,255,0.3)'
            : 'inset 0 1px 2px rgba(0,0,0,0.1)'
        }}
      >
        {isSelected && <Check className="w-4 h-4 text-white font-black" />}
      </div>
    </button>
  )
}

export const BookingStepService: React.FC<BookingStepServiceProps> = ({
  storePublicId,
  selectedId,
  onSelect,
  multiService,
  addons
}) => {
  const {
    data: services,
    isError,
    isFetching,
    isLoading,
    refetch
  } = usePublicServices(storePublicId)
  // Base de los ids de cada contador, para asociarlo a su tarjeta.
  const addonsIdBase = useId()

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="mb-6">
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            ¿Qué servicio necesitás?
          </h2>
          <p className="text-sm font-bold text-gray-500">
            Estamos cargando las opciones del negocio.
          </p>
        </div>
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex h-40 flex-col items-center justify-center"
        >
          <Loader2
            aria-hidden="true"
            className="w-8 h-8 animate-spin mb-4"
            style={{ color: colors2000s.text.secondary }}
          />
          <p className="text-sm font-black text-gray-500 uppercase tracking-widest">
            Cargando servicios...
          </p>
        </div>
      </div>
    )
  }

  const catalog = publicServiceOptions(services)
  const selection = ServiceSelection.of(multiService?.selectedIds ?? []).retainIn(catalog)
  const performers = multiService?.performers
  const groups = addons?.groups ?? []
  // Un servicio elegido con adicionales abre su contador debajo de la tarjeta.
  const openGroup = (serviceId: string) =>
    groups.find((group) => group.serviceId === serviceId && group.options.length > 0)
  // Sin varios servicios, la barra aparece solo si el elegido tiene
  // adicionales: sin ellos, tocarlo ya avanza.
  const singleWithAddons = selectedId && openGroup(selectedId) ? selectedId : null
  const barSelection = multiService
    ? selection
    : singleWithAddons
      ? ServiceSelection.of([singleWithAddons]).retainIn(catalog)
      : null
  const onBarContinue = multiService ? multiService.onContinue : addons?.onContinue

  return (
    <div className="space-y-4 duration-500">
      <div className="mb-6">
        <h2
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          ¿Qué servicio necesitás?
        </h2>
        <p className="text-sm font-bold text-gray-500">
          {multiService
            ? 'Elegí uno o más servicios para el mismo turno y tocá Continuar.'
            : addons && services?.some((service) => (service.addons?.length ?? 0) > 0)
              ? 'Elegí un servicio; si ofrece adicionales, podés sumarlos antes de continuar.'
              : 'Elegí un servicio y avanzás automáticamente.'}
        </p>
      </div>

      <div className="grid gap-4">
        {isError && services === undefined && (
          <div
            role="alert"
            className="flex flex-col items-start gap-3 rounded-md border-2 p-4 sm:flex-row sm:items-center sm:justify-between"
            style={{
              background: colors2000s.status.danger.bg,
              borderColor: colors2000s.status.danger.border,
              color: colors2000s.status.danger.text
            }}
          >
            <p className="text-sm font-bold">
              No pudimos cargar los servicios. Revisá tu conexión e intentá nuevamente.
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="min-h-11 shrink-0 rounded-md px-4 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={brandCtaStyle}
            >
              {isFetching ? 'Reintentando…' : 'Reintentar'}
            </button>
          </div>
        )}

        {isError && services !== undefined && (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-col items-start gap-3 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between"
            style={{
              background: colors2000s.status.warning.bg,
              borderColor: colors2000s.status.warning.border,
              color: colors2000s.status.warning.text
            }}
          >
            <p className="text-sm font-bold">
              {services.length > 0
                ? 'No pudimos actualizar el catálogo. Podés seguir con los servicios cargados.'
                : 'No pudimos actualizar el catálogo y no hay servicios disponibles para reservar.'}
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="min-h-11 shrink-0 rounded-md px-4 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={brandCtaStyle}
            >
              {isFetching ? 'Actualizando…' : 'Reintentar'}
            </button>
          </div>
        )}

        {!isError && services !== undefined && catalog.length === 0 && (
          <div
            role="status"
            aria-live="polite"
            className="rounded-md border p-4 text-sm font-bold"
            style={{
              background: colors2000s.bg.button,
              borderColor: colors2000s.border.default,
              color: colors2000s.text.secondary
            }}
          >
            No hay servicios disponibles para reservar en este momento.
          </div>
        )}

        {services?.map((svc) => {
          const option = multiService
            ? catalog.find((candidate) => candidate.id === svc.public_id)
            : undefined
          const reason =
            multiService && option ? selection.blockReason(option, catalog, performers) : null
          const isSelected = multiService
            ? selection.includes(svc.public_id)
            : selectedId === svc.public_id
          const expandable = Boolean(addons) && (svc.addons?.length ?? 0) > 0
          const group = isSelected ? openGroup(svc.public_id) : undefined
          const regionId = `${addonsIdBase}-adicionales-${svc.public_id}`
          return (
            <div key={svc.public_id} className="space-y-2">
              <ServiceCard
                service={svc}
                isSelected={isSelected}
                blockHint={reason ? BLOCK_HINTS[reason] : null}
                multi={Boolean(multiService)}
                expanded={expandable ? Boolean(group) : undefined}
                controls={group ? regionId : undefined}
                onClick={() =>
                  multiService ? multiService.onToggle(svc.public_id) : onSelect(svc.public_id)
                }
              />
              {group && addons && (
                <BookingAddonsPicker
                  id={regionId}
                  title={`Adicionales de ${svc.name}`}
                  addons={group.options}
                  quantities={group.selection.toQuantities()}
                  onChange={(addonId, quantity) =>
                    addons.onChange(svc.public_id, addonId, quantity)
                  }
                />
              )}
            </div>
          )
        })}
      </div>

      {barSelection && !barSelection.isEmpty() && onBarContinue && (
        <BookingServicesBar
          count={barSelection.count()}
          durationMinutes={barSelection.totalDuration(catalog)}
          listPrice={barSelection.listPrice(catalog)}
          addonsTotal={addonsTotalOf(groups)}
          onContinue={onBarContinue}
        />
      )}
    </div>
  )
}
