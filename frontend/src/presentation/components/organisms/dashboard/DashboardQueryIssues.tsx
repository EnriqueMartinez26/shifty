import { RefreshCw, TriangleAlert } from 'lucide-react'

import type { DashboardQueryIssue } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

type DashboardQueryIssuesProps = {
  issues: DashboardQueryIssue[]
}

function DashboardQueryIssues({ issues }: DashboardQueryIssuesProps) {
  if (issues.length === 0) return null

  return (
    <section
      aria-labelledby="dashboard-query-issues-title"
      className="grid gap-3 p-5 rounded-3xl"
      style={{
        ...createDashboardPanelStyle(),
        borderColor: colors2000s.status.danger.border
      }}
    >
      <div className="flex items-center gap-2">
        <TriangleAlert size={18} color={colors2000s.status.danger.text} aria-hidden="true" />
        <h2
          id="dashboard-query-issues-title"
          className="m-0 text-sm font-black uppercase tracking-wide"
          style={{ color: colors2000s.text.primary }}
        >
          Algunos datos no se pudieron cargar
        </h2>
      </div>
      <ul className="grid gap-3 m-0 p-0 list-none">
        {issues.map((issue) => (
          <li
            key={issue.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl p-3"
            style={{
              background: colors2000s.status.danger.bg,
              border: `1px solid ${colors2000s.status.danger.border}`
            }}
          >
            <div className="grid gap-1 min-w-0">
              <strong className="text-xs font-black" style={{ color: colors2000s.text.primary }}>
                {issue.title}
              </strong>
              <span className="text-xs font-bold" style={{ color: colors2000s.status.danger.text }}>
                {issue.message}
              </span>
            </div>
            <button
              type="button"
              onClick={issue.onRetry}
              disabled={issue.retrying}
              aria-label={`Reintentar ${issue.title.toLowerCase()}`}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-xs font-black uppercase tracking-wide disabled:cursor-wait disabled:opacity-60"
              style={{
                background: colors2000s.bg.button,
                border: `1px solid ${colors2000s.border.default}`,
                color: colors2000s.text.primary,
                boxShadow: colors2000s.shadows.insetLight
              }}
            >
              <RefreshCw
                size={14}
                className={issue.retrying ? 'animate-spin' : undefined}
                aria-hidden="true"
              />
              {issue.retrying ? 'Reintentando...' : 'Reintentar'}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default DashboardQueryIssues
