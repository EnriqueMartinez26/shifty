import React from 'react'

import { Briefcase, Clock, Loader2, Check } from 'lucide-react'

import { usePublicServices } from '@presentation/hooks/usePublic'

import { colors2000s } from '../../../../theme/colors'
import { createBookingChoiceCardStyle } from '../../../lib/surfaceStyles'

interface BookingStepServiceProps {
  storePublicId: string
  selectedId: string | null
  onSelect: (id: string) => void
}

export const BookingStepService: React.FC<BookingStepServiceProps> = ({
  storePublicId,
  selectedId,
  onSelect
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

  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="mb-6">
        <h2
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.accent }}
        >
          ¿Qué servicio necesitás?
        </h2>
        <p className="text-sm font-bold text-gray-500">Elegí una opción para continuar.</p>
      </div>

      <div className="grid gap-4">
        {services?.map((svc) => {
          const isSelected = selectedId === svc.public_id
          const serviceColor = svc.color || '#ff8c42'

          return (
            <button
              key={svc.public_id}
              onClick={() => onSelect(svc.public_id)}
              className="w-full text-left p-5 flex items-center gap-4 rounded-2xl transition-all active:scale-98 group border relative overflow-hidden"
              style={createBookingChoiceCardStyle(isSelected)}
            >
              {/* Left dynamic accented border */}
              <div
                className="absolute left-0 top-0 bottom-0 w-2.5"
                style={{ background: serviceColor }}
              />

              {/* Glossy avatar */}
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center flex-shrink-0 border ml-1 overflow-hidden"
                style={{
                  background: isSelected
                    ? 'linear-gradient(135deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0.15) 100%)'
                    : 'linear-gradient(135deg, #ffffff 0%, #f3f4f6 100%)',
                  borderColor: isSelected ? 'rgba(255,255,255,0.4)' : colors2000s.border.light,
                  boxShadow: isSelected
                    ? 'inset 0 1px 2px rgba(255,255,255,0.5)'
                    : colors2000s.shadows.insetDark,
                  color: isSelected ? '#ffffff' : serviceColor
                }}
              >
                {svc.image_url ? (
                  <img src={svc.image_url} alt={svc.name} className="w-full h-full object-cover" />
                ) : (
                  <Briefcase className="w-6 h-6 group-hover:scale-110 transition-transform duration-300" />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <p
                  className="text-lg font-black uppercase tracking-tight leading-none mb-2"
                  style={{ color: isSelected ? '#ffffff' : colors2000s.text.primary }}
                >
                  {svc.name}
                </p>

                <div className="flex items-center gap-3">
                  {/* Recessed spec fields */}
                  <span
                    className="text-xs font-black px-3 py-1 rounded-lg flex items-center gap-1 border"
                    style={{
                      background: '#ffffff',
                      borderColor: colors2000s.border.light,
                      boxShadow: colors2000s.shadows.insetDark,
                      color: colors2000s.text.primary
                    }}
                  >
                    <Clock className="w-3.5 h-3.5 text-orange-500" /> {svc.duration_minutes} min
                  </span>

                  <span
                    className="text-xs font-black px-3 py-1 rounded-lg border"
                    style={{
                      background: '#ffffff',
                      borderColor: colors2000s.border.light,
                      boxShadow: colors2000s.shadows.insetDark,
                      color: colors2000s.orange.accent
                    }}
                  >
                    ${svc.price}
                  </span>
                </div>
              </div>

              <div
                className="w-7 h-7 rounded-full flex items-center justify-center transition-all border"
                style={{
                  background: isSelected
                    ? 'linear-gradient(180deg, #22c55e 0%, #16a34a 100%)'
                    : '#ffffff',
                  borderColor: isSelected ? '#16a34a' : colors2000s.border.default,
                  boxShadow: isSelected
                    ? 'inset 0 1px 0 rgba(255,255,255,0.3)'
                    : 'inset 0 1px 2px rgba(0,0,0,0.1)'
                }}
              >
                {isSelected && <Check className="w-4 h-4 text-white font-black" />}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
export default BookingStepService
