import React, { useEffect, useMemo, useState } from "react";
import { AlertCircle, CreditCard, ExternalLink, Loader2, RefreshCcw, Save } from "lucide-react";

import {
  useCreatePromotion,
  useCreatePaymentPreference,
  useGatewayConfig,
  useManualConfirmPayment,
  useOutboxStats,
  usePaymentsAppointments,
  useProcessOutbox,
  usePromotions,
  useReconciliationSummary,
  useRefundPayment,
  useUpdatePromotion,
  useUpsertGatewayConfig,
} from "../hooks/usePayments";
import { useAuth } from "../context/AuthContext";
import { ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN } from "../context/roles";
import { buttonStyles2000s, colors2000s } from "../../theme/colors";

const currencyFmt = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  maximumFractionDigits: 0,
});

const createEmptyPromotionForm = () => ({
  code: "",
  title: "",
  description: "",
  promotion_type: "percent" as "percent" | "fixed",
  value: "",
  min_service_amount: "",
  max_uses: "",
  valid_from: "",
  valid_until: "",
  is_active: true,
});

const PaymentsPage: React.FC = () => {
  const { user } = useAuth();
  const canManagePromotions = user?.role === ROLE_STORE_ADMIN || user?.role === ROLE_SUPER_ADMIN;
  const gatewayQuery = useGatewayConfig();
  const appointmentsQuery = usePaymentsAppointments();
  const summaryQuery = useReconciliationSummary();
  const outboxStatsQuery = useOutboxStats();
  const promotionsQuery = usePromotions(canManagePromotions, true);
  const upsertGateway = useUpsertGatewayConfig();
  const createPreference = useCreatePaymentPreference();
  const createPromotion = useCreatePromotion();
  const manualConfirm = useManualConfirmPayment();
  const refundPayment = useRefundPayment();
  const processOutbox = useProcessOutbox();
  const updatePromotion = useUpdatePromotion();

  const [gatewayForm, setGatewayForm] = useState({
    provider: "mercadopago" as "mercadopago" | "stripe",
    access_token: "",
    public_key: "",
    webhook_secret: "",
  });
  const [refundForm, setRefundForm] = useState({
    paymentId: "",
    amount: "",
    reason: "",
  });
  const [promotionForm, setPromotionForm] = useState(createEmptyPromotionForm());
  const [editingPromotionId, setEditingPromotionId] = useState<string | null>(null);
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    if (gatewayQuery.data) {
      setGatewayForm((prev) => ({
        ...prev,
        provider: (gatewayQuery.data.provider as "mercadopago" | "stripe") || "mercadopago",
        public_key: gatewayQuery.data.public_key || "",
      }));
    }
  }, [gatewayQuery.data]);

  const summaryCards = useMemo(() => {
    const summary = summaryQuery.data;
    return [
      { label: "Pendientes", value: summary?.pending_payments ?? 0 },
      { label: "Aprobados", value: summary?.approved_payments ?? 0 },
      { label: "Manuales", value: summary?.manual_confirmed_payments ?? 0 },
      { label: "Total aprobado", value: currencyFmt.format(Number(summary?.total_approved_amount ?? 0)) },
    ];
  }, [summaryQuery.data]);

  const handleSaveGateway = async () => {
    try {
      const response = await upsertGateway.mutateAsync({
        ...gatewayForm,
        access_token: gatewayForm.access_token.trim() || undefined,
      });
      setMessage(`Gateway configurado: ${response.provider}`);
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo guardar la configuración");
    }
  };

  const handleCreatePreference = async (appointmentId: string) => {
    try {
      const response = await createPreference.mutateAsync(appointmentId);
      setRefundForm((prev) => ({ ...prev, paymentId: response.payment_public_id }));
      setMessage(`Preferencia creada: ${response.payment_public_id}`);
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo crear la preferencia");
    }
  };

  const handleManualConfirm = async (appointmentId: string) => {
    try {
      const response = await manualConfirm.mutateAsync({ appointmentId });
      setRefundForm((prev) => ({ ...prev, paymentId: response.public_id }));
      setMessage(`Pago confirmado manualmente: ${response.public_id}`);
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo confirmar el pago");
    }
  };

  const handleRefund = async () => {
    try {
      const response = await refundPayment.mutateAsync({
        paymentId: refundForm.paymentId,
        amount: refundForm.amount ? Number(refundForm.amount) : undefined,
        reason: refundForm.reason || undefined,
        manual: true,
      });
      setMessage(`Pago devuelto: ${response.public_id}`);
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo procesar el refund");
    }
  };

  const handleProcessOutbox = async () => {
    try {
      const response = await processOutbox.mutateAsync(100);
      setMessage(`Outbox procesado: ${response.processed} mensajes`);
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo procesar el outbox");
    }
  };

  const handleSavePromotion = async () => {
    try {
      const payload = {
        code: promotionForm.code.trim().toUpperCase(),
        title: promotionForm.title.trim(),
        description: promotionForm.description.trim() || undefined,
        promotion_type: promotionForm.promotion_type,
        value: Number(promotionForm.value),
        min_service_amount: promotionForm.min_service_amount ? Number(promotionForm.min_service_amount) : undefined,
        max_uses: promotionForm.max_uses ? Number(promotionForm.max_uses) : undefined,
        valid_from: promotionForm.valid_from || undefined,
        valid_until: promotionForm.valid_until || undefined,
        is_active: promotionForm.is_active,
      };

      if (editingPromotionId) {
        const response = await updatePromotion.mutateAsync({
          promotionId: editingPromotionId,
          payload,
        });
        setMessage(`Promocion actualizada: ${response.code}`);
      } else {
        const response = await createPromotion.mutateAsync(payload);
        setMessage(`Promocion creada: ${response.code}`);
      }
      setEditingPromotionId(null);
      setPromotionForm(createEmptyPromotionForm());
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo guardar la promocion");
    }
  };

  const handleEditPromotion = (promotion: any) => {
    const toInputDate = (value?: string | null) => (value ? value.slice(0, 16) : "");
    setEditingPromotionId(promotion.public_id);
    setPromotionForm({
      code: promotion.code,
      title: promotion.title,
      description: promotion.description || "",
      promotion_type: promotion.promotion_type,
      value: String(promotion.value ?? ""),
      min_service_amount: promotion.min_service_amount != null ? String(promotion.min_service_amount) : "",
      max_uses: promotion.max_uses != null ? String(promotion.max_uses) : "",
      valid_from: toInputDate(promotion.valid_from),
      valid_until: toInputDate(promotion.valid_until),
      is_active: promotion.is_active,
    });
  };

  const handleTogglePromotion = async (promotion: any) => {
    try {
      const response = await updatePromotion.mutateAsync({
        promotionId: promotion.public_id,
        payload: { is_active: !promotion.is_active },
      });
      setMessage(`Promocion ${response.code} ${response.is_active ? "activada" : "pausada"}`);
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo actualizar la promocion");
    }
  };

  const cardStyle = {
    background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`,
  };
  const inputStyle = {
    background: "white",
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    color: colors2000s.text.primary,
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="p-6 rounded-3xl flex flex-wrap items-start justify-between gap-4" style={cardStyle}>
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
            Pagos
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Configuración de gateway, preferencias de cobro, confirmación manual y conciliación.
          </p>
        </div>
        {(gatewayQuery.isLoading || summaryQuery.isLoading) && (
          <div className="flex items-center gap-2 text-xs font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
            <Loader2 className="w-4 h-4 animate-spin" />
            Cargando pagos...
          </div>
        )}
      </div>

      {message && (
        <div className="p-4 rounded-2xl text-sm font-bold flex items-center gap-3" style={{ background: "#fff7ed", border: "1px solid #fed7aa", color: "#c2410c" }}>
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{message}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {summaryCards.map((card) => (
          <div key={card.label} className="p-5 rounded-2xl" style={cardStyle}>
            <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>{card.label}</p>
            <p className="mt-2 text-2xl font-black" style={{ color: colors2000s.orange.accent }}>{card.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
              Gateway
            </h3>
            <button type="button" onClick={handleSaveGateway} className="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest" style={buttonStyles2000s.selected}>
              <Save className="w-4 h-4 inline mr-2" />
              Guardar
            </button>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Proveedor</label>
              <select
                value={gatewayForm.provider}
                onChange={(e) => setGatewayForm((prev) => ({ ...prev, provider: e.target.value as "mercadopago" | "stripe" }))}
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
              >
                <option value="mercadopago">Mercado Pago</option>
                <option value="stripe">Stripe</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Public key</label>
              <input
                value={gatewayForm.public_key}
                onChange={(e) => setGatewayForm((prev) => ({ ...prev, public_key: e.target.value }))}
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="APP_USR..."
              />
            </div>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Access token</label>
              <input
                value={gatewayForm.access_token}
                onChange={(e) => setGatewayForm((prev) => ({ ...prev, access_token: e.target.value }))}
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder={gatewayQuery.data?.configured ? "********" : "Ingresá el token"}
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Webhook secret</label>
              <input
                value={gatewayForm.webhook_secret}
                onChange={(e) => setGatewayForm((prev) => ({ ...prev, webhook_secret: e.target.value }))}
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="opcional"
              />
            </div>
          </div>
          <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
            Estado actual: {gatewayQuery.data?.configured ? "configurado" : "sin configurar"}
          </p>
        </div>

        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
              Operación
            </h3>
            <button type="button" onClick={handleProcessOutbox} className="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
              <RefreshCcw className="w-4 h-4 inline mr-2" />
              Procesar outbox
            </button>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-2xl p-4 bg-white" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">Pendientes</p>
              <p className="mt-2 text-xl font-black" style={{ color: colors2000s.orange.accent }}>{outboxStatsQuery.data?.pending ?? 0}</p>
            </div>
            <div className="rounded-2xl p-4 bg-white" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">Con error</p>
              <p className="mt-2 text-xl font-black text-red-500">{outboxStatsQuery.data?.pending_with_error ?? 0}</p>
            </div>
            <div className="rounded-2xl p-4 bg-white" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">Procesados</p>
              <p className="mt-2 text-xl font-black text-green-600">{outboxStatsQuery.data?.processed ?? 0}</p>
            </div>
          </div>
          <div className="space-y-3">
            <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Refund manual</label>
            <input value={refundForm.paymentId} onChange={(e) => setRefundForm((prev) => ({ ...prev, paymentId: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder="payment_public_id" />
            <input value={refundForm.amount} onChange={(e) => setRefundForm((prev) => ({ ...prev, amount: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder="Monto opcional" />
            <textarea value={refundForm.reason} onChange={(e) => setRefundForm((prev) => ({ ...prev, reason: e.target.value }))} className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y" style={inputStyle} placeholder="Motivo del refund" />
            <button type="button" onClick={handleRefund} disabled={!refundForm.paymentId} className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50" style={buttonStyles2000s.selected}>
              Ejecutar refund
            </button>
          </div>
        </div>
      </div>

      {canManagePromotions && (
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.1fr] gap-6">
        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
                Promociones
              </h3>
              <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                Codigos que el cliente puede aplicar antes de reservar.
              </p>
            </div>
            <button
              type="button"
              onClick={handleSavePromotion}
              className="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest"
              style={buttonStyles2000s.selected}
            >
              <Save className="w-4 h-4 inline mr-2" />
              {editingPromotionId ? "Actualizar" : "Crear"}
            </button>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Codigo</label>
              <input value={promotionForm.code} onChange={(e) => setPromotionForm((prev) => ({ ...prev, code: e.target.value.toUpperCase() }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder="BIENVENIDA10" />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Titulo</label>
              <input value={promotionForm.title} onChange={(e) => setPromotionForm((prev) => ({ ...prev, title: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder="Descuento primera visita" />
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Descripcion</label>
            <textarea value={promotionForm.description} onChange={(e) => setPromotionForm((prev) => ({ ...prev, description: e.target.value }))} className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y" style={inputStyle} placeholder="Visible para el equipo interno y util para entender la promo." />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Tipo</label>
              <select value={promotionForm.promotion_type} onChange={(e) => setPromotionForm((prev) => ({ ...prev, promotion_type: e.target.value as "percent" | "fixed" }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle}>
                <option value="percent">Porcentaje</option>
                <option value="fixed">Monto fijo</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Valor</label>
              <input type="number" min="0" step="0.01" value={promotionForm.value} onChange={(e) => setPromotionForm((prev) => ({ ...prev, value: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder={promotionForm.promotion_type === "percent" ? "10" : "2000"} />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Compra minima</label>
              <input type="number" min="0" step="0.01" value={promotionForm.min_service_amount} onChange={(e) => setPromotionForm((prev) => ({ ...prev, min_service_amount: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder="Opcional" />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Limite de usos</label>
              <input type="number" min="1" step="1" value={promotionForm.max_uses} onChange={(e) => setPromotionForm((prev) => ({ ...prev, max_uses: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} placeholder="Opcional" />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Desde</label>
              <input type="datetime-local" value={promotionForm.valid_from} onChange={(e) => setPromotionForm((prev) => ({ ...prev, valid_from: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Hasta</label>
              <input type="datetime-local" value={promotionForm.valid_until} onChange={(e) => setPromotionForm((prev) => ({ ...prev, valid_until: e.target.value }))} className="w-full rounded-2xl px-4 py-3 font-bold outline-none" style={inputStyle} />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-2xl p-4 bg-white" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">Activa</p>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>La promo queda visible para el booking publico.</p>
            </div>
            <button type="button" onClick={() => setPromotionForm((prev) => ({ ...prev, is_active: !prev.is_active }))} className="w-14 h-7 rounded-full relative transition-all" style={{ background: promotionForm.is_active ? colors2000s.orange.light : colors2000s.bg.disabled, boxShadow: colors2000s.shadows.insetDark, border: `1px solid ${colors2000s.border.default}` }}>
              <div className="absolute top-1 w-5 h-5 rounded-full transition-all shadow-md" style={{ background: "white", left: promotionForm.is_active ? "32px" : "4px", boxShadow: "0 2px 4px rgba(0,0,0,0.2)" }} />
            </button>
          </div>

          {editingPromotionId && (
            <button type="button" onClick={() => { setEditingPromotionId(null); setPromotionForm(createEmptyPromotionForm()); }} className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
              Cancelar edicion
            </button>
          )}
        </div>

        <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
              Promos activas e historicas
            </h3>
            {promotionsQuery.isLoading && <Loader2 className="w-4 h-4 animate-spin" style={{ color: colors2000s.text.secondary }} />}
          </div>
          <div className="space-y-3">
            {promotionsQuery.data?.map((promotion: any) => (
              <div key={promotion.public_id} className="rounded-2xl p-4 bg-white flex flex-col gap-4" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>{promotion.title}</p>
                    <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>
                      {promotion.code} · {promotion.promotion_type === "percent" ? `${promotion.value}%` : currencyFmt.format(Number(promotion.value))}
                    </p>
                    {promotion.description && (
                      <p className="text-xs font-bold mt-2" style={{ color: colors2000s.text.secondary }}>
                        {promotion.description}
                      </p>
                    )}
                  </div>
                  <span className="px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest" style={{ background: promotion.is_active ? "#ecfdf5" : "#f3f4f6", color: promotion.is_active ? "#15803d" : "#6b7280", border: `1px solid ${promotion.is_active ? "#bbf7d0" : "#d1d5db"}` }}>
                    {promotion.is_active ? "Activa" : "Pausada"}
                  </span>
                </div>
                <div className="grid md:grid-cols-3 gap-3 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                  <span>Usos: {promotion.current_uses}{promotion.max_uses ? ` / ${promotion.max_uses}` : ""}</span>
                  <span>Minimo: {promotion.min_service_amount ? currencyFmt.format(Number(promotion.min_service_amount)) : "sin minimo"}</span>
                  <span>Vence: {promotion.valid_until ? new Date(promotion.valid_until).toLocaleString("es-AR") : "sin fecha"}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => handleEditPromotion(promotion)} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
                    Editar
                  </button>
                  <button type="button" onClick={() => handleTogglePromotion(promotion)} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={promotion.is_active ? buttonStyles2000s.selected : buttonStyles2000s.default}>
                    {promotion.is_active ? "Pausar" : "Reactivar"}
                  </button>
                </div>
              </div>
            ))}
            {!promotionsQuery.data?.length && !promotionsQuery.isLoading && (
              <div className="rounded-2xl p-6 bg-white text-sm font-bold" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.secondary }}>
                Todavia no hay promociones configuradas.
              </div>
            )}
          </div>
        </div>
      </div>
      )}

      <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
        <div className="flex items-center gap-3">
          <CreditCard className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
          <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
            Turnos recientes para cobrar
          </h3>
        </div>
        <div className="space-y-3">
          {appointmentsQuery.data?.slice(0, 12).map((appointment) => (
            <div key={appointment.public_id} className="rounded-2xl p-4 bg-white flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
              <div>
                <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>{appointment.client_name}</p>
                <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
                  {appointment.service_name} · {appointment.staff_name} · {new Date(appointment.starts_at).toLocaleString("es-AR")}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => handleCreatePreference(appointment.public_id)} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
                  Crear link
                </button>
                <button type="button" onClick={() => handleManualConfirm(appointment.public_id)} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={buttonStyles2000s.selected}>
                  Confirmar manual
                </button>
                {createPreference.data?.appointment_id === appointment.public_id && createPreference.data.payment_link && (
                  <a href={createPreference.data.payment_link} target="_blank" rel="noreferrer" className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2" style={buttonStyles2000s.default}>
                    Abrir link
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>
            </div>
          ))}
          {!appointmentsQuery.data?.length && !appointmentsQuery.isLoading && (
            <div className="rounded-2xl p-6 bg-white text-sm font-bold" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.secondary }}>
              No hay turnos disponibles para operar pagos.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PaymentsPage;
