import React, { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Calendar, Clock } from "lucide-react";
import { colors2000s } from "../../../../theme/colors";

interface BookingStepConfirmationProps {
  bookingState: any;
  onBack: () => void;
  onConfirm: () => Promise<void>;
}

export const BookingStepConfirmation: React.FC<BookingStepConfirmationProps> = ({ 
  bookingState, onBack, onConfirm 
}) => {
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");

  useEffect(() => {
    let mounted = true;
    const processBooking = async () => {
      setStatus("loading");
      try {
        await onConfirm();
        if (mounted) setStatus("success");
      } catch (error) {
        console.error(error);
        if (mounted) setStatus("error");
      }
    };
    
    processBooking();

    return () => { mounted = false; };
  }, []);

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center justify-center py-20 animate-in fade-in duration-500">
        <Loader2 className="w-16 h-16 animate-spin text-orange-500 mb-6" />
        <h2 
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.accent }}
        >
          Confirmando...
        </h2>
        <p className="text-sm font-bold text-gray-500 mt-2">No cierres esta ventana.</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center animate-in fade-in zoom-in-95 duration-500">
        <div 
          className="w-20 h-20 rounded-full flex items-center justify-center mb-6 border"
          style={{
            background: 'linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)',
            borderColor: '#fca5a5',
            boxShadow: colors2000s.shadows.insetDark,
            color: '#ef4444'
          }}
        >
          <CheckCircle2 className="w-10 h-10" />
        </div>
        <h2 
          className="text-2xl font-black uppercase tracking-tight"
          style={{ color: '#ef4444' }}
        >
          Hubo un error
        </h2>
        <p className="text-sm font-bold text-gray-500 mt-2 mb-8">No pudimos procesar tu reserva. El horario podría estar ocupado.</p>
        <button
          onClick={onBack}
          className="px-8 py-3.5 text-gray-600 font-black rounded-xl uppercase tracking-widest text-xs border active:scale-95 transition-all cursor-pointer select-none"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
          }}
        >
          Volver a intentar
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center py-10 text-center animate-in fade-in zoom-in-95 duration-500">
      <div className="relative mb-8">
        <div className="absolute inset-0 bg-green-500 rounded-full blur-xl opacity-20 animate-pulse" />
        <div 
          className="w-24 h-24 rounded-full flex items-center justify-center text-white shadow-2xl relative z-10 border-4 border-white"
          style={{
            background: 'linear-gradient(135deg, #4ade80 0%, #16a34a 100%)',
            boxShadow: 'inset 0 2px 4px rgba(255,255,255,0.4), 0 4px 12px rgba(22,163,74,0.3)'
          }}
        >
          <CheckCircle2 className="w-12 h-12 stroke-[3px]" />
        </div>
      </div>
      
      <h2 
        className="text-3xl font-black uppercase tracking-tight leading-none mb-2"
        style={{ color: colors2000s.orange.accent }}
      >
        ¡Reserva Confirmada!
      </h2>
      <p className="text-sm font-bold text-gray-500 mb-10">
        Te enviamos los detalles a <span className="font-extrabold text-gray-700">{bookingState.client.email}</span>
      </p>

      <div 
        className="w-full rounded-3xl p-6 text-left border"
        style={{
          background: '#ffffff',
          borderColor: colors2000s.border.light,
          boxShadow: colors2000s.shadows.insetDark
        }}
      >
        <h3 className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-4 ml-1">Detalles del Turno</h3>
        
        <div className="grid gap-4">
          <div className="flex items-center gap-3">
            <div 
              className="p-2.5 rounded-xl border text-orange-500"
              style={{
                background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                borderColor: colors2000s.border.default,
                boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
              }}
            >
              <Calendar size={18} className="stroke-[2.5px]" />
            </div>
            <div>
              <p className="text-[9px] font-black uppercase tracking-wider text-gray-400">Fecha del turno</p>
              <p className="font-black text-gray-700 text-lg leading-tight">{bookingState.date}</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            <div 
              className="p-2.5 rounded-xl border text-blue-500"
              style={{
                background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                borderColor: colors2000s.border.default,
                boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
              }}
            >
              <Clock size={18} className="stroke-[2.5px]" />
            </div>
            <div>
              <p className="text-[9px] font-black uppercase tracking-wider text-gray-400">Hora de inicio</p>
              <p className="font-black text-gray-700 text-lg leading-tight">{bookingState.startTime} hs</p>
            </div>
          </div>
        </div>
      </div>

      <button
        onClick={() => window.location.reload()}
        className="w-full mt-8 text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none"
        style={{
          background: 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)',
          borderColor: '#020617',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15), 0 4px 10px rgba(0,0,0,0.1)'
        }}
      >
        Hacer otra reserva
      </button>
    </div>
  );
};
export default BookingStepConfirmation;
