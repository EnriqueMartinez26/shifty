import { z } from 'zod'

/**
 * Base abstract class defining standard operations, validation,
 * automatic logging, performance tracing, retry mechanisms, and error boundaries for all domain services.
 *
 * @template T The primary domain entity type that this service manages.
 */
export abstract class BaseService<T> {
  /**
   * The repository instance that interacts with the persistence layer.
   * This is protected to forbid external direct access and keep core data manipulation encapsulated.
   */
  protected abstract repository: unknown

  /**
   * Internal representation of the generic type to satisfy strict TypeScript unused type parameter checks.
   */
  protected _phantomEntity?: T

  /**
   * Configures retry options for resilient operations.
   */
  protected retryOptions = {
    maxAttempts: 3,
    delayMs: 200
  }

  /**
   * Creates an instance of BaseService.
   */
  constructor() {
    // Initializer hook
  }

  /**
   * Execution template method. Wraps any asynchronous action in an automatic transaction-like flow.
   * This handles performance profiling, standardized success/error logging, retry logic, and centralized error translation.
   *
   * @template R The return type of the operation.
   * @param operation The callback performing the core database/API action.
   * @param operationName The name of the operation for logging purposes.
   * @returns A promise that resolves to the result of the operation.
   * @throws A standard service-level Error with localized messaging.
   */
  protected async execute<R>(operation: () => Promise<R>, operationName?: string): Promise<R> {
    const serviceName = this.constructor.name
    const fullOperationName = operationName
      ? `${serviceName}.${operationName}`
      : `${serviceName}.anonymousOperation`

    this.log('INFO', `${fullOperationName} - started`)
    const startTime = typeof performance !== 'undefined' ? performance.now() : Date.now()

    let attempt = 0

    while (true) {
      attempt++
      try {
        const result = await operation()
        const endTime = typeof performance !== 'undefined' ? performance.now() : Date.now()
        const duration = (endTime - startTime).toFixed(0)

        this.log('SUCCESS', `${fullOperationName} - completed (${duration}ms)`)
        return result
      } catch (error) {
        const isRetryable = this.isRetryableError(error)

        if (isRetryable && attempt < this.retryOptions.maxAttempts) {
          this.log(
            'WARNING',
            `${fullOperationName} - Attempt ${attempt} failed. Retrying in ${this.retryOptions.delayMs * attempt}ms... Error: ${error instanceof Error ? error.message : String(error)}`
          )
          await this.sleep(this.retryOptions.delayMs * attempt)
          continue
        }

        this.handleError(error)
      }
    }
  }

  /**
   * Validates target data against a Zod schema. If invalid, throws a validation error that is intercepted by handleError.
   *
   * @param data The payload to validate.
   * @param schema The zod schema.
   * @throws {z.ZodError} If data doesn't match the schema rules.
   */
  protected validate(data: unknown, schema?: any): void {
    if (!schema) {
      return
    }

    if (typeof schema.parse === 'function') {
      try {
        schema.parse(data)
      } catch (error) {
        this.handleError(error)
      }
    } else {
      this.log('WARNING', 'Validation schema is not a valid Zod schema.')
    }
  }

  /**
   * Centralized error handling. Evaluates internal exceptions (TypeErrors, ValidationErrors, NetworkErrors)
   * and translates them into uniform, sanitized user-friendly exceptions without exposing technical details.
   *
   * @param error The raw error to analyze.
   * @returns Never returns, always throws a sanitized exception.
   */
  protected handleError(error: unknown): never {
    const serviceName = this.constructor.name
    let userMessage = 'Ocurrió un error inesperado en la operación.'
    let errorStack = ''
    let details: unknown = null

    if (error instanceof z.ZodError) {
      userMessage = 'Error de validación: Verifique los datos ingresados.'
      details = error.issues.map((err) => ({
        path: err.path.join('.'),
        message: err.message
      }))

      const detailsStr = JSON.stringify(details)
      this.log('ERROR', `${serviceName} - Validation Failure.\nDetails: ${detailsStr}`)
    } else if (error instanceof TypeError) {
      userMessage = 'Error de tipo de datos interno.'
      errorStack = error.stack || ''
      this.log('ERROR', `${serviceName} - TypeError: ${error.message}\nStack: ${errorStack}`)
    } else if (error instanceof Error) {
      userMessage = error.message
      errorStack = error.stack || ''

      // If it's already an error containing custom details, let's keep them
      if ('details' in error) {
        details = (error as any).details
      }

      this.log('ERROR', `${serviceName} - Exception: ${error.message}\nStack: ${errorStack}`)
    } else {
      this.log('ERROR', `${serviceName} - Unknown critical error:`, error)
    }

    const friendlyError = new Error(userMessage)
    Object.assign(friendlyError, {
      originalError: error,
      details,
      timestamp: new Date().toISOString()
    })

    throw friendlyError
  }

  /**
   * Emits standardized logs to stdout / stderr based on severity level.
   *
   * @param level Log classification: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR'.
   * @param message Text to print.
   * @param data Optional context metadata.
   */
  protected log(level: string, message: string, data?: any): void {
    const formattedMessage = `[${level}] ${message}`

    if (level === 'ERROR') {
      if (data !== undefined) {
        console.error(formattedMessage, data)
      } else {
        console.error(formattedMessage)
      }
    } else {
      if (data !== undefined) {
        console.log(formattedMessage, data)
      } else {
        console.log(formattedMessage)
      }
    }
  }

  /**
   * Simple helper to delay execution. Used during retries.
   *
   * @param ms Delay length in milliseconds.
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  /**
   * Determines if the exception is temporary (e.g. Network error, server overloaded)
   * and should trigger the retry logic.
   *
   * @param error The raw error encountered.
   * @returns True if retryable, false otherwise.
   */
  private isRetryableError(error: unknown): boolean {
    if (!error) return false

    const message =
      error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase()

    // Check for common retryable scenarios like network timeout, connection refused, or locking issues
    return (
      message.includes('network') ||
      message.includes('timeout') ||
      message.includes('fetch') ||
      message.includes('rate limit') ||
      message.includes('locked') ||
      message.includes('econnrefused')
    )
  }
}
