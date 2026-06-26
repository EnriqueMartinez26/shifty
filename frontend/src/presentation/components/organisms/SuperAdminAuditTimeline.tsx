import type { ReactElement } from 'react'

import { History, Loader2 } from 'lucide-react'

import type { SuperAdminAuditLog } from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { formatDateTimeEsAr } from '../../lib/formatters'

interface SuperAdminAuditTimelineProps {
  entries: SuperAdminAuditLog[] | undefined
  isLoading: boolean
}

const actionLabels: Record<string, string> = {
  create: 'Creación',
  update: 'Actualización',
  delete: 'Baja lógica',
  status_change: 'Cambio de estado'
}

function summarizeAuditEntry(entry: SuperAdminAuditLog): string {
  const payloadAfter =
    entry.payload_after &&
    typeof entry.payload_after === 'object' &&
    !Array.isArray(entry.payload_after)
      ? entry.payload_after
      : null

  if (entry.resource_type === 'Store' && payloadAfter?.name) {
    return `Tienda ${String(payloadAfter.name)}`
  }
  if (entry.resource_type === 'User' && payloadAfter?.email) {
    return `Usuario ${String(payloadAfter.email)}`
  }
  if (entry.resource_type === 'StoreSubscription' && payloadAfter?.plan_id) {
    return `Suscripción asignada al plan ${String(payloadAfter.plan_id)}`
  }
  if (entry.resource_type === 'CouponRedemption' && payloadAfter?.code) {
    return `Cupón ${String(payloadAfter.code)} aplicado`
  }
  return entry.resource_type
}

export function SuperAdminAuditTimeline({
  entries,
  isLoading
}: SuperAdminAuditTimelineProps): ReactElement {
  return (
    <section
      className="rounded-[2rem] p-6"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.outer
      }}
    >
      <div className="mb-4 flex items-center gap-2">
        <History className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
        <div>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Audit trail
          </p>
          <h2
            className="mt-1 text-xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Timeline reciente
          </h2>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-3 rounded-[1.5rem] p-8">
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: colors2000s.orange.accent }} />
          <span className="text-sm font-bold" style={{ color: colors2000s.text.secondary }}>
            Cargando auditoría...
          </span>
        </div>
      ) : entries?.length ? (
        <div className="space-y-3">
          {entries.map((entry) => (
            <div
              key={entry.public_id}
              className="rounded-[1.5rem] p-4"
              style={{
                background: colors2000s.bg.button,
                border: `1px solid ${colors2000s.border.light}`
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>
                    {actionLabels[entry.action] || entry.action}
                  </p>
                  <p
                    className="text-[10px] font-bold uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    {summarizeAuditEntry(entry)}
                  </p>
                </div>
                <span
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {formatDateTimeEsAr(entry.created_at)}
                </span>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest">
                <span style={{ color: colors2000s.text.secondary }}>Actor:</span>
                <span style={{ color: colors2000s.text.primary }}>
                  {entry.actor_email || 'Sistema'}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div
          className="rounded-[1.5rem] p-8 text-center"
          style={{ background: colors2000s.bg.button }}
        >
          <p
            className="text-sm font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.primary }}
          >
            Sin eventos recientes
          </p>
          <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Cuando haya cambios relevantes del tenant, van a aparecer acá.
          </p>
        </div>
      )}
    </section>
  )
}
