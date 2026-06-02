import React from "react";
import { 
  Users, 
  Calendar, 
  TrendingUp, 
  Clock,
  ArrowUpRight,
  UserCheck,
  Loader2
} from "lucide-react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import { useAuth } from "../context/AuthContext";
import { useDashboardSummary } from "../hooks/useDashboard";
import { colors2000s } from "../../theme/colors";

const Dashboard: React.FC = () => {
  const { token } = useAuth();
  const { data, isLoading, isError } = useDashboardSummary(Boolean(token));

  const currencyFmt = new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 0,
  });

  const stats = [
    {
      label: "Turnos Hoy",
      value: String(data?.stats?.appointments_today ?? 0),
      icon: Calendar,
      color: "#3b82f6",
      path: "/dashboard/calendar",
    },
    {
      label: "Clientes Nuevos (30d)",
      value: String(data?.stats?.new_clients_last_30d ?? 0),
      icon: UserCheck,
      color: "#10b981",
      path: "/dashboard/staff",
    },
    {
      label: "Revenue Semanal",
      value: currencyFmt.format(data?.stats?.weekly_revenue ?? 0),
      icon: TrendingUp,
      color: colors2000s.orange.accent,
      path: "/dashboard",
    },
    {
      label: "Tiempo Promedio",
      value: `${data?.stats?.average_appointment_minutes ?? 0} min`,
      icon: Clock,
      color: "#f59e0b",
      path: "/dashboard",
    },
  ];

  if (isLoading) {
    return (
      <div className="h-[60vh] flex items-center justify-center" style={{ color: colors2000s.text.secondary }}>
        <div className="flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Cargando dashboard...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {isError && (
        <div className="text-sm p-4 rounded-xl flex items-start gap-3" style={{ background: '#ffeeee', border: '1px solid #ffcccc', color: '#cc0000', boxShadow: colors2000s.shadows.insetDark }}>
          No se pudo cargar el resumen del dashboard. Reintenta en unos segundos.
        </div>
      )}

      {/* Grid de Estadísticas */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, i) => (
          <div key={i} className="p-6 rounded-2xl transition-all group" 
               style={{ 
                 background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                 border: `1px solid ${colors2000s.border.default}`,
                 boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
               }}>
            <div className="flex justify-between items-start mb-4">
              <div className="p-3 rounded-xl" style={{ background: 'white', boxShadow: colors2000s.shadows.insetDark, border: `1px solid ${colors2000s.border.light}` }}>
                <stat.icon className="w-6 h-6" style={{ color: stat.color }} />
              </div>
              <Link 
                to={stat.path}
                className="transition-colors p-1"
                style={{ color: colors2000s.text.disabled }}
              >
                <ArrowUpRight className="w-5 h-5 hover:scale-110 transition-transform" />
              </Link>
            </div>
            <div>
              <p className="text-sm font-bold uppercase tracking-wider" style={{ color: colors2000s.text.secondary, fontSize: '10px' }}>{stat.label}</p>
              <h3 className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>{stat.value}</h3>
            </div>
          </div>
        ))}
      </div>

      {/* Sección Inferior */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 p-8 rounded-3xl" 
             style={{ 
               background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
               border: `1px solid ${colors2000s.border.default}`,
               boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
             }}>
          <h3 className="text-lg font-black mb-6 uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>Próximos Turnos</h3>
          <div className="space-y-4">
            {(data?.upcoming_appointments.length ?? 0) === 0 && (
              <div className="p-6 rounded-2xl text-sm italic" style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, color: colors2000s.text.disabled, boxShadow: colors2000s.shadows.insetDark }}>
                No hay turnos próximos para mostrar.
              </div>
            )}

            {data?.upcoming_appointments.map((appointment) => (
              <div key={appointment.public_id} className="flex items-center justify-between p-4 rounded-2xl transition-all"
                   style={{ background: 'white', border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.outer }}>
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full flex items-center justify-center font-bold"
                       style={{ background: `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.disabledBottom} 100%)`, color: colors2000s.text.secondary, border: `1px solid ${colors2000s.border.default}` }}>
                    {appointment.client_name[0]?.toUpperCase() ?? "-"}
                  </div>
                  <div>
                    <p className="text-sm font-bold" style={{ color: colors2000s.text.primary }}>{appointment.client_name}</p>
                    <p className="text-xs" style={{ color: colors2000s.text.secondary }}>
                      {appointment.service_name} · <span className="font-bold" style={{ color: colors2000s.orange.accent }}>{format(new Date(appointment.starts_at), "HH:mm")}</span>
                    </p>
                  </div>
                </div>
                <div className="px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest"
                     style={{ background: colors2000s.bg.disabled, border: `1px solid ${colors2000s.border.default}`, color: colors2000s.text.secondary }}>
                  {appointment.status}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Card de Promoción - Glossy Blue */}
        <div className="rounded-3xl p-8 flex flex-col justify-between relative overflow-hidden group"
             style={{ 
               background: `linear-gradient(180deg, #1e40af 0%, #1e3a8a 100%)`,
               boxShadow: '0 10px 15px -3px rgba(30, 58, 138, 0.3)',
               border: '1px solid #1e3a8a'
             }}>
          {/* Gloss effect */}
          <div className="absolute top-0 left-0 w-full h-1/2 bg-gradient-to-b from-white/20 to-transparent pointer-events-none" />
          
          <div className="absolute top-0 right-0 p-8 opacity-10 group-hover:scale-110 transition-transform">
            <Users className="w-32 h-32 text-white" />
          </div>
          
          <div className="relative z-10">
            <h3 className="text-xl font-black text-white mb-2 italic">Impulsá tu negocio</h3>
            <p className="text-blue-100/80 text-sm mb-6 leading-tight">
              Vemos bastante movimiento en la agenda. Después podemos sumar campañas y recordatorios según tu rubro.
            </p>
          </div>
          
          <button 
            disabled
            className="relative z-10 w-full font-black py-4 rounded-xl transition-all cursor-not-allowed uppercase tracking-widest text-sm"
            style={{ 
              background: `linear-gradient(180deg, #ffffff 0%, #e2e8f0 100%)`,
              color: '#1e3a8a',
              boxShadow: '0 4px 6px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,1)'
            }}
          >
            Próximamente
          </button>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
