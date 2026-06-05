import { useMemo } from "react";
import type { CSSProperties, ReactNode } from "react";
import { format, subDays } from "date-fns";
import { useNavigate } from "react-router-dom";

import type { ProfessionalReportItem, ReportTopServiceItem } from "@application/services/ReportsService";
import type { UpcomingAppointment } from "@application/services/DashboardService";

import { useAuth } from "../context/AuthContext";
import { ROLE_PROFESSIONAL, ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN } from "../context/roles";
import { useDashboardSummary } from "../hooks/useDashboard";
import { useLedgerSummary } from "../hooks/useLedger";
import { useOutboxStats, useReconciliationSummary } from "../hooks/usePayments";
import { useProfessionalReports, useReportSummary } from "../hooks/useReports";
import { useStoreFeatureFlags } from "../hooks/useStores";

type Tone = "neutral" | "primary" | "warning" | "danger" | "success";

type MetricItem = {
  id: string;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
  onSelect?: () => void;
};

type ActionItem = {
  id: string;
  title: string;
  description?: string;
  meta?: string;
  tone?: Tone;
  onSelect?: () => void;
};

type AgendaItem = {
  id: string;
  time: string;
  title: string;
  subtitle?: string;
  status?: string;
  tone?: Tone;
};

type RankedItem = {
  id: string;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
};

type DashboardCopy = {
  actionsTitle: string;
  agendaTitle: string;
  moneyTitle: string;
  performanceTitle: string;
  alertsTitle: string;
  emptyActions: string;
  emptyAgenda: string;
  emptyAlerts: string;
};

type EnterpriseDashboardProps = {
  copy: DashboardCopy;
  todayMetrics: MetricItem[];
  urgentActions: ActionItem[];
  agenda: AgendaItem[];
  moneyMetrics: MetricItem[];
  performanceItems: RankedItem[];
  alerts: ActionItem[];
  isLoading: boolean;
  errorMessage?: string;
};

const carbon = {
  blue: "#0F62FE",
  black: "#161616",
  gray90: "#262626",
  gray80: "#393939",
  gray60: "#6F6F6F",
  gray30: "#C6C6C6",
  gray20: "#E0E0E0",
  gray10: "#F4F4F4",
  white: "#FFFFFF",
  danger: "#DA1E28",
  warning: "#F1C21B",
  success: "#24A148",
};

const currencyFormatter = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat("es-AR", {
  maximumFractionDigits: 0,
});

const percentFormatter = new Intl.NumberFormat("es-AR", {
  maximumFractionDigits: 1,
});

const dashboardCopy: DashboardCopy = {
  actionsTitle: "Acciones urgentes",
  agendaTitle: "Agenda operacional",
  moneyTitle: "Dinero",
  performanceTitle: "Rendimiento",
  alertsTitle: "Alertas",
  emptyActions: "No hay acciones urgentes.",
  emptyAgenda: "No hay turnos proximos para mostrar.",
  emptyAlerts: "No hay alertas activas.",
};

const pageStyle: CSSProperties = {
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  color: carbon.black,
  display: "grid",
  gap: 24,
};

const metricGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(184px, 1fr))",
  gap: 16,
};

const dashboardLayoutStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(240px, 1fr) minmax(320px, 1.65fr) minmax(240px, 1fr)",
  gap: 16,
  alignItems: "start",
};

const panelStyle: CSSProperties = {
  background: carbon.white,
  border: `1px solid ${carbon.gray20}`,
  borderRadius: 8,
  minWidth: 0,
};

const panelHeaderStyle: CSSProperties = {
  padding: 16,
  borderBottom: `1px solid ${carbon.gray20}`,
};

const panelTitleStyle: CSSProperties = {
  margin: 0,
  color: carbon.black,
  fontSize: 14,
  lineHeight: "20px",
  fontWeight: 600,
  letterSpacing: 0,
};

const panelBodyStyle: CSSProperties = {
  padding: 16,
};

const listStyle: CSSProperties = {
  display: "grid",
  gap: 8,
};

const emptyStyle: CSSProperties = {
  margin: 0,
  padding: 16,
  background: carbon.gray10,
  borderRadius: 8,
  color: carbon.gray60,
  fontSize: 12,
  lineHeight: "16px",
};

const toneBorder = (tone: Tone = "neutral") => {
  if (tone === "primary") return carbon.blue;
  if (tone === "warning") return carbon.warning;
  if (tone === "danger") return carbon.danger;
  if (tone === "success") return carbon.success;
  return carbon.gray20;
};

