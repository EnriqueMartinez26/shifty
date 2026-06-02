import React, { useState } from "react";
import { ChevronLeft, FileText, Mail, Phone, User } from "lucide-react";

import { colors2000s } from "../../../../theme/colors";

interface BookingStepClientProps {
  clientData: {
    name: string;
    email: string;
    phone: string;
    notes: string;
  };
  onBack: () => void;
  onSubmit: (data: any) => void;
}

export const BookingStepClient: React.FC<BookingStepClientProps> = ({ clientData, onBack, onSubmit }) => {
  const [formData, setFormData] = useState(clientData);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formData);
  };

  const inputStyle = {
    background: "#ffffff",
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    borderRadius: "12px",
    color: colors2000s.text.primary,
    fontFamily: "inherit",
    outline: "none",
    transition: "all 0.15s",
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={onBack}
          type="button"
          className="p-2 rounded-full transition-all active:scale-90 flex items-center justify-center border"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
            color: colors2000s.text.primary,
          }}
        >
          <ChevronLeft size={20} className="stroke-[3px]" />
        </button>
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>
            Tus Datos
          </h2>
          <p className="text-sm font-bold text-gray-500">Para registrar tu reserva.</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="relative">
          <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">Nombre Completo</label>
          <div className="relative">
            <User size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full pl-12 pr-4 py-3.5 font-bold"
              style={inputStyle}
              placeholder="Ej: Juan Perez"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div className="relative">
            <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">Email (Opcional)</label>
            <div className="relative">
              <Mail size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="w-full pl-12 pr-4 py-3.5 font-bold"
                style={inputStyle}
                placeholder="juan@email.com"
              />
            </div>
          </div>

          <div className="relative">
            <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">Telefono</label>
            <div className="relative">
              <Phone size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="tel"
                required
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full pl-12 pr-4 py-3.5 font-bold"
                style={inputStyle}
                placeholder="11 2345 6789"
              />
            </div>
          </div>
        </div>

        <div className="relative">
          <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 block mb-1">Notas Adicionales (Opcional)</label>
          <div className="relative">
            <FileText size={18} className="absolute left-4 top-4 text-gray-400" />
            <textarea
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="w-full pl-12 pr-4 py-3.5 font-bold min-h-[100px] resize-none"
              style={inputStyle}
              placeholder="Algo que debamos saber?"
            />
          </div>
        </div>

        <button
          type="submit"
          className="w-full mt-6 text-white font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
            borderColor: colors2000s.orange.accent,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`,
          }}
        >
          Continuar
        </button>
      </form>
    </div>
  );
};

export default BookingStepClient;
