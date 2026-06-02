import React, { useState, useEffect } from "react";
import { User } from "@domain/entities/User";
import { X, Loader2 } from "lucide-react";
import { colors2000s, buttonStyles2000s } from "../../../theme/colors";

interface UserFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: any) => Promise<void>;
  editingUser?: User | null;
}

export const UserFormModal: React.FC<UserFormModalProps> = ({ isOpen, onClose, onSubmit, editingUser }) => {
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    email: "",
    password: "",
    first_name: "",
    last_name: "",
    phone: "",
    role: "staff" as "admin" | "staff" | "client",
  });

  useEffect(() => {
    if (editingUser) {
      const p = editingUser.toPrimitives();
      setFormData({
        email: p.email,
        password: "",
        first_name: p.firstName || "",
        last_name: p.lastName || "",
        phone: p.phone || "",
        role: p.role,
      });
    } else {
      setFormData({
        email: "",
        password: "",
        first_name: "",
        last_name: "",
        phone: "",
        role: "staff",
      });
    }
  }, [editingUser, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await onSubmit(formData);
      onClose();
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = {
    background: 'white',
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    color: colors2000s.text.primary,
    outline: 'none',
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={onClose} />
      <div 
        className="relative w-full max-w-lg rounded-[2.5rem] border animate-in zoom-in-95 duration-200 p-8 overflow-y-auto max-h-[90vh]"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
        }}
      >
        <div className="flex justify-between items-center mb-8">
          <div>
            <h3 className="text-2xl font-black uppercase tracking-tight text-gray-800" style={{ color: colors2000s.text.primary }}>
              {editingUser ? "Editar Usuario" : "Nuevo Usuario"}
            </h3>
            <p className="text-xs font-bold text-gray-500" style={{ color: colors2000s.text.secondary }}>Gestioná los permisos y datos del personal.</p>
          </div>
          <button 
            onClick={onClose} 
            className="w-10 h-10 rounded-full flex items-center justify-center transition-all active:scale-90"
            style={buttonStyles2000s.default}
          >
            <X size={20} className="text-gray-500" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">Email de Acceso</label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              disabled={Boolean(editingUser)}
              className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
              style={editingUser ? { ...inputStyle, background: colors2000s.bg.disabled, opacity: 0.7 } : inputStyle}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">Nombre</label>
              <input
                value={formData.first_name}
                onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={inputStyle}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">Apellido</label>
              <input
                value={formData.last_name}
                onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={inputStyle}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">Rol</label>
              <select
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value as any })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all appearance-none cursor-pointer"
                style={inputStyle}
              >
                <option value="admin">Administrador</option>
                <option value="staff">Staff / Profesional</option>
                <option value="client">Cliente</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">Teléfono</label>
              <input
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={inputStyle}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
              {editingUser ? "Cambiar Contraseña (opcional)" : "Contraseña"}
            </label>
            <input
              type="password"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
              style={inputStyle}
              required={!editingUser}
            />
          </div>

          <div className="flex gap-4 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-4 rounded-xl font-black uppercase tracking-widest text-xs transition-all active:scale-95"
              style={buttonStyles2000s.default}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin mx-auto" />
              ) : (
                editingUser ? "Guardar Cambios" : "Crear Usuario"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
