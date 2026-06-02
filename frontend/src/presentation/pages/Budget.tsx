import React, { useMemo, useState } from "react";
import { Calculator, Edit3, Loader2, Plus, Trash2, X } from "lucide-react";
import type { BudgetItem, BudgetPayload } from "../hooks/useBudgets";
import { useBudgets, useCreateBudget, useUpdateBudget, useDeleteBudget } from "../hooks/useBudgets";
import { colors2000s, buttonStyles2000s } from "../../theme/colors";

const initialForm: BudgetPayload = {
  title: "",
  improvement_description: "",
  estimated_hours: 1,
  hourly_rate: 1,
  currency: "ARS",
  status: "draft",
  notes: "",
};

const BudgetPage: React.FC = () => {
  const [includeInactive, setIncludeInactive] = useState(false);
  const { data, isLoading } = useBudgets(includeInactive);

  const createMutation = useCreateBudget();
  const updateMutation = useUpdateBudget();
  const deleteMutation = useDeleteBudget();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingBudget, setEditingBudget] = useState<BudgetItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formData, setFormData] = useState<BudgetPayload>(initialForm);

  const estimatedTotal = useMemo(
    () => Number(formData.estimated_hours || 0) * Number(formData.hourly_rate || 0),
    [formData.estimated_hours, formData.hourly_rate]
  );

  const resetForm = () => {
    setIsModalOpen(false);
    setEditingBudget(null);
    setFormData(initialForm);
    setError(null);
  };

  const openCreate = () => {
    setEditingBudget(null);
    setFormData(initialForm);
    setError(null);
    setIsModalOpen(true);
  };

  const openEdit = (budget: BudgetItem) => {
    setEditingBudget(budget);
    setFormData({
      title: budget.title,
      improvement_description: budget.improvement_description,
      estimated_hours: Number(budget.estimated_hours),
      hourly_rate: Number(budget.hourly_rate),
      currency: budget.currency,
      status: budget.status,
      notes: budget.notes || "",
    });
    setError(null);
    setIsModalOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      if (editingBudget) {
        await updateMutation.mutateAsync({
          publicId: editingBudget.public_id,
          payload: formData,
        });
      } else {
        await createMutation.mutateAsync(formData);
      }
      resetForm();
    } catch (err: any) {
      setError(err.response?.data?.detail || "No se pudo guardar el presupuesto");
    }
  };

  const handleDelete = async (budget: BudgetItem) => {
    if (!confirm(`¿Seguro que querés desactivar el presupuesto ${budget.title}?`)) {
      return;
    }
    await deleteMutation.mutateAsync(budget.public_id);
  };

  if (isLoading) {
    return (
      <div className="h-[60vh] flex flex-col items-center justify-center gap-3" style={{ color: colors2000s.text.secondary }}>
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: colors2000s.orange.accent }} />
        <p className="font-black uppercase tracking-widest text-xs">Cargando presupuestos...</p>
      </div>
    );
  }

  const inputStyle = {
    background: 'white',
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    color: colors2000s.text.primary,
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-3xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>Presupuesto</h2>
          <p className="text-sm font-bold" style={{ color: colors2000s.text.secondary }}>Define mejoras, horas, valor hora y costo total.</p>
        </div>
        <div className="flex items-center gap-6">
          <label className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2 cursor-pointer" style={{ color: colors2000s.text.secondary }}>
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(e) => setIncludeInactive(e.target.checked)}
              className="w-4 h-4 rounded border-gray-300 text-orange-600 focus:ring-orange-500"
            />
            Inactivos
          </label>
          <button
            onClick={openCreate}
            className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs transition-all active:scale-95 group"
            style={buttonStyles2000s.selected}
          >
            <Plus className="w-5 h-5 group-hover:rotate-90 transition-transform duration-300" />
            Nuevo Presupuesto
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {data?.map((budget) => (
          <div key={budget.public_id} className="rounded-[2.5rem] p-6 space-y-4 group transition-all relative overflow-hidden active:scale-[0.98]"
               style={{ 
                 background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                 border: `1px solid ${colors2000s.border.default}`,
                 boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
               }}>
            <div className="flex justify-between items-start gap-3">
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-black uppercase tracking-tight truncate" style={{ color: colors2000s.text.primary }}>{budget.title}</h3>
                <p className="text-xs font-medium line-clamp-2 mt-1" style={{ color: colors2000s.text.secondary }}>{budget.improvement_description}</p>
              </div>
              <span className="px-2 py-1 rounded font-black text-[9px] uppercase tracking-widest"
                    style={{ background: colors2000s.bg.disabled, color: colors2000s.text.secondary, border: `1px solid ${colors2000s.border.light}` }}>
                {budget.status}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-3 text-xs">
              <div className="rounded-xl p-3" style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
                <p className="text-[9px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.disabled }}>Horas</p>
                <p className="font-black" style={{ color: colors2000s.text.primary }}>{budget.estimated_hours}</p>
              </div>
              <div className="rounded-xl p-3" style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
                <p className="text-[9px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.disabled }}>Valor Hora</p>
                <p className="font-black" style={{ color: colors2000s.text.primary }}>{budget.hourly_rate}</p>
              </div>
              <div className="rounded-xl p-3" style={{ background: '#f0fdf4', border: `1px solid #bbf7d0`, boxShadow: 'inset 0 2px 4px rgba(22,163,74,0.1)' }}>
                <p className="text-[9px] font-black uppercase tracking-widest" style={{ color: '#16a34a' }}>Total</p>
                <p className="font-black" style={{ color: '#15803d' }}>${budget.total_cost}</p>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t" style={{ borderColor: colors2000s.border.light }}>
              <button onClick={() => openEdit(budget)} className="p-2.5 rounded-xl transition-all" style={buttonStyles2000s.default}>
                <Edit3 className="w-4.5 h-4.5" />
              </button>
              <button onClick={() => handleDelete(budget)} className="p-2.5 rounded-xl transition-all" style={{ ...buttonStyles2000s.default, color: '#ef4444' }}>
                <Trash2 className="w-4.5 h-4.5" />
              </button>
            </div>
          </div>
        ))}
      </div>

      {(data?.length ?? 0) === 0 && (
        <div className="bg-white/50 border-2 border-dashed rounded-[3rem] p-20 text-center" style={{ borderColor: colors2000s.border.default }}>
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-inner" style={{ background: colors2000s.bg.disabled }}>
            <Calculator className="w-8 h-8 opacity-20" style={{ color: colors2000s.text.primary }} />
          </div>
          <h3 className="text-xl font-black uppercase" style={{ color: colors2000s.text.primary }}>No hay presupuestos</h3>
          <p className="text-sm font-bold max-w-xs mx-auto mb-8" style={{ color: colors2000s.text.secondary }}>Crea tu primera propuesta de mejora.</p>
          <button onClick={openCreate} className="font-black uppercase tracking-widest text-xs" style={{ color: colors2000s.orange.accent }}>
            Nuevo Presupuesto
          </button>
        </div>
      )}

      {isModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={resetForm} />
          <div className="relative w-full max-w-xl rounded-[2.5rem] p-8 shadow-2xl animate-in zoom-in-95 duration-200 overflow-y-auto max-h-[90vh]"
               style={{ background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`, border: `1px solid ${colors2000s.border.default}` }}>
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-xl font-black uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>
                {editingBudget ? "Editar Presupuesto" : "Nuevo Presupuesto"}
              </h3>
              <button onClick={resetForm} style={{ color: colors2000s.text.disabled }}>
                <X className="w-6 h-6" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-[10px] font-black uppercase tracking-widest mb-2" style={{ color: colors2000s.text.secondary }}>Título de mejora</label>
                <input
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  className="w-full rounded-xl px-4 py-3 font-bold outline-none"
                  style={inputStyle}
                  required
                />
              </div>

              <div>
                <label className="block text-[10px] font-black uppercase tracking-widest mb-2" style={{ color: colors2000s.text.secondary }}>Descripción</label>
                <textarea
                  value={formData.improvement_description}
                  onChange={(e) => setFormData({ ...formData, improvement_description: e.target.value })}
                  className="w-full rounded-xl px-4 py-3 font-medium outline-none h-24 resize-none"
                  style={inputStyle}
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[10px] font-black uppercase tracking-widest mb-2" style={{ color: colors2000s.text.secondary }}>Horas estimadas</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    value={formData.estimated_hours}
                    onChange={(e) => setFormData({ ...formData, estimated_hours: Number(e.target.value) })}
                    className="w-full rounded-xl px-4 py-3 font-bold outline-none"
                    style={inputStyle}
                    required
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-black uppercase tracking-widest mb-2" style={{ color: colors2000s.text.secondary }}>Valor hora (ARS)</label>
                  <input
                    type="number"
                    step="1"
                    min="1"
                    value={formData.hourly_rate}
                    onChange={(e) => setFormData({ ...formData, hourly_rate: Number(e.target.value) })}
                    className="w-full rounded-xl px-4 py-3 font-bold outline-none"
                    style={inputStyle}
                    required
                  />
                </div>
              </div>

              <div className="p-4 rounded-2xl text-center font-black uppercase tracking-widest text-xs shadow-inner"
                   style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, color: colors2000s.orange.accent }}>
                Total estimado: {formData.currency} {estimatedTotal.toFixed(2)}
              </div>

              <div>
                <label className="block text-[10px] font-black uppercase tracking-widest mb-2" style={{ color: colors2000s.text.secondary }}>Notas adicionales</label>
                <textarea
                  value={formData.notes || ""}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  className="w-full rounded-xl px-4 py-3 font-medium outline-none h-20 resize-none"
                  style={inputStyle}
                />
              </div>

              {error && <div className="p-3 rounded-xl text-xs font-bold" style={{ background: '#ffeeee', color: '#cc0000', border: '1px solid #ffcccc' }}>{error}</div>}

              <button
                type="submit"
                disabled={createMutation.isPending || updateMutation.isPending}
                className="w-full font-black py-4 rounded-xl transition-all uppercase tracking-widest text-sm active:scale-[0.98]"
                style={buttonStyles2000s.selected}
              >
                {createMutation.isPending || updateMutation.isPending ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : "Guardar Presupuesto"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default BudgetPage;
