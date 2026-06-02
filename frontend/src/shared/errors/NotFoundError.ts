import { ApplicationError } from './ApplicationError';

export class NotFoundError extends ApplicationError {
  public readonly code = 'NOT_FOUND_ERROR';
  public readonly statusCode = 404;
  public readonly isOperational = true;
}
export default NotFoundError;
