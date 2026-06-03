import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Building2,
  CreditCard,
  Filter,
  Loader2,
  Search,
  Shield,
  Tag,
  Users,
} from "lucide-react";

import { buttonStyles2000s, colors2000s } from "../../theme/colors";
import {
  useSuperAdminCoupons,
  useSuperAdminOverview,
  useSuperAdminPlans,
  useSuperAdminStores,
} from "../hooks/useSuperAdmin";

type ActivityFilter = "active" | "inactive" | "all";
type SubscriptionFilter = "all" | "with" | "without";

const money = (value: string | number, currency = "ARS") =>
  new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value || 0));

const formatDate = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("es-AR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      }).format(new Date(value))
    : "Sin fecha";

const formatDateTime = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("es-AR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "Sin actividad";

const scopeBadgeStyle = (variant: "global" | "tenant" | "danger") => {
  if (variant === "global") {
    return {
      background: "#eff6ff",
      border: "1px solid #bfdbfe",
      color: "#1d4ed8",
    };
  }
  if (variant === "danger") {
    return {
      background: "#fff1f2",
      border: "1px solid #fecdd3",
      color: "#be123c",
    };
  }
  return {
    background: "#fff7ed",
    border: `1px solid ${colors2000s.orange.light}`,
    color: colors2000s.orange.accent,
  };
};

const panelStyle = {
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`,
};

const innerCardStyle = {
  background: "white",
  border: `1px solid ${colors2000s.border.light}`,
  boxShadow: colors2000s.shadows.outer,
};

const emptyStateStyle = {
  background: "white",
  border: `1px dashed ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.insetDark,
};

const disabledActionStyle = {
  ...buttonStyles2000s.disabled,
  borderRadius: "14px",
  padding: "12px 16px",
  fontSize: "10px",
  fontWeight: 900,
  letterSpacing: "0.12em",
  textTransform: "uppercase" as const,
};

const roleLabel = (role: string, isGlobalAdmin: boolean) => {
  if (isGlobalAdmin) return "Super Admin";
  if (role === "admin") return "Admin";
  if (role === "staff") return "Profesional";
  if (role === "receptionist") return "Recepción";
  return "Usuario";
};

const statusLabel = (active: boolean) => (active ? "Activa" : "Inactiva");

const SuperAdminPage: React.FC = () => {
  const [search, setSearch] = useState("");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("active");
  const [subscriptionFilter, setSubscriptionFilter] = useState<SubscriptionFilter>("all");
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);

  const storeParams = useMemo(
    () => ({
      search: search.trim() || undefined,
      is_active:
        activityFilter === "all" ? null : activityFilter === "active",
      has_subscription:
        subscriptionFilter === "all" ? null : subscriptionFilter === "with",
    }),
    [activityFilter, search, subscriptionFilter]
  );

  const storesQuery = useSuperAdminStores(storeParams);
  const overviewQuery = useSuperAdminOverview(selectedStoreId);
  const plansQuery = useSuperAdminPlans();
  const couponsQuery = useSuperAdminCoupons();

  useEffect(() => {
    if (!storesQuery.data?.length) {
      setSelectedStoreId(null);
      return;
    }
    const selectedExists = storesQuery.data.some((store) => store.public_id === selectedStoreId);
    if (!selectedExists) {
      setSelectedStoreId(storesQuery.data[0].public_id);
    }
  }, [selectedStoreId, storesQuery.data]);

  const selectedStore = useMemo(
    () => storesQuery.data?.find((store) => store.public_id === selectedStoreId) ?? null,
    [selectedStoreId, storesQuery.data]
  );

  const overview = overviewQuery.data;

  return (
    <div className="space-y-6">
      <section className="rounded-[2rem] p-6" style={panelStyle}>
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("global")}>
                Scope Global
              </span>
              <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("tenant")}>
                Tienda Seleccionada
              </span>
            </div>
            <div>
              <h1 className="text-3xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
                Control Global
              </h1>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                Operación multi-tenant para tiendas, admins, suscripciones y cupones.
              </p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {[
              "Editar tienda",
              selectedStore?.is_active ? "Desactivar tienda" : "Activar tienda",
              "Crear admin",
              "Asignar plan",
              "Canjear cupón",
            ].map((label, index) => (
              <button
                key={label}
                type="button"
                disabled
                title="Flujo visual preparado. Wiring mutacional pendiente."
                style={index === 1 ? { ...disabledActionStyle, color: "#b91c1c" } : disabledActionStyle}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 rounded-[1.75rem] p-5" style={innerCardStyle}>
          {selectedStore ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
                <div>
                  <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Tienda activa</p>
                  <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>{selectedStore.name}</p>
                </div>
                <div>
                  <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Estado</p>
                  <span className="inline-flex rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={selectedStore.is_active ? scopeBadgeStyle("tenant") : scopeBadgeStyle("danger")}>
                    {statusLabel(selectedStore.is_active)}
                  </span>
                </div>
                <div>
                  <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Slug</p>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>{selectedStore.slug}</p>
                </div>
                <div>
                  <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Color de marca</p>
                  <div className="mt-1 flex items-center gap-3">
                    <span className="h-5 w-5 rounded-full border" style={{ background: selectedStore.primary_color, borderColor: colors2000s.border.default }} />
                    <span className="font-black" style={{ color: colors2000s.text.primary }}>{selectedStore.primary_color}</span>
                  </div>
                </div>
                <div>
                  <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Suscripción</p>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>
                    {selectedStore.current_plan_name || "Sin suscripción"}
                  </p>
                </div>
              </div>

              <div className="rounded-2xl px-4 py-3" style={{ ...scopeBadgeStyle("danger"), boxShadow: colors2000s.shadows.outer }}>
                <p className="text-[10px] font-black uppercase tracking-widest">Safeguards</p>
                <p className="mt-1 text-[11px] font-bold">
                  Revocar Super Admin, desactivar tienda, reemplazar suscripción y canjear cupón son flujos de cuidado.
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
              <Building2 className="mx-auto mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                No hay tienda seleccionada
              </p>
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_420px]">
        <div className="space-y-6">
          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("global")}>
                    Tiendas
                  </span>
                </div>
                <h2 className="text-2xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
                  Operación por tenant
                </h2>
                <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                  Filtros directos por estado y suscripción para triage operativo rápido.
                </p>
              </div>

              <div className="flex flex-col gap-3 md:flex-row md:items-center">
                <div className="relative">
                  <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: colors2000s.text.disabled }} />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Buscar por nombre o slug"
                    className="w-full rounded-2xl py-3 pl-11 pr-4 text-sm font-bold outline-none md:w-72"
                    style={{ ...innerCardStyle, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }}
                  />
                </div>

                <div className="flex items-center gap-2 rounded-2xl p-2" style={innerCardStyle}>
                  <Filter className="h-4 w-4" style={{ color: colors2000s.text.secondary }} />
                  {[
                    { value: "active", label: "Activas" },
                    { value: "inactive", label: "Inactivas" },
                    { value: "all", label: "Todas" },
                  ].map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setActivityFilter(item.value as ActivityFilter)}
                      className="rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                      style={activityFilter === item.value ? buttonStyles2000s.selected : buttonStyles2000s.default}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-2 rounded-2xl p-2" style={innerCardStyle}>
                  {[
                    { value: "all", label: "Todas" },
                    { value: "with", label: "Con suscripción" },
                    { value: "without", label: "Sin suscripción" },
                  ].map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setSubscriptionFilter(item.value as SubscriptionFilter)}
                      className="rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                      style={subscriptionFilter === item.value ? buttonStyles2000s.selected : buttonStyles2000s.default}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-6 overflow-hidden rounded-[1.75rem]" style={innerCardStyle}>
              {storesQuery.isLoading ? (
                <div className="flex items-center justify-center gap-3 p-10" style={{ color: colors2000s.text.secondary }}>
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span className="font-bold">Cargando tiendas...</span>
                </div>
              ) : storesQuery.data?.length ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left">
                    <thead style={{ background: colors2000s.bg.disabled }}>
                      <tr>
                        {["Tienda", "Estado", "Usuarios", "Suscripción", "Renueva", "Último canje"].map((label) => (
                          <th key={label} className="px-4 py-3 text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {storesQuery.data.map((store) => {
                        const isSelected = store.public_id === selectedStoreId;
                        return (
                          <tr
                            key={store.public_id}
                            onClick={() => setSelectedStoreId(store.public_id)}
                            className="cursor-pointer transition-colors"
                            style={{
                              background: isSelected ? "#fff7ed" : "transparent",
                              borderTop: `1px solid ${colors2000s.border.light}`,
                            }}
                          >
                            <td className="px-4 py-4">
                              <div className="flex items-center gap-3">
                                <span className="h-4 w-4 rounded-full border" style={{ background: store.primary_color, borderColor: colors2000s.border.default }} />
                                <div>
                                  <p className="font-black" style={{ color: colors2000s.text.primary }}>{store.name}</p>
                                  <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                                    {store.slug}
                                  </p>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-4">
                              <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={store.is_active ? scopeBadgeStyle("tenant") : scopeBadgeStyle("danger")}>
                                {statusLabel(store.is_active)}
                              </span>
                            </td>
                            <td className="px-4 py-4">
                              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                                {store.active_users_count}/{store.users_count}
                              </p>
                              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                                {store.admins_count} admins
                              </p>
                            </td>
                            <td className="px-4 py-4">
                              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                                {store.current_plan_name || "Sin plan"}
                              </p>
                              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                                {store.subscription_status || "Sin suscripción"}
                              </p>
                            </td>
                            <td className="px-4 py-4 text-sm font-bold" style={{ color: colors2000s.text.primary }}>
                              {formatDate(store.current_period_end)}
                            </td>
                            <td className="px-4 py-4 text-sm font-bold" style={{ color: colors2000s.text.primary }}>
                              {formatDateTime(store.last_redemption_at)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="rounded-[1.5rem] p-10 text-center" style={emptyStateStyle}>
                  <Building2 className="mx-auto mb-3 h-10 w-10 opacity-25" />
                  <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                    No hay tiendas para este filtro
                  </p>
                  <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                    Ajustá búsqueda, estado o suscripción para recuperar resultados.
                  </p>
                </div>
              )}
            </div>
          </section>

          <div className="grid gap-6 xl:grid-cols-2">
            <section className="rounded-[2rem] p-6" style={panelStyle}>
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("global")}>
                    Planes
                  </span>
                  <h2 className="mt-2 text-xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
                    Catálogo global
                  </h2>
                </div>
                <button type="button" disabled style={disabledActionStyle}>Crear plan</button>
              </div>
              <div className="space-y-3">
                {plansQuery.data?.map((plan) => (
                  <div key={plan.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-black" style={{ color: colors2000s.text.primary }}>{plan.name}</p>
                        <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                          {plan.billing_interval} · {money(plan.price, plan.currency)}
                        </p>
                      </div>
                      <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={plan.is_active ? scopeBadgeStyle("global") : scopeBadgeStyle("danger")}>
                        {plan.is_active ? "Activo" : "Inactivo"}
                      </span>
                    </div>
                    <div className="mt-4 grid grid-cols-3 gap-3 text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                      <div>Max staff: <span style={{ color: colors2000s.text.primary }}>{plan.max_staff ?? "Libre"}</span></div>
                      <div>Max services: <span style={{ color: colors2000s.text.primary }}>{plan.max_services ?? "Libre"}</span></div>
                      <div>Billing: <span style={{ color: colors2000s.text.primary }}>{plan.billing_interval}</span></div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-[2rem] p-6" style={panelStyle}>
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("global")}>
                    Cupones
                  </span>
                  <h2 className="mt-2 text-xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
                    Maestro editable
                  </h2>
                </div>
                <button type="button" disabled style={disabledActionStyle}>Crear cupón</button>
              </div>
              <div className="space-y-3">
                {couponsQuery.data?.length ? (
                  couponsQuery.data.map((coupon) => (
                    <div key={coupon.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-black" style={{ color: colors2000s.text.primary }}>{coupon.code}</p>
                          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                            {coupon.coupon_type} · {coupon.value}{coupon.coupon_type === "percent" ? "%" : ` ${coupon.currency || ""}`}
                          </p>
                        </div>
                        <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={coupon.is_active ? scopeBadgeStyle("global") : scopeBadgeStyle("danger")}>
                          {coupon.current_uses} usos
                        </span>
                      </div>
                      <p className="mt-3 text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                        Vigencia: {formatDate(coupon.valid_from)} a {formatDate(coupon.valid_until)}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                    <Tag className="mx-auto mb-3 h-10 w-10 opacity-25" />
                    <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                      Cupón sin usos todavía
                    </p>
                    <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                      El catálogo está listo, pero no hay campañas activas con historial.
                    </p>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>

        <aside className="space-y-6 xl:sticky xl:top-8 xl:self-start">
          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="mb-4 flex items-center justify-between">
              <div>
                <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("tenant")}>
                  Admins y Usuarios
                </span>
                <h2 className="mt-2 text-xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
                  Detalle del tenant
                </h2>
              </div>
              {overviewQuery.isFetching && <Loader2 className="h-4 w-4 animate-spin" style={{ color: colors2000s.orange.accent }} />}
            </div>

            {!overview && overviewQuery.isLoading ? (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin" />
                <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                  Cargando contexto
                </p>
              </div>
            ) : overview ? (
              <div className="space-y-4">
                <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                  <div className="mb-3 flex items-center gap-2">
                    <Shield className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
                    <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Admins</p>
                  </div>
                  {overview.users.admins.length ? (
                    <div className="space-y-3">
                      {overview.users.admins.map((user) => (
                        <div key={user.public_id} className="rounded-2xl p-3" style={{ background: colors2000s.bg.button }}>
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                                {[user.first_name, user.last_name].filter(Boolean).join(" ") || user.email}
                              </p>
                              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                                {user.email}
                              </p>
                            </div>
                            <span className="rounded-full px-2 py-1 text-[10px] font-black uppercase tracking-widest" style={user.is_global_admin ? scopeBadgeStyle("danger") : scopeBadgeStyle("tenant")}>
                              {roleLabel(user.role, user.is_global_admin)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-[1.25rem] p-6 text-center" style={emptyStateStyle}>
                      <Shield className="mx-auto mb-3 h-8 w-8 opacity-25" />
                      <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                        No hay admins creados
                      </p>
                    </div>
                  )}
                </div>

                <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                  <div className="mb-3 flex items-center gap-2">
                    <Users className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
                    <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                      Usuarios
                    </p>
                  </div>
                  <div className="mb-3 grid grid-cols-3 gap-2 text-center">
                    {[
                      { label: "Admins", value: overview.users.admins_count },
                      { label: "Usuarios", value: overview.users.users_count },
                      { label: "Activos", value: overview.users.active_users_count },
                    ].map((item) => (
                      <div key={item.label} className="rounded-2xl p-3" style={{ background: colors2000s.bg.button }}>
                        <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>{item.value}</p>
                        <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>{item.label}</p>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    {overview.users.users.map((user) => (
                      <div key={user.public_id} className="flex items-center justify-between rounded-2xl px-3 py-2" style={{ background: colors2000s.bg.button }}>
                        <div>
                          <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                            {[user.first_name, user.last_name].filter(Boolean).join(" ") || user.email}
                          </p>
                          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                            {roleLabel(user.role, user.is_global_admin)}
                          </p>
                        </div>
                        {user.is_global_admin ? (
                          <BadgeCheck className="h-4 w-4" style={{ color: "#be123c" }} />
                        ) : (
                          <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: user.is_active ? "#15803d" : "#b91c1c" }}>
                            {user.is_active ? "Activo" : "Inactivo"}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <Users className="mx-auto mb-3 h-10 w-10 opacity-25" />
                <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                  Seleccioná una tienda
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="mb-4 flex items-center gap-2">
              <CreditCard className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
              <div>
                <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("tenant")}>
                  Suscripción
                </span>
              </div>
            </div>
            {overview?.subscription ? (
              <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-black" style={{ color: colors2000s.text.primary }}>
                      {overview.subscription.plan_name || "Plan sin nombre"}
                    </p>
                    <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                      {overview.subscription.status} · {overview.subscription.billing_interval}
                    </p>
                  </div>
                  <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("tenant")}>
                    {money(overview.subscription.total_amount, overview.subscription.currency)}
                  </span>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                  <div>Base: <span style={{ color: colors2000s.text.primary }}>{money(overview.subscription.base_amount, overview.subscription.currency)}</span></div>
                  <div>Descuento: <span style={{ color: colors2000s.text.primary }}>{money(overview.subscription.discount_amount, overview.subscription.currency)}</span></div>
                  <div>Max staff: <span style={{ color: colors2000s.text.primary }}>{overview.subscription.max_staff ?? "Libre"}</span></div>
                  <div>Max services: <span style={{ color: colors2000s.text.primary }}>{overview.subscription.max_services ?? "Libre"}</span></div>
                  <div>Inicio: <span style={{ color: colors2000s.text.primary }}>{formatDate(overview.subscription.current_period_start)}</span></div>
                  <div>Fin: <span style={{ color: colors2000s.text.primary }}>{formatDate(overview.subscription.current_period_end)}</span></div>
                </div>
                <div className="mt-4 rounded-2xl p-3" style={{ background: colors2000s.bg.button }}>
                  <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                    Cupón aplicado
                  </p>
                  <p className="mt-1 font-black" style={{ color: colors2000s.text.primary }}>
                    {overview.subscription.applied_coupon?.code || "Sin cupón aplicado"}
                  </p>
                </div>
              </div>
            ) : (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <CreditCard className="mx-auto mb-3 h-10 w-10 opacity-25" />
                <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                  Esta tienda no tiene suscripción
                </p>
                <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                  El panel está listo para asignar plan cuando se habilite el flujo mutacional.
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="mb-4 flex items-center gap-2">
              <Tag className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
              <div>
                <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("tenant")}>
                  Canjes
                </span>
              </div>
            </div>
            {overview?.recent_redemptions.length ? (
              <div className="space-y-3">
                {overview.recent_redemptions.map((redemption) => (
                  <div key={redemption.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-black" style={{ color: colors2000s.text.primary }}>{redemption.code_snapshot}</p>
                        <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                          {redemption.coupon_type_snapshot} · {formatDateTime(redemption.created_at)}
                        </p>
                      </div>
                      <span className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest" style={scopeBadgeStyle("tenant")}>
                        -{money(redemption.discount_amount, redemption.currency)}
                      </span>
                    </div>
                    <p className="mt-3 text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                      Final: <span style={{ color: colors2000s.text.primary }}>{money(redemption.final_amount, redemption.currency)}</span>
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
                <Tag className="mx-auto mb-3 h-10 w-10 opacity-25" />
                <p className="text-sm font-black uppercase tracking-widest" style={{ color: colors2000s.text.primary }}>
                  No hay canjes recientes
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[2rem] p-6" style={panelStyle}>
            <div className="flex items-start gap-3 rounded-[1.5rem] p-4" style={{ ...scopeBadgeStyle("danger"), boxShadow: colors2000s.shadows.outer }}>
              <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0" />
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest">Danger / Safeguard States</p>
                <p className="mt-2 text-xs font-bold">
                  La UI diferencia acciones globales, acciones sobre tienda seleccionada y operaciones delicadas para evitar errores de tenant.
                </p>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
};

export default SuperAdminPage;
