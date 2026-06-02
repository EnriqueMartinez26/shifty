import { ApplicationError } from './ApplicationError';

export class NetworkError extends ApplicationError {
  public readonly code = 'NETWORK_ERROR';
  public readonly statusCode = 0;
  public readonly isOperational = true;
}
export default NetworkError;
