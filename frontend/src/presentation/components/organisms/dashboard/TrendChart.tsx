import type { CSSProperties } from 'react'

import { TrendingUp } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'

import type { ReportTrendPoint } from '@application/services/ReportsService'

import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

// Orden fijo de series (no identidad categorica libre): Total / Completados / Cancelados.
// Paleta validada con scripts/validate_palette.js del skill dataviz (ALL CHECKS PASS).
const seriesColors = {
  total: colors2000s.orange.dark,
  completed: colors2000s.status.success.dark,
  cancelled: colors2000s.status.danger.dark
}

const monthLabelFormatter = new Intl.DateTimeFormat('es-AR', { month: 'short' })

const formatMonthLabel = (month: string) => {
  const [year, monthIndex] = month.split('-').map(Number)
  if (!year || !monthIndex) return month
  const date = new Date(year, monthIndex - 1, 1)
  const label = monthLabelFormatter.format(date).replace('.', '')
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}`
}

export type TrendChartProps = {
  points: ReportTrendPoint[]
  isLoading?: boolean
}

const panelBodyStyle: CSSProperties = { padding: 24, display: 'grid', gap: 16 }

const headerStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 10 }

const iconBadgeStyle: CSSProperties = {
  width: 34,
  height: 34,
  borderRadius: 12,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(255, 140, 66, 0.12)',
  border: '1px solid rgba(200, 90, 15, 0.25)',
  color: colors2000s.orange.accent,
  boxShadow: colors2000s.shadows.insetLight,
  flexShrink: 0
}

const titleStyle: CSSProperties = {
  margin: 0,
  color: colors2000s.text.primary,
  fontSize: 16,
  lineHeight: '20px',
  fontWeight: 900,
  letterSpacing: '-0.01em',
  textTransform: 'uppercase'
}

const subtitleStyle: CSSProperties = {
  margin: 0,
  color: colors2000s.text.secondary,
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700
}

const emptyStyle: CSSProperties = {
  margin: 0,
  padding: 16,
  borderRadius: 16,
  border: `1px dashed ${colors2000s.border.default}`,
  background: 'rgba(255, 255, 255, 0.45)',
  color: colors2000s.text.secondary,
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700,
  textAlign: 'center'
}

const tooltipContentStyle: CSSProperties = {
  background: 'rgba(255, 255, 255, 0.96)',
  border: `1px solid ${colors2000s.border.default}`,
  borderRadius: 12,
  boxShadow: colors2000s.shadows.outerMedium,
  color: colors2000s.text.primary,
  fontSize: 12,
  fontWeight: 700,
  padding: '8px 12px'
}

export function TrendChart({ points, isLoading }: TrendChartProps) {
  const data = points.map((point) => ({
    ...point,
    label: formatMonthLabel(point.month)
  }))

  const hasData = data.some((point) => point.total_appointments > 0)

  return (
    <section style={createDashboardPanelStyle()}>
      <div style={panelBodyStyle}>
        <div style={headerStyle}>
          <span style={iconBadgeStyle}>
            <TrendingUp size={18} />
          </span>
          <div style={{ display: 'grid', gap: 2 }}>
            <h3 style={titleStyle}>Tendencia de turnos</h3>
            <p style={subtitleStyle}>Total, completados y cancelados por mes.</p>
          </div>
        </div>

        {isLoading ? (
          <p style={emptyStyle}>Cargando tendencia...</p>
        ) : !data.length || !hasData ? (
          <p style={emptyStyle}>Sin datos suficientes para graficar la tendencia.</p>
        ) : (
          <div style={{ width: '100%', height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} barGap={4} barCategoryGap="24%">
                <CartesianGrid vertical={false} stroke={colors2000s.border.light} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: colors2000s.text.secondary, fontSize: 11, fontWeight: 700 }}
                  axisLine={{ stroke: colors2000s.border.default }}
                  tickLine={false}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: colors2000s.text.secondary, fontSize: 11, fontWeight: 700 }}
                  axisLine={false}
                  tickLine={false}
                  width={32}
                />
                <Tooltip
                  cursor={{ fill: 'rgba(0, 0, 0, 0.04)' }}
                  contentStyle={tooltipContentStyle}
                  labelStyle={{ color: colors2000s.text.primary, fontWeight: 900 }}
                />
                <Legend
                  formatter={(value: string) => (
                    <span
                      style={{ color: colors2000s.text.secondary, fontSize: 11, fontWeight: 800 }}
                    >
                      {value}
                    </span>
                  )}
                  iconType="circle"
                  iconSize={8}
                />
                <Bar
                  dataKey="total_appointments"
                  name="Total"
                  fill={seriesColors.total}
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="completed_appointments"
                  name="Completados"
                  fill={seriesColors.completed}
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="cancelled_appointments"
                  name="Cancelados"
                  fill={seriesColors.cancelled}
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </section>
  )
}

export default TrendChart
