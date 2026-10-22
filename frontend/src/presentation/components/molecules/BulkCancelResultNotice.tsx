import React from 'react'

import type { BulkCancelSkipped } from '@application/services/PortalBookingsService'

import { colors2000s } from '../../../theme/colors'
import { bulkCancelSkipReason } from '../../lib/bulkCancelSkipReason'

interface BulkCancelResultNoticeProps {
  cancelledCount: number
  skipped: BulkCancelSkipped[]
  /** Nombre de cada reserva elegida, tomado al cancelar (la lista se refresca). */
  labels: Readonly<Record<string, string>>
}

const cancelledLine = (count: number): string => {
  if (count === 0) return 'No se canceló ninguna reserva.'
  return `Cancelamos ${count} ${count === 1 ? 'reserva' : 'reservas'}.`
}

/** Resultado de la cancelacion masiva: cuantas salieron y por que no las otras. */
export const BulkCancelResultNotice: React.FC<BulkCancelResultNoticeProps> = ({
  cancelledCount,
  skipped,
  labels
}) => (
  <div
    role="status"
    className="p-4 rounded-2xl text-sm font-bold space-y-2"
    style={{
      background: colors2000s.status.success.bg,
      border: `1px solid ${colors2000s.status.success.border}`,
      color: colors2000s.status.success.text
    }}
  >
    <p>{cancelledLine(cancelledCount)}</p>
    {skipped.length > 0 && (
      <div style={{ color: colors2000s.status.warning.text }}>
        <p>{`${skipped.length} ${skipped.length === 1 ? 'no se canceló' : 'no se cancelaron'}:`}</p>
        <ul className="list-disc pl-5">
          {skipped.map((item) => (
            <li key={item.id}>
              {`${labels[item.id] ?? 'Una reserva'}: ${bulkCancelSkipReason(item.code)}`}
            </li>
          ))}
        </ul>
      </div>
    )}
  </div>
)
