import { ApplicationError } from './ApplicationError';

export class ValidationError extends ApplicationError {
  public readonly code = 'VALIDATION_ERROR';
  public readonly statusCode = 400;
  public readonly isOperational = true;
}
export default ValidationError;
