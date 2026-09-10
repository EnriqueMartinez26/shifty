import { useMemo } from 'react'
import type { CSSProperties } from 'react'

import { PieChart as PieChartIcon } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import type { ReportTopServiceItem } from '@application/services/ReportsService'

import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

// Orden fijo de categorias (servicio 1..4). Validado con scripts/validate_palette.js
// del skill dataviz en modo --pairs all (una dona expone cualquier par de porciones
// como vecinas segun los datos, por eso se valida contra todos los pares, no solo
// adyacentes en la lista). "Otros" queda siempre en gris neutro para no reintroducir
// un choque de tono calido (naranja/aviso/peligro comparten familia calida).
const sliceColors = [
  colors2000s.orange.dark,
  colors2000s.status.success.dark,
  colors2000s.status.info.dark,
  colors2000s.status.danger.dark
]

const othersColor = colors2000s.text.disabled

const numberFormatter = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 })
const currencyFormatter = new Intl.NumberFormat('es-AR', {
  style: 'currency',
  currency: 'ARS',
  maximumFractionDigits: 0
})

type SalesSlice = {
  id: string
  name: string
  value: number
  revenue: number
  color: string
}

export type SalesDonutProps = {
  services: ReportTopServiceItem[]
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

const buildSlices = (services: ReportTopServiceItem[]): SalesSlice[] => {
  const sorted = [...services].sort((left, right) => right.appointments - left.appointments)
  const top = sorted.slice(0, 4)
  const rest = sorted.slice(4)

  const slices: SalesSlice[] = top.map((service, index) => ({
    id: service.service_id,
    name: service.service_name,
    value: service.appointments,
    revenue: service.revenue,
    color: sliceColors[index] ?? othersColor
  }))

  if (rest.length) {
    slices.push({
      id: 'others',
      name: 'Otros',
      value: rest.reduce((sum, item) => sum + item.appointments, 0),
      revenue: rest.reduce((sum, item) => sum + item.revenue, 0),
      color: othersColor
    })
  }

  return slices.filter((slice) => slice.value > 0)
}

export function SalesDonut({ services, isLoading }: SalesDonutProps) {
  const slices = useMemo(() => buildSlices(services ?? []), [services])
  const totalAppointments = useMemo(
    () => slices.reduce((sum, slice) => sum + slice.value, 0),
    [slices]
  )

  return (
    <section style={createDashboardPanelStyle()}>
      <div style={panelBodyStyle}>
        <div style={headerStyle}>
          <span style={iconBadgeStyle}>
            <PieChartIcon size={18} />
          </span>
          <div style={{ display: 'grid', gap: 2 }}>
            <h3 style={titleStyle}>Ventas por servicio</h3>
            <p style={subtitleStyle}>Reservas por servicio en el periodo.</p>
          </div>
        </div>

        {isLoading ? (
          <p style={emptyStyle}>Cargando ventas...</p>
        ) : !slices.length ? (
          <p style={emptyStyle}>Sin reservas registradas en el periodo.</p>
        ) : (
          <>
            <div style={{ position: 'relative', width: '100%', height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={slices}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={62}
                    outerRadius={92}
                    paddingAngle={2}
                    stroke={colors2000s.bg.button}
                    strokeWidth={2}
                  >
                    {slices.map((slice) => (
                      <Cell key={slice.id} fill={slice.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={tooltipContentStyle}
                    formatter={(value, _name, item) => {
                      const slice = item.payload as SalesSlice
                      return [
                        `${numberFormatter.format(Number(value))} reservas - ${currencyFormatter.format(
                          slice.revenue
                        )}`,
                        slice.name
                      ]
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>

              <div
                style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  transform: 'translate(-50%, -50%)',
                  textAlign: 'center',
                  pointerEvents: 'none'
                }}
              >
                <strong
                  style={{
                    display: 'block',
                    color: colors2000s.text.primary,
                    fontSize: 26,
                    lineHeight: '30px',
                    fontWeight: 900,
                    letterSpacing: '-0.02em'
                  }}
                >
                  {numberFormatter.format(totalAppointments)}
                </strong>
                <span
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 10,
                    lineHeight: '12px',
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em'
                  }}
                >
                  Reservas
                </span>
              </div>
            </div>

            <ul style={{ display: 'grid', gap: 8, listStyle: 'none', margin: 0, padding: 0 }}>
              {slices.map((slice) => (
                <li
                  key={slice.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 10
                  }}
                >
                  <span
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      minWidth: 0,
                      color: colors2000s.text.primary,
                      fontSize: 12,
                      lineHeight: '16px',
                      fontWeight: 800
                    }}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 3,
                        background: slice.color,
                        flexShrink: 0
                      }}
                    />
                    <span
                      style={{
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      {slice.name}
                    </span>
                  </span>
                  <span
                    style={{
                      color: colors2000s.text.secondary,
                      fontSize: 12,
                      lineHeight: '16px',
                      fontWeight: 800,
                      whiteSpace: 'nowrap'
                    }}
                  >
                    {numberFormatter.format(slice.value)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  )
}

export default SalesDonut