const formatCurrency = (value: number | string | null | undefined) =>
  currencyFormatter.format(Number(value ?? 0));

const formatPercent = (value: number | null | undefined) =>
  `${percentFormatter.format(Number(value ?? 0))}%`;

const canViewReports = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin || role === ROLE_STORE_ADMIN || role === ROLE_SUPER_ADMIN || role === ROLE_PROFESSIONAL;

const canViewFinancialAdmin = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin || role === ROLE_STORE_ADMIN || role === ROLE_SUPER_ADMIN;

const getAppointmentTone = (status: string): Tone => {
  if (["CANCELLED", "EXPIRED", "REJECTED"].includes(status)) return "danger";
  if (["PENDING", "PENDING_PAYMENT"].includes(status)) return "warning";
  if (["CONFIRMED", "COMPLETED"].includes(status)) return "success";
  return "neutral";
};

const getTopProfessional = (items: ProfessionalReportItem[] | undefined) =>
  [...(items ?? [])].sort(
    (left, right) => right.occupancy_rate - left.occupancy_rate || right.revenue - left.revenue
  )[0];

const mapAgenda = (appointments: UpcomingAppointment[] | undefined): AgendaItem[] =>
  (appointments ?? []).map((appointment) => ({
    id: appointment.public_id,
    time: format(new Date(appointment.starts_at), "HH:mm"),
    title: appointment.client_name,
    subtitle: `${appointment.service_name} - ${appointment.staff_name}`,
    status: appointment.status,
    tone: getAppointmentTone(appointment.status),
  }));

const mapTopServices = (items: ReportTopServiceItem[] | undefined): RankedItem[] =>
  (items ?? []).slice(0, 3).map((item) => ({
    id: item.service_id,
    label: item.service_name,
    value: formatCurrency(item.revenue),
    detail: `${numberFormatter.format(item.appointments)} reservas`,
  }));

