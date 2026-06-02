import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { ArrowRight, Store, User, Sparkles } from "lucide-react";
import { mdiStore, mdiShieldAlert } from "@mdi/js";
import { Icon2000s, LucideIcon2000s } from "../components/legacy/Icon2000s";
import { colors2000s, buttonStyles2000s } from "../../theme/colors";
import { BUSINESS_TYPE_OPTIONS, getBusinessLabels } from "../lib/businessLabels";
import { useRegisterBusiness } from "../hooks/useRegisterBusiness";

const RegisterPage: React.FC = () => {
  const [formData, setFormData] = useState({
    store_name: "",
    store_slug: "",
    business_type: "generic" as const,
    admin_email: "",
    admin_password: "",
    admin_first_name: "",
    admin_last_name: "",
  });
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const labels = getBusinessLabels(formData.business_type);
  const registerMutation = useRegisterBusiness();

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nameVal = e.target.value;
    const computedSlug = nameVal
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9\s-]/g, "")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .trim();

    setFormData((prev) => {
      const isSlugEmptyOrAutoMatched =
        prev.store_slug === "" ||
        prev.store_slug ===
          prev.store_name
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/[^a-z0-9\s-]/g, "")
            .replace(/\s+/g, "-")
            .replace(/-+/g, "-")
            .trim();

      return {
        ...prev,
        store_name: nameVal,
        store_slug: isSlugEmptyOrAutoMatched ? computedSlug : prev.store_slug,
      };
    });
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    try {
      await registerMutation.mutateAsync(formData);
      navigate("/login?registered=true");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Error al registrar el negocio");
    }
  };

  const inputStyle = {
    background: "white",
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    color: colors2000s.text.primary,
  };

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center relative overflow-y-auto py-12 px-4"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`,
      }}
    >
      <div className="w-full max-w-2xl relative z-10 my-auto">
        <div className="flex flex-col items-center mb-8 text-center">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 rotate-3 relative overflow-hidden"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              boxShadow: `${colors2000s.shadows.outerOrange}, 0 8px 24px rgba(200,90,15,0.3)`,
              border: `1px solid ${colors2000s.orange.accent}`,
            }}
          >
            <div className="absolute top-0 left-0 right-0 h-1/2 bg-white/20 pointer-events-none" />
            <Icon2000s path={mdiStore} size={30} variant="active" />
          </div>

          <div
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full border mb-3 text-xs font-bold uppercase tracking-wider"
            style={{
              background: "#ffffff",
              borderColor: colors2000s.border.default,
              color: colors2000s.orange.accent,
              boxShadow: colors2000s.shadows.outer,
            }}
          >
            <Sparkles className="w-3.5 h-3.5 animate-pulse" />
            Empeza hoy tu prueba gratuita
          </div>

          <h1 className="text-3xl md:text-4xl font-black tracking-tight" style={{ color: colors2000s.orange.accent }}>
            Registra tu negocio
          </h1>
          <p className="text-sm font-medium mt-1" style={{ color: colors2000s.text.secondary }}>
            Configura tu agenda profesional multi-tenant en segundos
          </p>
        </div>

        <div
          className="p-8 md:p-10 rounded-3xl"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`,
          }}
        >
          <form onSubmit={handleSubmit} className="space-y-8">
            <div className="space-y-4">
              <h2
                className="text-sm font-bold uppercase tracking-widest flex items-center gap-2 pb-2 border-b"
                style={{ color: colors2000s.orange.accent, borderColor: colors2000s.border.light }}
              >
                <LucideIcon2000s icon={Store} size={18} variant="pressed" />
                Informacion del negocio
              </h2>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    Rubro
                  </label>
                  <select
                    name="business_type"
                    value={formData.business_type}
                    onChange={handleChange}
                    className="w-full rounded-xl px-4 py-3 outline-none transition-all focus:border-[#ff8c42]"
                    style={inputStyle}
                  >
                    {BUSINESS_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    {labels.businessNameLabel}
                  </label>
                  <input
                    name="store_name"
                    value={formData.store_name}
                    onChange={handleNameChange}
                    className="w-full rounded-xl px-4 py-3 outline-none transition-all focus:border-[#ff8c42]"
                    style={inputStyle}
                    placeholder={labels.businessNamePlaceholder}
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    URL personalizada (Slug)
                  </label>
                  <div className="relative flex items-center">
                    <span className="absolute left-4 font-bold text-xs pointer-events-none" style={{ color: colors2000s.text.disabled }}>
                      shifty.app/
                    </span>
                    <input
                      name="store_slug"
                      value={formData.store_slug}
                      onChange={handleChange}
                      className="w-full rounded-xl pl-24 pr-4 py-3 outline-none font-mono text-sm transition-all focus:border-[#ff8c42]"
                      style={inputStyle}
                      placeholder={labels.slugPlaceholder}
                      required
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-4 pt-4">
              <h2
                className="text-sm font-bold uppercase tracking-widest flex items-center gap-2 pb-2 border-b"
                style={{ color: colors2000s.orange.accent, borderColor: colors2000s.border.light }}
              >
                <LucideIcon2000s icon={User} size={18} variant="pressed" />
                Cuenta de Administrador
              </h2>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    Nombre
                  </label>
                  <input
                    name="admin_first_name"
                    value={formData.admin_first_name}
                    onChange={handleChange}
                    className="w-full rounded-xl px-4 py-3 outline-none transition-all focus:border-[#ff8c42]"
                    style={inputStyle}
                    placeholder="Ana"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    Apellido
                  </label>
                  <input
                    name="admin_last_name"
                    value={formData.admin_last_name}
                    onChange={handleChange}
                    className="w-full rounded-xl px-4 py-3 outline-none transition-all focus:border-[#ff8c42]"
                    style={inputStyle}
                    placeholder="Perez"
                    required
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    Email Corporativo
                  </label>
                  <input
                    name="admin_email"
                    type="email"
                    value={formData.admin_email}
                    onChange={handleChange}
                    className="w-full rounded-xl px-4 py-3 outline-none transition-all focus:border-[#ff8c42]"
                    style={inputStyle}
                    placeholder="hola@tuempresa.com"
                    required
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors2000s.text.secondary }}>
                    Contrasena del Administrador
                  </label>
                  <input
                    name="admin_password"
                    type="password"
                    value={formData.admin_password}
                    onChange={handleChange}
                    className="w-full rounded-xl px-4 py-3 outline-none transition-all focus:border-[#ff8c42]"
                    style={inputStyle}
                    placeholder="Minimo 8 caracteres"
                    required
                  />
                </div>
              </div>
            </div>

            {error && (
              <div
                className="text-sm p-4 rounded-xl flex items-center gap-2.5"
                style={{
                  background: "#ffeeee",
                  border: "1px solid #ffcccc",
                  color: "#cc0000",
                  boxShadow: colors2000s.shadows.insetDark,
                }}
              >
                <Icon2000s path={mdiShieldAlert} size={18} variant="idle" color="#cc0000" />
                <span className="font-medium">{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={registerMutation.isPending}
              className="w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50 group"
              style={registerMutation.isPending ? buttonStyles2000s.disabled : buttonStyles2000s.selected}
            >
              {registerMutation.isPending ? (
                "Creando negocio..."
              ) : (
                <>
                  Crear mi cuenta y empezar
                  <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 text-center" style={{ borderTop: `1px solid ${colors2000s.border.light}` }}>
            <p className="text-sm" style={{ color: colors2000s.text.secondary }}>
              Ya tenes una cuenta creada?{" "}
              <Link to="/login" className="font-bold transition-colors" style={{ color: colors2000s.orange.accent }}>
                Inicia Sesion
              </Link>
            </p>
          </div>
        </div>

        <p className="mt-8 text-center text-xs" style={{ color: colors2000s.text.disabled }}>
          Copyright 2026 Shifty SaaS. Todos los derechos reservados.
        </p>
      </div>
    </div>
  );
};

export default RegisterPage;
