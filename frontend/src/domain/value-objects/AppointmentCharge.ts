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

/**
 * Medios con que se registra el resto de un turno (D-20261008-01). Replica
 * `BalancePaymentMethod` de `backend/modules/payments/model.py`.
 */
export const REMAINDER_PAYMENT_METHODS = [
  'efectivo',
  'transferencia',
  'mercadopago',
  'otro'
] as const
export type RemainderPaymentMethod = (typeof REMAINDER_PAYMENT_METHODS)[number]

interface AppointmentChargeInput {
  appointmentStatus: string
  /** Precio congelado del turno; la API manda los importes como texto decimal. */
  priceAmount: number | string | null | undefined
  paymentStatus: string | null | undefined
  paymentAmount: number | string | null | undefined
  /** Saldo que calcula el backend en SQL (D-20261008-01); manda sobre el calculo local. */
  remainingAmount?: number | string | null
  /** Resto ya registrado aparte del cobro (a lo sumo uno por turno). */
  remainderAmount?: number | string | null
}

export type AppointmentCharge =
  /**
   * La plata entro: `paid` es el cobro mas el resto registrado y `remaining`
   * lo que falta para el precio del turno.
   */
  | { kind: 'paid'; paid: number; remaining: number; remainderRecorded: boolean }
  /**
   * El cobro se devolvio. `remainder` es el resto vivo, que la devolucion no
   * revierte y sigue contando como ingreso (revision de la PR #137, W1).
   */
  | { kind: 'refunded'; remainder: number | null }
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
 * El saldo lo calcula el backend (D-20261008-01: nunca se confia en el
 * cliente). Si no viene (un backend anterior), el precio menos lo pagado. Un
 * ausente no debe el resto de un servicio que no recibio: su saldo es cero (lo
 * que pago es sena retenida, como la cuentan los reportes).
 */
const remainingOf = (
  appointmentStatus: string,
  price: number | null,
  paid: number,
  fromServer: number | null
): number => {
  if (appointmentStatus === 'absent' || price === null) return 0
  return fromServer ?? Math.max(price - paid, 0)
}

const toCents = (amount: number): number => Math.round(amount * 100)

/**
 * Lo cobrado en total: los cobros acreditados mas los restos pagados aparte.
 * La conciliacion los informa por separado (revision de la PR #137, S2); un
 * backend sin restos no manda el segundo importe.
 */
export const totalCollected = (
  approvedAmount: number | string | null | undefined,
  remainderAmount: number | string | null | undefined
): number => (toAmount(approvedAmount) ?? 0) + (toAmount(remainderAmount) ?? 0)

/**
 * El turno tiene un resto vivo: con el cobro pagado o devuelto (la devolucion
 * de la sena no lo revierte). Es lo que el admin puede revertir.
 */
export const hasLiveRemainder = (charge: AppointmentCharge): boolean =>
  (charge.kind === 'paid' && charge.remainderRecorded) ||
  (charge.kind === 'refunded' && charge.remainder !== null)

/** El importe es mayor a cero y entra en el saldo, al centavo. */
export const fitsRemaining = (amount: number, remaining: number): boolean =>
  toCents(amount) > 0 && toCents(amount) <= toCents(remaining)

/**
 * Se ofrece registrar el resto si el cobro esta acreditado, queda saldo y no
 * hay uno ya registrado: hay a lo sumo un resto por turno (D-20261008-01).
 */
export const canRecordRemainder = (charge: AppointmentCharge): boolean =>
  charge.kind === 'paid' && charge.remaining > 0 && !charge.remainderRecorded

/**
 * 2026-10-08 (decision de Mateo): el importe de "Confirmar pago" se precarga
 * con la sena pendiente si el turno tiene un cobro vivo; si no, con el precio
 * del turno menos lo pagado. Con un solo cobro por turno, "lo pagado" de un
 * turno sin cobro acreditado es cero.
 */
export const appointmentChargeOf = ({
  appointmentStatus,
  priceAmount,
  paymentStatus,
  paymentAmount,
  remainingAmount,
  remainderAmount
}: AppointmentChargeInput): AppointmentCharge => {
  const price = toAmount(priceAmount)
  const amount = toAmount(paymentAmount)
  if (paymentStatus && ACCREDITED_PAYMENT_STATUSES.includes(paymentStatus)) {
    const remainder = toAmount(remainderAmount)
    const paid = (amount ?? 0) + (remainder ?? 0)
    return {
      kind: 'paid',
      paid,
      remaining: remainingOf(appointmentStatus, price, paid, toAmount(remainingAmount)),
      remainderRecorded: remainder !== null
    }
  }
  if (paymentStatus === 'refunded') {
    return { kind: 'refunded', remainder: toAmount(remainderAmount) }
  }
  if (paymentStatus && LIVE_CHARGE_PAYMENT_STATUSES.includes(paymentStatus) && amount !== null) {
    return { kind: 'pending', amount, isDeposit: price !== null && amount < price }
  }
  return { kind: 'unpaid', suggested: price }
}