const Dashboard = () => {
  const navigate = useNavigate();
  const { token, user } = useAuth();
  const isGlobalAdmin = Boolean(user?.is_global_admin);
  const reportsAllowed = canViewReports(user?.role, isGlobalAdmin);
  const financialAdminAllowed = canViewFinancialAdmin(user?.role, isGlobalAdmin);
  const fromDate = useMemo(() => format(subDays(new Date(), 7), "yyyy-MM-dd"), []);
  const toDate = useMemo(() => format(new Date(), "yyyy-MM-dd"), []);

  const summaryQuery = useDashboardSummary(Boolean(token));
  const featureFlagsQuery = useStoreFeatureFlags();
  const reportsQuery = useReportSummary(fromDate, toDate, reportsAllowed);
  const professionalsQuery = useProfessionalReports(fromDate, toDate, reportsAllowed);

  const flags = featureFlagsQuery.data?.flags;
  const paymentsEnabled = Boolean(flags?.payments);
  const ledgerEnabled = Boolean(flags?.ledger);

  const paymentsQuery = useReconciliationSummary(Boolean(paymentsEnabled && financialAdminAllowed));
  const outboxQuery = useOutboxStats(Boolean(paymentsEnabled && financialAdminAllowed));
  const ledgerQuery = useLedgerSummary(Boolean(ledgerEnabled && reportsAllowed));

  const stats = summaryQuery.data?.stats;
  const reportStats = reportsQuery.data?.stats;
  const clientStats = reportsQuery.data?.client_stats;
  const outstandingBalance = Number(
    ledgerQuery.data?.total_balance ?? reportsQuery.data?.debt_summary.outstanding_balance ?? 0
  );
  const debtorsCount = Number(ledgerQuery.data?.debtors_count ?? reportsQuery.data?.debt_summary.debtors_count ?? 0);
  const topProfessional = getTopProfessional(professionalsQuery.data?.professionals);

  const todayMetrics = useMemo<MetricItem[]>(
    () => [
      {
        id: "appointments-today",
        label: "Turnos hoy",
        value: numberFormatter.format(stats?.appointments_today ?? 0),
        detail: `${numberFormatter.format(stats?.pending_confirmations ?? 0)} pendientes`,
        tone: "primary",
        onSelect: () => navigate("/dashboard/calendar"),
      },
      {
        id: "occupancy",
        label: "Ocupacion",
        value: formatPercent(stats?.occupancy_rate),
        detail: "Capacidad tomada hoy",
        tone: Number(stats?.occupancy_rate ?? 0) >= 85 ? "warning" : "neutral",
        onSelect: () => navigate("/dashboard/reports"),
      },
      {
        id: "new-clients",
        label: "Clientes nuevos",
        value: numberFormatter.format(stats?.new_clients_last_30d ?? 0),
        detail: "Ultimos 30 dias",
        tone: "success",
        onSelect: () => navigate("/dashboard/users"),
      },
      {
        id: "weekly-revenue",
        label: "Ingreso semanal",
        value: formatCurrency(stats?.weekly_revenue),
        detail: `${formatPercent(stats?.revenue_trend)} vs semana anterior`,
        tone: Number(stats?.revenue_trend ?? 0) < 0 ? "warning" : "success",
        onSelect: () => navigate("/dashboard/reports"),
      },
    ],
    [navigate, stats]
  );

  const urgentActions = useMemo<ActionItem[]>(() => {
    const items: ActionItem[] = [];
    if (Number(stats?.pending_confirmations ?? 0) > 0) {
      items.push({
        id: "confirmations",
        title: "Confirmar turnos",
        description: "Reservas esperando decision",
        meta: numberFormatter.format(stats?.pending_confirmations ?? 0),
        tone: "warning",
        onSelect: () => navigate("/dashboard/calendar"),
      });
    }
    if (Number(paymentsQuery.data?.pending_payments ?? 0) > 0) {
      items.push({
        id: "pending-payments",
        title: "Revisar pagos pendientes",
        description: formatCurrency(paymentsQuery.data?.total_pending_amount),
        meta: numberFormatter.format(paymentsQuery.data?.pending_payments ?? 0),
        tone: "warning",
        onSelect: () => navigate("/dashboard/payments"),
      });
    }
    if (Number(outboxQuery.data?.pending_with_error ?? 0) > 0 || Number(paymentsQuery.data?.failed_webhooks ?? 0) > 0) {
      items.push({
        id: "payment-sync",
        title: "Corregir sincronizacion de pagos",
        description: "Hay webhooks u outbox con error",
        meta: numberFormatter.format(
          Number(outboxQuery.data?.pending_with_error ?? 0) + Number(paymentsQuery.data?.failed_webhooks ?? 0)
        ),
        tone: "danger",
        onSelect: () => navigate("/dashboard/payments"),
      });
    }
    if (debtorsCount > 0) {
      items.push({
        id: "debtors",
        title: "Gestionar deuda",
        description: formatCurrency(outstandingBalance),
        meta: numberFormatter.format(debtorsCount),
        tone: "warning",
        onSelect: () => navigate("/dashboard/ledger"),
      });
    }
    return items;
  }, [debtorsCount, navigate, outboxQuery.data, outstandingBalance, paymentsQuery.data, stats]);

  const moneyMetrics = useMemo<MetricItem[]>(
    () => [
      {
        id: "approved-amount",
        label: "Cobrado",
        value: formatCurrency(paymentsQuery.data?.total_approved_amount ?? reportStats?.total_revenue),
        detail: paymentsEnabled ? "Pagos aprobados y manuales" : "Ingresos por turnos",
        tone: "success",
        onSelect: () => navigate(paymentsEnabled ? "/dashboard/payments" : "/dashboard/reports"),
      },
      {
        id: "average-ticket",
        label: "Ticket promedio",
        value: formatCurrency(reportStats?.average_ticket),
        detail: "Ultimos 7 dias",
        tone: "neutral",
        onSelect: () => navigate("/dashboard/reports"),
      },
      {
        id: "outstanding-balance",
        label: "Saldo pendiente",
        value: formatCurrency(outstandingBalance),
        detail: `${numberFormatter.format(debtorsCount)} deudores`,
        tone: debtorsCount > 0 ? "warning" : "neutral",
        onSelect: () => navigate("/dashboard/ledger"),
      },
    ],
    [debtorsCount, navigate, outstandingBalance, paymentsEnabled, paymentsQuery.data, reportStats]
  );

  const performanceItems = useMemo<RankedItem[]>(() => {
    const items = mapTopServices(reportsQuery.data?.top_services);
    if (topProfessional) {
      items.unshift({
        id: topProfessional.staff_id,
        label: topProfessional.staff_name,
        value: formatPercent(topProfessional.occupancy_rate),
        detail: `${formatCurrency(topProfessional.revenue)} por profesional`,
      });
    }
    if (clientStats) {
      items.push({
        id: "returning-clients",
        label: "Clientes recurrentes",
        value: numberFormatter.format(clientStats.returning_clients),
        detail: `${numberFormatter.format(clientStats.new_clients)} nuevos`,
      });
    }
    return items.slice(0, 5);
  }, [clientStats, reportsQuery.data?.top_services, topProfessional]);

  const alerts = useMemo<ActionItem[]>(() => {
    const items: ActionItem[] = [];
    if (featureFlagsQuery.isSuccess && !paymentsEnabled) {
      items.push({
        id: "payments-disabled",
        title: "Pagos deshabilitados",
        description: "No hay conciliacion automatica activa",
        tone: "neutral",
        onSelect: () => navigate("/dashboard/settings"),
      });
    }
    if (featureFlagsQuery.isSuccess && !ledgerEnabled) {
      items.push({
        id: "ledger-disabled",
        title: "Ledger deshabilitado",
        description: "No se registra deuda por cliente",
        tone: "neutral",
        onSelect: () => navigate("/dashboard/settings"),
      });
    }
    if (Number(reportStats?.cancelled_appointments ?? 0) > 0) {
      items.push({
        id: "cancellations",
        title: "Cancelaciones en el periodo",
        description: "Revisar patron por servicio o profesional",
        meta: numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
        tone: "warning",
        onSelect: () => navigate("/dashboard/reports"),
      });
    }
    if (Number(stats?.revenue_trend ?? 0) < -15) {
      items.push({
        id: "revenue-drop",
        title: "Ingreso semanal en baja",
        description: `${formatPercent(stats?.revenue_trend)} contra la semana anterior`,
        tone: "danger",
        onSelect: () => navigate("/dashboard/reports"),
      });
    }
    return items;
  }, [featureFlagsQuery.isSuccess, ledgerEnabled, navigate, paymentsEnabled, reportStats, stats]);

  return (
    <EnterpriseDashboard
      copy={dashboardCopy}
      todayMetrics={todayMetrics}
      urgentActions={urgentActions}
      agenda={mapAgenda(summaryQuery.data?.upcoming_appointments)}
      moneyMetrics={moneyMetrics}
      performanceItems={performanceItems}
      alerts={alerts}
      isLoading={summaryQuery.isLoading}
      errorMessage={summaryQuery.isError ? "No se pudo cargar el resumen operativo." : undefined}
    />
  );
};

