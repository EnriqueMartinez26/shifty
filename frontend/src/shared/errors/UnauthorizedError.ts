import { ApplicationError } from './ApplicationError';

export class UnauthorizedError extends ApplicationError {
  public readonly code = 'UNAUTHORIZED_ERROR';
  public readonly statusCode = 401;
  public readonly isOperational = true;
}
export default UnauthorizedError;
