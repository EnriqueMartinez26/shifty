import { ApplicationError } from './ApplicationError'

export class InternalServerError extends ApplicationError {
  public readonly code = 'INTERNAL_SERVER_ERROR'
  public readonly statusCode = 500
  public readonly isOperational = false
}
export default InternalServerError
