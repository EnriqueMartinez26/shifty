import { ApplicationError } from './ApplicationError'

export class ForbiddenError extends ApplicationError {
  public readonly code = 'FORBIDDEN_ERROR'
  public readonly statusCode = 403
  public readonly isOperational = true
}
export default ForbiddenError
