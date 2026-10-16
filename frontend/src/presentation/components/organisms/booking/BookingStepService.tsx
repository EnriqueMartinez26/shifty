import React from 'react'

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

import { BookingServicesBar } from './BookingServicesBar'
import { colors2000s } from '../../../../theme/colors'
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

interface BookingStepServiceProps {
  storePublicId: string
  selectedId: string | null
  onSelect: (id: string) => void
  /** Presente: tocar un servicio lo suma o lo quita y se sigue con la barra. */
  multiService?: MultiServiceChoice
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
  onClick: () => void
}

const ServiceCard: React.FC<ServiceCardProps> = ({
  service: svc,
  isSelected,
  blockHint,
  multi,
  onClick
}) => {
  const serviceColor = svc.color || colors2000s.orange.light
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={blockHint !== null}
      aria-pressed={multi ? isSelected : undefined}
      className="w-full text-left p-4 pl-5 sm:p-5 flex items-center gap-3 sm:gap-4 transition-all active:scale-98 group border relative overflow-hidden disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100"
      style={createBookingChoiceCardStyle(isSelected)}
    >
      {/* Left dynamic accented border */}
      <div className="absolute left-0 top-0 bottom-0 w-2.5" style={{ background: serviceColor }} />

      {/* Glossy avatar */}
      <div
        className="w-12 h-12 sm:w-14 sm:h-14 rounded-md flex items-center justify-center flex-shrink-0 ml-1 overflow-hidden"
        style={{
          background: isSelected
            ? 'linear-gradient(135deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0.15) 100%)'
            : 'linear-gradient(135deg, #ffffff 0%, #f3f4f6 100%)',
          boxShadow: isSelected
            ? 'inset 0 1px 2px rgba(255,255,255,0.5)'
            : colors2000s.shadows.insetDark,
          color: isSelected ? colors2000s.text.onOrangeSelection : serviceColor
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
            color: isSelected ? colors2000s.text.onOrangeSelection : colors2000s.text.primary
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
            <Clock className="w-3.5 h-3.5 text-orange-500" /> {svc.duration_minutes} min
          </span>

          <span
            className="text-xs font-black px-3 py-1 rounded-md whitespace-nowrap"
            style={{
              background: '#ffffff',
              boxShadow: colors2000s.shadows.insetDark,
              color: colors2000s.orange.accent
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
        className="w-7 h-7 flex-shrink-0 rounded-full flex items-center justify-center transition-all"
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
  multiService
}) => {
  const { data: services, isLoading } = usePublicServices(storePublicId)

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-48">
        <Loader2 className="w-8 h-8 animate-spin text-orange-500 mb-4" />
        <p className="text-sm font-black text-gray-500 uppercase tracking-widest">
          Cargando servicios...
        </p>
      </div>
    )
  }

  const catalog = publicServiceOptions(services)
  const selection = ServiceSelection.of(multiService?.selectedIds ?? []).retainIn(catalog)
  const performers = multiService?.performers

  return (
    <div className="space-y-4 duration-500">
      <div className="mb-6">
        <h2
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.heading }}
        >
          ¿Qué servicio necesitás?
        </h2>
        <p className="text-sm font-bold text-gray-500">
          {multiService
            ? 'Elegí uno o más servicios para el mismo turno y tocá Continuar.'
            : 'Elegí una opción para continuar.'}
        </p>
      </div>

      <div className="grid gap-4">
        {services?.map((svc) => {
          if (!multiService) {
            return (
              <ServiceCard
                key={svc.public_id}
                service={svc}
                isSelected={selectedId === svc.public_id}
                blockHint={null}
                multi={false}
                onClick={() => onSelect(svc.public_id)}
              />
            )
          }
          const option = catalog.find((candidate) => candidate.id === svc.public_id)
          const reason = option ? selection.blockReason(option, catalog, performers) : null
          return (
            <ServiceCard
              key={svc.public_id}
              service={svc}
              isSelected={selection.includes(svc.public_id)}
              blockHint={reason ? BLOCK_HINTS[reason] : null}
              multi
              onClick={() => multiService.onToggle(svc.public_id)}
            />
          )
        })}
      </div>

      {multiService && !selection.isEmpty() && (
        <BookingServicesBar
          count={selection.count()}
          durationMinutes={selection.totalDuration(catalog)}
          listPrice={selection.listPrice(catalog)}
          onContinue={multiService.onContinue}
        />
      )}
    </div>
  )
}
