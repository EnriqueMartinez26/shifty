import { ApplicationError } from './ApplicationError'

/** 402: la operacion necesita un pago (p. ej. suscripcion suspendida). */
export class PaymentRequiredError extends ApplicationError {
  public readonly code = 'PAYMENT_REQUIRED_ERROR'
  public readonly statusCode = 402
  public readonly isOperational = true
}
