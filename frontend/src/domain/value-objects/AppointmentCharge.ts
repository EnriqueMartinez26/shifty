/**
 * Estado del cobro de un turno, tal como lo opera la pantalla de Cobros.
 *
 * Replica dos conjuntos de `backend/modules/payments/model.py`:
 * `ACCREDITED_PAYMENT_STATUSES` (la plata entro) y
 * `LIVE_CHARGE_PAYMENT_STATUSES` (el cobro sigue abierto: la sena pendiente).
 * El backend tiene a lo sumo un cobro por turno (`uq_payments_store_appointment`).
 */
const ACCREDITED_PAYMENT_STATUSES: readonly string[] = ['approved', 'manual_confirmed']
const LIVE_CHARGE_PAYMENT_STATUSES: readonly string[] = ['pending', 'rejected']

interface AppointmentChargeInput {
  appointmentStatus: string
  /** Precio congelado del turno; la API manda los importes como texto decimal. */
  priceAmount: number | string | null | undefined
  paymentStatus: string | null | undefined
  paymentAmount: number | string | null | undefined
}

export type AppointmentCharge =
  /** La plata entro; `remaining` es lo que falta para el precio del turno. */
  | { kind: 'paid'; paid: number; remaining: number }
  | { kind: 'refunded' }
  /**
   * Cobro vivo: lo que el turno tiene pendiente de pago. Es sena si cobra
   * menos que el precio del turno; un link del panel por el precio completo
   * no lo es (revision de la PR #131, S1).
   */
  | { kind: 'pending'; amount: number; isDeposit: boolean }
  /** Sin cobro (o vencido): se sugiere el precio, si se conoce. */
  | { kind: 'unpaid'; suggested: number | null }

const toAmount = (value: number | string | null | undefined): number | null => {
  if (value === null || value === undefined || value === '') return null
  const amount = Number(value)
  return Number.isFinite(amount) && amount >= 0 ? amount : null
}

/**
 * 2026-10-08 (decision de Mateo): el importe de "Confirmar pago" se precarga
 * con la sena pendiente si el turno tiene un cobro vivo; si no, con el precio
 * del turno menos lo pagado. Con un solo cobro por turno, "lo pagado" de un
 * turno sin cobro acreditado es cero.
 *
 * Un ausente no debe el resto de un servicio que no recibio: su `remaining`
 * es cero (lo que pago es sena retenida, como la cuentan los reportes).
 */
export const appointmentChargeOf = ({
  appointmentStatus,
  priceAmount,
  paymentStatus,
  paymentAmount
}: AppointmentChargeInput): AppointmentCharge => {
  const price = toAmount(priceAmount)
  const amount = toAmount(paymentAmount)
  if (paymentStatus && ACCREDITED_PAYMENT_STATUSES.includes(paymentStatus)) {
    const paid = amount ?? 0
    const owes = price !== null && appointmentStatus !== 'absent'
    return { kind: 'paid', paid, remaining: owes ? Math.max(price - paid, 0) : 0 }
  }
  if (paymentStatus === 'refunded') return { kind: 'refunded' }
  if (paymentStatus && LIVE_CHARGE_PAYMENT_STATUSES.includes(paymentStatus) && amount !== null) {
    return { kind: 'pending', amount, isDeposit: price !== null && amount < price }
  }
  return { kind: 'unpaid', suggested: price }
}
