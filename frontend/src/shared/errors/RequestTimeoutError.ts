import { ApplicationError } from './ApplicationError'

/**
 * Una lectura (GET) que vencio su timeout de 15 s sin respuesta
 * (D-20260930-02). Es operacional pero no se reintenta solo: otros 15 s de
 * espera no ayudan a quien mira la pantalla. Las escrituras no tienen timeout
 * en el cliente, asi que nunca terminan aca.
 */
export class RequestTimeoutError extends ApplicationError {
  public readonly code = 'REQUEST_TIMEOUT'
  public readonly statusCode = 0
  public readonly isOperational = true
}
