import { lazy, Suspense } from 'react'

import { Sparkles, TrendingUp, TriangleAlert, Wallet } from 'lucide-react'

import ActionList from './ActionList'
import ChartPlaceholder from './ChartPlaceholder'
import {
  boardGridStyle,
  insightsGridStyle,
  lowerGridStyle,
  pageStyle,
  panelBodyStyle
} from './dashboardStyles'
import ErrorPanel from './ErrorPanel'
import HeroPanel from './HeroPanel'
import MetricStack from './MetricStack'
import OperationPanel from './OperationPanel'
import OpportunityList from './OpportunityList'
import Panel from './Panel'
import RankedList from './RankedList'
import SummaryMetricsPanel from './SummaryMetricsPanel'
import TransactionsPanel from './TransactionsPanel'
import type { EnterpriseDashboardProps } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

// Los graficos traen recharts, que era casi todo el chunk del Dashboard
// (426 KB) y bajaba en la primera pantalla del dueno. Con lazy van a su propio
// chunk y la pagina pinta sin esperarlo (F4-13).
const TrendChart = lazy(() => import('./TrendChart'))
const SalesDonut = lazy(() => import('./SalesDonut'))

// Alto del area de dibujo de cada grafico (el `height` de su contenedor en
// TrendChart.tsx y SalesDonut.tsx). No se importa de esos modulos: hacerlo
// traeria recharts de vuelta al chunk del Dashboard.
const TREND_CHART_HEIGHT = 280
const SALES_DONUT_HEIGHT = 200

function EnterpriseDashboard({
  copy,
  hero,
  trendPoints,
  trendLoading,
  topServices,
  salesLoading,
  transactions,
  onViewTransactions,
  todayMetrics,
  urgentActions,
  agenda,
  operationCards,
  moneyMetrics,
  performanceItems,
  alerts,
  opportunities,
  isLoading,
  errorMessage
}: EnterpriseDashboardProps) {
  if (isLoading) {
    return (
      <main style={pageStyle}>
        <div
          style={{
            ...createDashboardPanelStyle(),
            ...panelBodyStyle,
            color: colors2000s.text.secondary,
            fontWeight: 700
          }}
        >
          Cargando panel...
        </div>
      </main>
    )
  }

  return (
    <main style={pageStyle}>
      {errorMessage ? <ErrorPanel message={errorMessage} /> : null}

      <SummaryMetricsPanel title={copy.metricsTitle} metrics={todayMetrics} />

      <section style={insightsGridStyle} className="dashboard-insights-grid">
        <Suspense
          fallback={<ChartPlaceholder text="Cargando tendencia..." height={TREND_CHART_HEIGHT} />}
        >
          <TrendChart points={trendPoints} isLoading={trendLoading} />
        </Suspense>
        <Suspense
          fallback={<ChartPlaceholder text="Cargando ventas..." height={SALES_DONUT_HEIGHT} />}
        >
          <SalesDonut services={topServices} isLoading={salesLoading} />
        </Suspense>
        <TransactionsPanel
          title={copy.transactionsTitle}
          description={copy.transactionsDescription}
          items={transactions}
          emptyText={copy.emptyTransactions}
          viewAllLabel={copy.viewTransactionsLabel}
          onViewAll={onViewTransactions}
        />
      </section>

      <HeroPanel hero={hero} />

      <section style={boardGridStyle} className="dashboard-board-grid">
        <OperationPanel
          title={copy.operationsTitle}
          description={copy.operationsDescription}
          agenda={agenda}
          emptyAgendaText={copy.emptyAgenda}
          cards={operationCards}
        />

        <div style={{ display: 'grid', gap: 16 }}>
          <Panel
            title={copy.actionsTitle}
            description="Lo que merece atención inmediata."
            icon={<TriangleAlert size={18} />}
          >
            <ActionList items={urgentActions} emptyText={copy.emptyActions} />
          </Panel>

          <Panel
            title={copy.moneyTitle}
            description="Cobros, ticket y deuda actual."
            icon={<Wallet size={18} />}
          >
            <MetricStack items={moneyMetrics} />
          </Panel>
        </div>
      </section>

      <section style={lowerGridStyle} className="dashboard-lower-grid">
        <Panel
          title={copy.performanceTitle}
          description="Servicios, profesionales y recurrencia."
          icon={<TrendingUp size={18} />}
        >
          <RankedList items={performanceItems} />
        </Panel>

        <Panel
          title={copy.alertsTitle}
          description="Desvios, caidas y modulos fuera de regimen."
          icon={<TriangleAlert size={18} />}
        >
          <ActionList items={alerts} emptyText={copy.emptyAlerts} compact />
        </Panel>

        <Panel
          title={copy.opportunitiesTitle}
          description="Espacios para crecer o corregir rápido."
          icon={<Sparkles size={18} />}
        >
          <OpportunityList items={opportunities} emptyText={copy.emptyOpportunities} />
        </Panel>
      </section>

      <style>
        {`
          @media (max-width: 1200px) {
            .dashboard-board-grid,
            .dashboard-lower-grid {
              grid-template-columns: 1fr !important;
            }
          }

          @media (max-width: 1100px) {
            .dashboard-insights-grid {
              grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;
            }
          }

          @media (max-width: 720px) {
            .dashboard-insights-grid {
              grid-template-columns: 1fr !important;
            }
          }
        `}
      </style>
    </main>
  )
}

export default EnterpriseDashboard
