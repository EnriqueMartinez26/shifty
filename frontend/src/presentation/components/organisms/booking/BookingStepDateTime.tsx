import React, { useState, useMemo } from "react";
import { ChevronLeft, Calendar as CalendarIcon, Clock, Loader2 } from "lucide-react";
import { format, addDays, parseISO } from "date-fns";
import { es } from "date-fns/locale";
import { usePublicAvailability } from "@presentation/hooks/usePublic";
import { colors2000s } from "../../../../theme/colors";

interface BookingStepDateTimeProps {
  storePublicId: string;
  serviceId: string;
  staffId: string;
  selectedDate: string | null;
  selectedTime: string | null;
  onSelect: (date: string, time: string) => void;
  onBack: () => void;
}

export const BookingStepDateTime: React.FC<BookingStepDateTimeProps> = ({
  storePublicId, serviceId, staffId, selectedDate, selectedTime, onSelect, onBack
}) => {
  const [activeDate, setActiveDate] = useState<Date>(() => {
    if (!selectedDate || selectedDate === "invalid") return new Date();
    const parsed = parseISO(selectedDate);
    return isNaN(parsed.getTime()) ? new Date() : parsed;
  });
  const [forceAll, setForceAll] = useState(false);

  // Generar próximos 14 días
  const dates = useMemo(() => {
    return Array.from({ length: 14 }).map((_, i) => addDays(new Date(), i));
  }, []);

  const dateStr = format(activeDate, "yyyy-MM-dd");

  const { data: availability, isLoading } = usePublicAvailability(
    storePublicId,
    serviceId,
    /^\d{4}-\d{2}-\d{2}$/.test(dateStr) ? dateStr : undefined,
    forceAll
  );

  // Filtrar los slots por el staff seleccionado
  const availableSlots = useMemo(() => {
    if (!availability) return [];
    return availability.filter((slot) => slot.staff_id === staffId);
  }, [availability, staffId]);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="flex items-center gap-4 mb-2">
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
            Elegí fecha y hora
          </h2>
          <p className="text-sm font-bold text-gray-500">Buscá un horario disponible.</p>
        </div>
      </div>

      {/* Selector de Fecha Horizontal */}
      <div>
        <div className="flex items-center gap-2 mb-3 text-xs font-black text-gray-500 uppercase tracking-widest ml-1">
          <CalendarIcon size={14} className="text-orange-500" />
          <span>Fechas Disponibles</span>
        </div>
        
        {/* Recessed slider container */}
        <div 
          className="flex gap-3 overflow-x-auto p-4 snap-x hide-scrollbar rounded-2xl border"
          style={{
            background: '#ffffff',
            borderColor: colors2000s.border.light,
            boxShadow: colors2000s.shadows.insetDark
          }}
        >
          {dates.map((date) => {
            const formattedDate = format(date, "yyyy-MM-dd");
            const isSelected = format(activeDate, "yyyy-MM-dd") === formattedDate;
            const isToday = format(date, "yyyy-MM-dd") === format(new Date(), "yyyy-MM-dd");

            return (
              <button
                key={formattedDate}
                onClick={() => {
                  setActiveDate(date);
                }}
                className="flex flex-col items-center justify-center min-w-[72px] py-3 rounded-2xl border transition-all snap-center active:scale-95"
                style={{
                  background: isSelected
                    ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
                    : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                  borderColor: isSelected ? colors2000s.orange.accent : colors2000s.border.default,
                  boxShadow: isSelected 
                    ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}` 
                    : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                  color: isSelected ? '#ffffff' : colors2000s.text.primary
                }}
              >
                <span className="text-[9px] uppercase font-black tracking-widest opacity-80">
                  {isToday ? "Hoy" : format(date, "EEE", { locale: es })}
                </span>
                <span className="text-2xl font-black mt-1 leading-none">
                  {format(date, "dd")}
                </span>
                <span className="text-[9px] font-black uppercase tracking-widest opacity-80 mt-1">
                  {format(date, "MMM", { locale: es })}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Selector de Horarios */}
      <div className="pt-2">
        <div className="flex items-center justify-between mb-4 ml-1">
          <div className="flex items-center gap-2 text-xs font-black text-gray-500 uppercase tracking-widest">
            <Clock size={14} className="text-orange-500" />
            <span>Horarios Disponibles</span>
          </div>
          <label className="flex items-center gap-2 cursor-pointer opacity-80 hover:opacity-100 transition-opacity">
            <span className="text-[9px] font-black uppercase text-gray-500 tracking-wider">Ver todos</span>
            <div 
              className={`w-9 h-5 rounded-full p-1 transition-colors ${forceAll ? 'bg-orange-500' : 'bg-gray-300'}`}
              onClick={() => setForceAll(!forceAll)}
            >
              <div 
                className={`w-3 h-3 bg-white rounded-full shadow-sm transform transition-transform ${forceAll ? 'translate-x-4' : 'translate-x-0'}`} 
              />
            </div>
          </label>
        </div>

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-10">
            <Loader2 className="w-8 h-8 animate-spin text-orange-500 mb-4" />
          </div>
        ) : availableSlots.length === 0 ? (
          <div 
            className="text-center py-10 rounded-2xl border"
            style={{
              background: '#ffffff',
              borderColor: colors2000s.border.light,
              boxShadow: colors2000s.shadows.insetDark
            }}
          >
            <p className="font-black text-gray-400 uppercase tracking-widest text-xs">No hay turnos disponibles.</p>
            <p className="text-xs text-gray-400 mt-2 font-medium">Por favor, probá seleccionando otro día.</p>
          </div>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
            {availableSlots.map((slot: any) => {
              const timeString = (slot.start_time || slot.starts_at.split("T")[1] || "").substring(0, 5);
              const isSelected = selectedDate === dateStr && selectedTime === timeString;
              const isAvailable = slot.status === "available";
              const badgeColor =
                slot.status === "blocked" ? "#dc2626" : slot.status === "booked" ? "#2563eb" : colors2000s.text.secondary;

              return (
                <button
                  key={slot.start_time || slot.starts_at}
                  onClick={() => isAvailable && onSelect(dateStr, timeString)}
                  disabled={!isAvailable}
                  className="py-3 rounded-xl font-black text-lg transition-all active:scale-95 border disabled:cursor-not-allowed disabled:opacity-70"
                  style={{
                    background: isSelected
                      ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
                      : isAvailable
                        ? `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`
                        : "linear-gradient(180deg, #f5f5f5 0%, #e5e7eb 100%)",
                    borderColor: isSelected ? colors2000s.orange.accent : colors2000s.border.default,
                    boxShadow: isSelected 
                      ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}` 
                      : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                    color: isSelected ? '#ffffff' : isAvailable ? colors2000s.text.primary : colors2000s.text.disabled
                  }}
                >
                  <div>{timeString}</div>
                  <div className="text-[8px] uppercase tracking-widest mt-1" style={{ color: isSelected ? "#ffffff" : badgeColor }}>
                    {slot.status}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <style dangerouslySetInnerHTML={{__html: `
        .hide-scrollbar::-webkit-scrollbar { display: none; }
        .hide-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
      `}} />
    </div>
  );
};
export default BookingStepDateTime;