function EnterpriseDashboard({
  copy,
  todayMetrics,
  urgentActions,
  agenda,
  moneyMetrics,
  performanceItems,
  alerts,
  isLoading,
  errorMessage,
}: EnterpriseDashboardProps) {
  if (isLoading) {
    return (
      <main style={pageStyle}>
        <div style={{ ...panelStyle, padding: 24, color: carbon.gray60 }}>Cargando dashboard...</div>
      </main>
    );
  }

  return (
    <main style={pageStyle}>
      {errorMessage && (
        <div
          style={{
            ...panelStyle,
            padding: 16,
            borderColor: carbon.danger,
            color: carbon.danger,
            fontSize: 14,
            lineHeight: "20px",
          }}
        >
          {errorMessage}
        </div>
      )}

      <section style={metricGridStyle}>
        {todayMetrics.map((metric) => (
          <MetricCard key={metric.id} item={metric} />
        ))}
      </section>

      <section style={dashboardLayoutStyle} className="enterprise-dashboard-layout">
        <Panel title={copy.actionsTitle}>
          <ActionList items={urgentActions} emptyText={copy.emptyActions} />
        </Panel>

        <Panel title={copy.agendaTitle} className="enterprise-dashboard-agenda">
          <AgendaList items={agenda} emptyText={copy.emptyAgenda} />
        </Panel>

        <Panel title={copy.moneyTitle}>
          <MetricStack items={moneyMetrics} />
        </Panel>

        <Panel title={copy.performanceTitle}>
          <RankedList items={performanceItems} />
        </Panel>

        <Panel title={copy.alertsTitle}>
          <ActionList items={alerts} emptyText={copy.emptyAlerts} compact />
        </Panel>
      </section>

      <style>
        {`
          @media (max-width: 1200px) {
            .enterprise-dashboard-layout {
              grid-template-columns: 1fr 1fr !important;
            }
            .enterprise-dashboard-agenda {
              grid-row: auto !important;
            }
          }
          @media (max-width: 760px) {
            .enterprise-dashboard-layout {
              grid-template-columns: 1fr !important;
            }
          }
        `}
      </style>
    </main>
  );
}

