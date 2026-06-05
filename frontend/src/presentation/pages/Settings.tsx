import React, { useState, useEffect } from "react";
import {
  Store,
  Settings as SettingsIcon,
  Bell,
  Lock,
  Save,
  Check,
  AlertCircle,
  Loader2,
  Calendar,
  Plus,
  Trash2,
  SlidersHorizontal,
} from "lucide-react";
import type { StoreCustomField, StoreCustomFieldOption } from "@application/services/StoreSettingsService";
import { useStoreFeatureFlags, useStoreSettings, useUpdateStoreFeatureFlags, useUpdateStoreSettings } from "../hooks/useStores";
import { useChangePassword } from "../hooks/useChangePassword";
import { colors2000s, buttonStyles2000s } from "../../theme/colors";
import { BUSINESS_TYPE_OPTIONS, getBusinessLabels } from "../lib/businessLabels";

const TABS = [
  { id: "identity", label: "Identidad", icon: <Store className="w-4 h-4" /> },
  { id: "schedule", label: "Horarios", icon: <Calendar className="w-4 h-4" /> },
  { id: "policies", label: "Políticas", icon: <SettingsIcon className="w-4 h-4" /> },
  { id: "notifications", label: "Notificaciones", icon: <Bell className="w-4 h-4" /> },
  { id: "features", label: "Funciones", icon: <SlidersHorizontal className="w-4 h-4" /> },
  { id: "security", label: "Seguridad", icon: <Lock className="w-4 h-4" /> },
];

const DAYS = [
  { id: "mon", label: "Lunes" },
  { id: "tue", label: "Martes" },
  { id: "wed", label: "Miércoles" },
  { id: "thu", label: "Jueves" },
  { id: "fri", label: "Viernes" },
  { id: "sat", label: "Sábado" },
  { id: "sun", label: "Domingo" },
];

const DEFAULT_FEATURE_FLAGS = {
  payments: false,
  ledger: false,
  advanced_reports: false,
  new_calendar: false,
  otp_booking: false,
};

const FEATURE_LABELS = [
  { key: "payments", title: "Cobros online y senas", description: "Mercado Pago, confirmacion manual, devoluciones y actualizacion de pagos." },
  { key: "ledger", title: "Deuda / fiado", description: "Cuenta pendiente por cliente con cargos, pagos, ajustes y devoluciones." },
  { key: "advanced_reports", title: "Reportes avanzados", description: "Metricas por tienda o profesional y exportacion." },
  { key: "new_calendar", title: "Agenda nueva", description: "Disponibilidad con bloqueos, gaps y estados extendidos." },
  { key: "otp_booking", title: "OTP en reserva publica", description: "Validacion por SMS o WhatsApp antes de reservar." },
] as const;

const CUSTOM_FIELD_TYPE_OPTIONS = [
  { value: "text", label: "Texto corto" },
  { value: "textarea", label: "Texto largo" },
  { value: "tel", label: "Telefono" },
  { value: "email", label: "Email" },
  { value: "date", label: "Fecha" },
  { value: "select", label: "Lista" },
] as const;

const createEmptyCustomField = (index: number): StoreCustomField => ({
  key: `campo_${index}`,
  label: "",
  type: "text",
  required: false,
  placeholder: "",
  help_text: "",
  options: [],
});

const serializeFieldOptions = (options: StoreCustomFieldOption[]) =>
  options.map((option) => (option.label === option.value ? option.value : `${option.label}|${option.value}`)).join("\n");

const parseFieldOptions = (rawValue: string): StoreCustomFieldOption[] =>
  rawValue
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [labelPart, valuePart] = line.split("|");
      const label = (labelPart || "").trim();
      const value = (valuePart || labelPart || "").trim();
      return { label, value };
    });

const SettingsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState("identity");
  const { data: store, isLoading } = useStoreSettings();
  const featureFlagsQuery = useStoreFeatureFlags();
  const updateStore = useUpdateStoreSettings();
  const updateFeatureFlags = useUpdateStoreFeatureFlags();
  const changePassword = useChangePassword();

  const [formData, setFormData] = useState<any>(null);
  const [passwordForm, setPasswordForm] = useState({ current: "", new: "", confirm: "" });
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (store) {
      setFormData({
        name: store.name,
        slug: store.slug,
        business_type: store.business_type || "generic",
        logo_url: store.logo_url || "",
        cover_url: store.cover_url || "",
        description: store.description || "",
        whatsapp_number: store.whatsapp_number || "",
        instagram_url: store.instagram_url || "",
        facebook_url: store.facebook_url || "",
        website_url: store.website_url || "",
        custom_client_fields: store.custom_client_fields || [],
        primary_color: store.primary_color,
        cancellation_hours: store.cancellation_hours,
        buffer_minutes: store.buffer_minutes,
        business_hours: store.business_hours,
        send_email_confirmation: store.send_email_confirmation,
        send_email_reminders: store.send_email_reminders,
        feature_flags: featureFlagsQuery.data?.flags || store.feature_flags || DEFAULT_FEATURE_FLAGS,
      });
    }
  }, [store, featureFlagsQuery.data]);

  const labels = getBusinessLabels(formData?.business_type);

  const handleSave = async () => {
    if (!formData) return;
    setSaveStatus("saving");
    try {
      const { feature_flags, ...storePayload } = formData;
      if (activeTab === "features") {
        await updateFeatureFlags.mutateAsync(feature_flags);
      } else {
        await updateStore.mutateAsync(storePayload);
      }
      setSaveStatus("success");
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch (err: any) {
      setSaveStatus("error");
      setErrorMessage(err.response?.data?.detail || "Error al guardar");
    }
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    if (passwordForm.new !== passwordForm.confirm) {
      setErrorMessage("Las contraseñas no coinciden");
      return;
    }
    setSaveStatus("saving");
    try {
      await changePassword.mutateAsync({
        current_password: passwordForm.current,
        new_password: passwordForm.new,
      });
      setSaveStatus("success");
      setPasswordForm({ current: "", new: "", confirm: "" });
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch (err: any) {
      setSaveStatus("error");
      setErrorMessage(err.response?.data?.detail || "Error al cambiar contraseña");
    }
  };

  if (isLoading || !formData) {
    return (
      <div className="flex flex-col items-center justify-center py-20" style={{ color: colors2000s.text.secondary }}>
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: colors2000s.orange.accent }} />
        <p className="mt-4 font-black uppercase tracking-widest text-xs">Cargando configuración...</p>
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
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>Configuración</h1>
        {activeTab !== "security" && (
          <button
            onClick={handleSave}
            disabled={saveStatus === "saving"}
            className="flex items-center gap-2 px-6 py-3 font-black uppercase tracking-widest text-xs rounded-xl transition-all active:scale-95 disabled:opacity-50"
            style={buttonStyles2000s.selected}
          >
            {saveStatus === "saving" ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : saveStatus === "success" ? (
              <Check className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saveStatus === "saving" ? "Guardando..." : saveStatus === "success" ? "Guardado" : "Guardar Cambios"}
          </button>
        )}
      </div>

      {/* Tabs Navigation */}
      <div className="flex gap-2 p-2 rounded-2xl overflow-x-auto no-scrollbar"
           style={{ 
             background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
             border: `1px solid ${colors2000s.border.default}`,
             boxShadow: colors2000s.shadows.insetLight
           }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all whitespace-nowrap"
            style={activeTab === tab.id ? buttonStyles2000s.selected : buttonStyles2000s.default}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {saveStatus === "error" && (
        <div className="p-4 rounded-xl flex items-center gap-3 text-xs font-bold" 
             style={{ background: '#ffeeee', border: '1px solid #ffcccc', color: '#cc0000', boxShadow: colors2000s.shadows.insetDark }}>
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <p>{errorMessage}</p>
        </div>
      )}

      {/* Tab Content */}
      <div className="p-8 rounded-[2.5rem] animate-in fade-in slide-in-from-bottom-4 duration-500"
           style={{ 
             background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
             border: `1px solid ${colors2000s.border.default}`,
             boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
           }}>
        
        {activeTab === "identity" && (
          <div className="space-y-8">
            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Rubro</label>
                <select
                  value={formData.business_type}
                  onChange={(e) => setFormData({ ...formData, business_type: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                >
                  {BUSINESS_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>{labels.businessNameLabel}</label>
                <input
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder={labels.businessNamePlaceholder}
                />
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Slug de la URL</label>
                <div className="flex items-center gap-2 rounded-2xl px-5 py-3.5" style={inputStyle}>
                  <span className="text-xs font-black opacity-30">/booking/</span>
                  <input
                    value={formData.slug}
                    onChange={(e) => setFormData({ ...formData, slug: e.target.value.toLowerCase().replace(/\s+/g, '-') })}
                    className="flex-1 bg-transparent font-black outline-none"
                    placeholder={labels.slugPlaceholder}
                  />
                </div>
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>URL del Logo</label>
                <input
                  value={formData.logo_url}
                  onChange={(e) => setFormData({ ...formData, logo_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="https://..."
                />
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Color de Marca</label>
                <div className="flex items-center gap-4">
                  <input
                    type="color"
                    value={formData.primary_color}
                    onChange={(e) => setFormData({ ...formData, primary_color: e.target.value })}
                    className="w-14 h-14 rounded-2xl bg-white border-none p-1 cursor-pointer shadow-inner"
                    style={{ border: `1px solid ${colors2000s.border.default}` }}
                  />
                  <div className="flex-1 px-5 py-3.5 font-black uppercase tracking-widest rounded-2xl" style={inputStyle}>
                    {formData.primary_color}
                  </div>
                </div>
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>URL de portada</label>
                <input
                  value={formData.cover_url}
                  onChange={(e) => setFormData({ ...formData, cover_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="https://..."
                />
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>WhatsApp</label>
                <input
                  value={formData.whatsapp_number}
                  onChange={(e) => setFormData({ ...formData, whatsapp_number: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="+54911..."
                />
              </div>
            </div>

            <div className="space-y-3">
              <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Descripcion publica</label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full min-h-28 rounded-2xl px-5 py-3.5 font-bold outline-none resize-y"
                style={inputStyle}
                placeholder="Breve descripcion visible en el portal publico."
              />
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Campos extra del booking</label>
                  <p className="text-[11px] font-bold mt-1" style={{ color: colors2000s.text.disabled }}>
                    Define preguntas opcionales o requeridas para el portal publico.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setFormData({
                      ...formData,
                      custom_client_fields: [
                        ...(formData.custom_client_fields || []),
                        createEmptyCustomField((formData.custom_client_fields?.length || 0) + 1),
                      ],
                    })
                  }
                  className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all active:scale-95"
                  style={buttonStyles2000s.default}
                >
                  <Plus className="w-3 h-3 mr-1" />
                  Agregar campo
                </button>
              </div>

              {(formData.custom_client_fields || []).length === 0 ? (
                <div className="p-4 rounded-2xl text-xs font-bold" style={{ background: "white", border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.secondary }}>
                  No hay campos extra configurados. El booking publico va a pedir solo nombre, telefono, email opcional y notas.
                </div>
              ) : (
                <div className="space-y-4">
                  {(formData.custom_client_fields || []).map((field: StoreCustomField, index: number) => (
                    <div
                      key={`${field.key}-${index}`}
                      className="p-5 rounded-[1.5rem] space-y-4"
                      style={{ background: "white", border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.outer }}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Campo #{index + 1}</p>
                          <p className="text-xs font-bold mt-1" style={{ color: colors2000s.text.disabled }}>
                            La clave se usa internamente y conviene mantenerla corta, en minusculas y con guiones bajos.
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setFormData({
                              ...formData,
                              custom_client_fields: (formData.custom_client_fields || []).filter((_: StoreCustomField, fieldIndex: number) => fieldIndex !== index),
                            })
                          }
                          className="p-2 rounded-xl transition-all active:scale-95"
                          style={{ color: "#ef4444" }}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>

                      <div className="grid md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Etiqueta</label>
                          <input
                            value={field.label}
                            onChange={(e) => {
                              const nextFields = [...(formData.custom_client_fields || [])];
                              nextFields[index] = { ...field, label: e.target.value };
                              setFormData({ ...formData, custom_client_fields: nextFields });
                            }}
                            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                            style={inputStyle}
                            placeholder="Ej: Motivo de consulta"
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Clave</label>
                          <input
                            value={field.key}
                            onChange={(e) => {
                              const nextFields = [...(formData.custom_client_fields || [])];
                              nextFields[index] = { ...field, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") };
                              setFormData({ ...formData, custom_client_fields: nextFields });
                            }}
                            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                            style={inputStyle}
                            placeholder="motivo_consulta"
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Tipo</label>
                          <select
                            value={field.type}
                            onChange={(e) => {
                              const nextFields = [...(formData.custom_client_fields || [])];
                              nextFields[index] = { ...field, type: e.target.value as StoreCustomField["type"], options: e.target.value === "select" ? field.options : [] };
                              setFormData({ ...formData, custom_client_fields: nextFields });
                            }}
                            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                            style={inputStyle}
                          >
                            {CUSTOM_FIELD_TYPE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="space-y-2">
                          <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Placeholder</label>
                          <input
                            value={field.placeholder || ""}
                            onChange={(e) => {
                              const nextFields = [...(formData.custom_client_fields || [])];
                              nextFields[index] = { ...field, placeholder: e.target.value };
                              setFormData({ ...formData, custom_client_fields: nextFields });
                            }}
                            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                            style={inputStyle}
                            placeholder="Texto de ayuda dentro del campo"
                          />
                        </div>
                      </div>

                      <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
                        <div className="space-y-2">
                          <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Texto de ayuda</label>
                          <input
                            value={field.help_text || ""}
                            onChange={(e) => {
                              const nextFields = [...(formData.custom_client_fields || [])];
                              nextFields[index] = { ...field, help_text: e.target.value };
                              setFormData({ ...formData, custom_client_fields: nextFields });
                            }}
                            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                            style={inputStyle}
                            placeholder="Ej: Aclaranos si es primera vez o seguimiento"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            const nextFields = [...(formData.custom_client_fields || [])];
                            nextFields[index] = { ...field, required: !field.required };
                            setFormData({ ...formData, custom_client_fields: nextFields });
                          }}
                          className="mt-7 px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all active:scale-95"
                          style={field.required ? buttonStyles2000s.selected : buttonStyles2000s.default}
                        >
                          {field.required ? "Obligatorio" : "Opcional"}
                        </button>
                      </div>

                      {field.type === "select" && (
                        <div className="space-y-2">
                          <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Opciones</label>
                          <textarea
                            value={serializeFieldOptions(field.options || [])}
                            onChange={(e) => {
                              const nextFields = [...(formData.custom_client_fields || [])];
                              nextFields[index] = { ...field, options: parseFieldOptions(e.target.value) };
                              setFormData({ ...formData, custom_client_fields: nextFields });
                            }}
                            className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
                            style={inputStyle}
                            placeholder={"Una opcion por linea\nEj: Primera vez|primera_vez"}
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Instagram</label>
                <input
                  value={formData.instagram_url}
                  onChange={(e) => setFormData({ ...formData, instagram_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="https://instagram.com/..."
                />
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Facebook</label>
                <input
                  value={formData.facebook_url}
                  onChange={(e) => setFormData({ ...formData, facebook_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="https://facebook.com/..."
                />
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Sitio web</label>
                <input
                  value={formData.website_url}
                  onChange={(e) => setFormData({ ...formData, website_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="https://..."
                />
              </div>
            </div>
          </div>
        )}

        {activeTab === "schedule" && (
          <div className="space-y-6">
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>Horarios de Atención</h3>
            <div className="space-y-3">
              {DAYS.map((day) => {
                const dayHours = formData.business_hours[day.id] || [];
                return (
                  <div key={day.id} className="flex flex-col md:flex-row md:items-center gap-4 p-4 rounded-2xl transition-all"
                       style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.outer }}>
                    <div className="w-24 font-black uppercase tracking-widest text-[10px]" style={{ color: colors2000s.text.primary }}>{day.label}</div>

                    <div className="flex-1 space-y-2">
                      {dayHours.length === 0 ? (
                        <span className="text-[10px] font-black uppercase italic" style={{ color: colors2000s.text.disabled }}>Cerrado</span>
                      ) : (
                        dayHours.map((period: any, idx: number) => (
                          <div key={idx} className="flex items-center gap-2">
                            <input
                              type="time"
                              value={period.open}
                              onChange={(e) => {
                                const newHours = { ...formData.business_hours };
                                newHours[day.id][idx].open = e.target.value;
                                setFormData({ ...formData, business_hours: newHours });
                              }}
                              className="rounded-lg px-2 py-1 text-[11px] font-black uppercase outline-none"
                              style={inputStyle}
                            />
                            <span className="text-[10px] font-bold" style={{ color: colors2000s.text.disabled }}>A</span>
                            <input
                              type="time"
                              value={period.close}
                              onChange={(e) => {
                                const newHours = { ...formData.business_hours };
                                newHours[day.id][idx].close = e.target.value;
                                setFormData({ ...formData, business_hours: newHours });
                              }}
                              className="rounded-lg px-2 py-1 text-[11px] font-black uppercase outline-none"
                              style={inputStyle}
                            />
                            <button
                              onClick={() => {
                                const newHours = { ...formData.business_hours };
                                newHours[day.id].splice(idx, 1);
                                setFormData({ ...formData, business_hours: newHours });
                              }}
                              className="p-1.5 transition-all"
                              style={{ color: '#ef4444' }}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ))
                      )}
                    </div>

                    <button
                      onClick={() => {
                        const newHours = { ...formData.business_hours };
                        if (!newHours[day.id]) newHours[day.id] = [];
                        newHours[day.id].push({ open: "09:00", close: "18:00" });
                        setFormData({ ...formData, business_hours: newHours });
                      }}
                      className="px-3 py-2 rounded-xl text-[9px] font-black uppercase tracking-widest transition-all active:scale-95"
                      style={buttonStyles2000s.default}
                    >
                      <Plus className="w-3 h-3 mr-1" />
                      Bloque
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {activeTab === "policies" && (
          <div className="space-y-8">
            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Cancelación (Horas)</label>
                <input
                  type="number"
                  value={formData.cancellation_hours}
                  onChange={(e) => setFormData({ ...formData, cancellation_hours: parseInt(e.target.value) || 0 })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="24"
                />
                <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.disabled }}>Antelación mínima permitida para cancelar.</p>
              </div>
              <div className="space-y-3">
                <label className="block text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Buffer entre turnos (min)</label>
                <input
                  type="number"
                  value={formData.buffer_minutes}
                  onChange={(e) => setFormData({ ...formData, buffer_minutes: parseInt(e.target.value) || 0 })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                  placeholder="0"
                />
                <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.disabled }}>Tiempo de limpieza/descanso automático.</p>
              </div>
            </div>
          </div>
        )}

        {activeTab === "notifications" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between p-6 rounded-[2rem] transition-all"
                 style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.outer }}>
              <div className="space-y-1">
                <p className="font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>Email de Confirmación</p>
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Enviar al confirmar reserva.</p>
              </div>
              <button
                onClick={() => setFormData({ ...formData, send_email_confirmation: !formData.send_email_confirmation })}
                className="w-14 h-7 rounded-full relative transition-all"
                style={{ 
                  background: formData.send_email_confirmation ? colors2000s.orange.light : colors2000s.bg.disabled,
                  boxShadow: colors2000s.shadows.insetDark,
                  border: `1px solid ${colors2000s.border.default}`
                }}
              >
                <div className="absolute top-1 w-5 h-5 rounded-full transition-all shadow-md"
                     style={{ 
                       background: 'white', 
                       left: formData.send_email_confirmation ? '32px' : '4px',
                       boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                     }} />
              </button>
            </div>

            <div className="flex items-center justify-between p-6 rounded-[2rem] transition-all"
                 style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.outer }}>
              <div className="space-y-1">
                <p className="font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>Recordatorios 24hs</p>
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Aviso automático un día antes.</p>
              </div>
              <button
                onClick={() => setFormData({ ...formData, send_email_reminders: !formData.send_email_reminders })}
                className="w-14 h-7 rounded-full relative transition-all"
                style={{ 
                  background: formData.send_email_reminders ? colors2000s.orange.light : colors2000s.bg.disabled,
                  boxShadow: colors2000s.shadows.insetDark,
                  border: `1px solid ${colors2000s.border.default}`
                }}
              >
                <div className="absolute top-1 w-5 h-5 rounded-full transition-all shadow-md"
                     style={{ 
                       background: 'white', 
                       left: formData.send_email_reminders ? '32px' : '4px',
                       boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                     }} />
              </button>
            </div>
          </div>
        )}

        {activeTab === "features" && (
          <div className="space-y-6">
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>Funciones por tenant</h3>
            {FEATURE_LABELS.map((feature) => {
              const enabled = Boolean(formData.feature_flags?.[feature.key]);
              return (
                <div
                  key={feature.key}
                  className="flex items-center justify-between gap-6 p-6 rounded-[2rem] transition-all"
                  style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.outer }}
                >
                  <div className="space-y-1">
                    <p className="font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>{feature.title}</p>
                    <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>{feature.description}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setFormData({
                        ...formData,
                        feature_flags: {
                          ...formData.feature_flags,
                          [feature.key]: !enabled,
                        },
                      })
                    }
                    className="w-14 h-7 rounded-full relative transition-all flex-shrink-0"
                    style={{
                      background: enabled ? colors2000s.orange.light : colors2000s.bg.disabled,
                      boxShadow: colors2000s.shadows.insetDark,
                      border: `1px solid ${colors2000s.border.default}`,
                    }}
                  >
                    <div
                      className="absolute top-1 w-5 h-5 rounded-full transition-all shadow-md"
                      style={{
                        background: 'white',
                        left: enabled ? '32px' : '4px',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
                      }}
                    />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {activeTab === "security" && (
          <form onSubmit={handlePasswordChange} className="max-w-md space-y-6">
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>Seguridad</h3>
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Contraseña Actual</label>
                <input
                  type="password"
                  required
                  value={passwordForm.current}
                  onChange={(e) => setPasswordForm({ ...passwordForm, current: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                />
              </div>

              <div className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Nueva Contraseña</label>
                <input
                  type="password"
                  required
                  value={passwordForm.new}
                  onChange={(e) => setPasswordForm({ ...passwordForm, new: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                />
              </div>

              <div className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Confirmar Nueva</label>
                <input
                  type="password"
                  required
                  value={passwordForm.confirm}
                  onChange={(e) => setPasswordForm({ ...passwordForm, confirm: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={inputStyle}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={saveStatus === "saving"}
              className="w-full py-4 rounded-2xl font-black uppercase tracking-widest text-sm transition-all active:scale-[0.98] disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {saveStatus === "saving" ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : "Actualizar Acceso"}
            </button>
          </form>
        )}
      </div>

      <div className="p-6 rounded-[2rem]" style={{ background: '#fffbeb', border: '1px solid #fef3c7', boxShadow: colors2000s.shadows.outer }}>
        <div className="flex gap-4">
          <AlertCircle className="w-6 h-6 text-amber-500 flex-shrink-0" />
          <div className="space-y-1">
            <h4 className="font-black text-xs uppercase tracking-widest" style={{ color: '#d97706' }}>Atención: Zona Crítica</h4>
            <p className="text-[10px] font-bold leading-relaxed" style={{ color: '#b45309' }}>
              Modificar el <strong>Slug</strong> invalidará el link de reserva compartido anteriormente. Asegúrate de notificar a tus clientes.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
