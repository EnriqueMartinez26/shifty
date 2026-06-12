import React from 'react'
import { Check, ChevronLeft, Loader2, Sparkles, User } from 'lucide-react'

import { usePublicStaff } from '@presentation/hooks/usePublic'
import { colors2000s } from '../../../../theme/colors'

interface BookingStepStaffProps {
  storePublicId: string
  serviceId: string
  selectedId: string | null
  onSelect: (id: string | null) => void
  onBack: () => void
}

export const BookingStepStaff: React.FC<BookingStepStaffProps> = ({
  storePublicId,
  serviceId,
  selectedId,
  onSelect,
  onBack
}) => {
  const { data: staffList, isLoading } = usePublicStaff(storePublicId, serviceId)

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-48">
        <Loader2 className="w-8 h-8 animate-spin text-orange-500 mb-4" />
        <p className="text-sm font-black text-gray-500 uppercase tracking-widest">
          Cargando profesionales...
        </p>
      </div>
    )
  }

  const cards = [
    {
      id: null,
      title: 'Cualquier profesional',
      subtitle: 'Te asignamos el primero disponible para el horario que elijas.',
      accent: 'linear-gradient(180deg, #0f766e 0%, #115e59 100%)',
      icon: <Sparkles className="w-6 h-6" />
    },
    ...(staffList || []).map((staff, idx) => ({
      id: staff.public_id,
      title: `${staff.first_name} ${staff.last_name}`.trim(),
      subtitle: 'Profesional disponible para este servicio.',
      accent:
        idx % 2 === 0
          ? 'linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)'
          : `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
      icon: <User className="w-6 h-6 group-hover:scale-110 transition-transform duration-300" />
    }))
  ]

  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={onBack}
          className="p-2 rounded-full transition-all active:scale-90 flex items-center justify-center border"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
            color: colors2000s.text.primary
          }}
        >
          <ChevronLeft size={20} className="stroke-[3px]" />
        </button>
        <div>
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.orange.accent }}
          >
            Quien te atiende?
          </h2>
          <p className="text-sm font-bold text-gray-500">
            Podes elegir un profesional puntual o dejar que el sistema lo asigne.
          </p>
        </div>
      </div>

      <div className="grid gap-4">
        {cards.map((card, idx) => {
          const isSelected = selectedId === card.id
          return (
            <button
              key={card.id ?? 'any-professional'}
              onClick={() => onSelect(card.id)}
              className="w-full text-left p-5 flex items-center gap-4 rounded-2xl transition-all active:scale-98 group border relative overflow-hidden"
              style={{
                background: isSelected
                  ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
                  : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                borderColor: isSelected ? colors2000s.orange.accent : colors2000s.border.default,
                boxShadow: isSelected
                  ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                  : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
              }}
            >
              <div
                className="absolute left-0 top-0 bottom-0 w-2.5"
                style={{ background: card.accent }}
              />
              <div
                className="w-14 h-14 rounded-full flex items-center justify-center border ml-1 flex-shrink-0"
                style={{
                  background: isSelected
                    ? 'linear-gradient(135deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0.15) 100%)'
                    : idx % 2 === 0
                      ? 'linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)'
                      : 'linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%)',
                  borderColor: isSelected
                    ? 'rgba(255,255,255,0.4)'
                    : idx % 2 === 0
                      ? '#bfdbfe'
                      : '#fed7aa',
                  boxShadow: isSelected
                    ? 'inset 0 1px 2px rgba(255,255,255,0.5)'
                    : colors2000s.shadows.insetDark,
                  color: isSelected
                    ? '#ffffff'
                    : idx % 2 === 0
                      ? '#2563eb'
                      : colors2000s.orange.dark
                }}
              >
                {card.icon}
              </div>

              <div className="flex-1 min-w-0">
                <p
                  className="text-lg font-black uppercase tracking-tight leading-none mb-2"
                  style={{ color: isSelected ? '#ffffff' : colors2000s.text.primary }}
                >
                  {card.title}
                </p>
                <p
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{
                    color: isSelected ? 'rgba(255,255,255,0.8)' : colors2000s.text.secondary
                  }}
                >
                  {card.subtitle}
                </p>
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

export default BookingStepStaff