function MetricCard({ item }: { item: MetricItem }) {
  return (
    <button
      type="button"
      onClick={item.onSelect}
      style={{
        display: "grid",
        gap: 8,
        minHeight: 104,
        padding: 16,
        background: carbon.white,
        border: `1px solid ${toneBorder(item.tone)}`,
        borderRadius: 8,
        color: carbon.black,
        textAlign: "left",
        cursor: item.onSelect ? "pointer" : "default",
      }}
    >
      <span style={{ color: carbon.gray60, fontSize: 12, lineHeight: "16px" }}>{item.label}</span>
      <strong style={{ color: item.tone === "primary" ? carbon.blue : carbon.black, fontSize: 28, lineHeight: "32px", fontWeight: 600 }}>
        {item.value}
      </strong>
      {item.detail && <span style={{ color: carbon.gray60, fontSize: 12, lineHeight: "16px" }}>{item.detail}</span>}
    </button>
  );
}

function Panel({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section style={panelStyle} className={className}>
      <header style={panelHeaderStyle}>
        <h2 style={panelTitleStyle}>{title}</h2>
      </header>
      <div style={panelBodyStyle}>{children}</div>
    </section>
  );
}

function ActionList({
  items,
  emptyText,
  compact = false,
}: {
  items: ActionItem[];
  emptyText: string;
  compact?: boolean;
}) {
  if (!items.length) return <EmptyState text={emptyText} />;

  return (
    <div style={listStyle}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={item.onSelect}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            width: "100%",
            minHeight: compact ? 48 : 56,
            padding: 12,
            background: carbon.gray10,
            border: `1px solid ${toneBorder(item.tone)}`,
            borderRadius: 8,
            color: carbon.black,
            cursor: item.onSelect ? "pointer" : "default",
            textAlign: "left",
          }}
        >
          <span style={{ display: "grid", gap: 4, minWidth: 0 }}>
            <strong style={{ fontSize: 14, lineHeight: "20px", fontWeight: 600 }}>{item.title}</strong>
            {item.description && (
              <small style={{ color: carbon.gray60, fontSize: 12, lineHeight: "16px" }}>{item.description}</small>
            )}
          </span>
          {item.meta && (
            <em style={{ color: carbon.gray80, fontSize: 12, lineHeight: "16px", fontStyle: "normal", whiteSpace: "nowrap" }}>
              {item.meta}
            </em>
          )}
        </button>
      ))}
    </div>
  );
}

function AgendaList({ items, emptyText }: { items: AgendaItem[]; emptyText: string }) {
  if (!items.length) return <EmptyState text={emptyText} />;

  return (
    <div style={listStyle}>
      {items.map((item) => (
        <div
          key={item.id}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            minHeight: 56,
            padding: 12,
            background: carbon.gray10,
            border: `1px solid ${toneBorder(item.tone)}`,
            borderRadius: 8,
            color: carbon.black,
          }}
        >
          <time style={{ width: 48, color: carbon.gray80, fontSize: 12, lineHeight: "16px", fontWeight: 600 }}>
            {item.time}
          </time>
          <span style={{ display: "grid", gap: 4, minWidth: 0, flex: 1 }}>
            <strong style={{ fontSize: 14, lineHeight: "20px", fontWeight: 600 }}>{item.title}</strong>
            {item.subtitle && <small style={{ color: carbon.gray60, fontSize: 12, lineHeight: "16px" }}>{item.subtitle}</small>}
          </span>
          {item.status && (
            <em style={{ color: carbon.gray80, fontSize: 12, lineHeight: "16px", fontStyle: "normal", whiteSpace: "nowrap" }}>
              {item.status}
            </em>
          )}
        </div>
      ))}
    </div>
  );
}

function MetricStack({ items }: { items: MetricItem[] }) {
  return (
    <div style={listStyle}>
      {items.map((item) => (
        <MetricCard key={item.id} item={item} />
      ))}
    </div>
  );
}

function RankedList({ items }: { items: RankedItem[] }) {
  if (!items.length) return <EmptyState text="Sin datos para este periodo." />;

  return (
    <ol style={{ ...listStyle, listStyle: "none", margin: 0, padding: 0 }}>
      {items.map((item) => (
        <li
          key={item.id}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            minHeight: 56,
            padding: 12,
            background: carbon.gray10,
            border: "1px solid transparent",
            borderRadius: 8,
          }}
        >
          <span style={{ display: "grid", gap: 4, minWidth: 0 }}>
            <strong style={{ fontSize: 14, lineHeight: "20px", fontWeight: 600 }}>{item.label}</strong>
            {item.detail && <small style={{ color: carbon.gray60, fontSize: 12, lineHeight: "16px" }}>{item.detail}</small>}
          </span>
          <em style={{ color: carbon.gray80, fontSize: 12, lineHeight: "16px", fontStyle: "normal", whiteSpace: "nowrap" }}>
            {item.value}
          </em>
        </li>
      ))}
    </ol>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p style={emptyStyle}>{text}</p>;
}

export default Dashboard;
