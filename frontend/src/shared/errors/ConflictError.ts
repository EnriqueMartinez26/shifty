import { ApplicationError } from './ApplicationError'

export class ConflictError extends ApplicationError {
  public readonly code = 'CONFLICT_ERROR'
  public readonly statusCode = 409
  public readonly isOperational = true
}
export default ConflictError
