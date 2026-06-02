# 🚨 IMPROVEMENT 6: ERROR HIERARCHY & EXCEPTION HANDLING

## 🎯 Goal
Create comprehensive error hierarchy with Strategy pattern handlers for consistent error management.

**POO Gain**: +3%  
**Effort**: 1-2 days  
**Priority**: 🟡 HIGH (depends on: Improvements 1-2)

---

## 🏗️ IMPLEMENTATION

### Step 1: Domain Error Hierarchy

**File**: `frontend/src/core/errors/DomainError.ts`

```typescript
/**
 * Domain Error Hierarchy
 *
 * Hierarchy:
 * DomainError (abstract)
 *   ├── ValidationError
 *   ├── NotFoundError
 *   ├── ConflictError
 *   ├── UnauthorizedError
 *   ├── ForbiddenError
 *   └── BusinessRuleError
 */

export abstract class DomainError extends Error {
  abstract readonly code: string
  abstract readonly statusCode: number

  constructor(message: string) {
    super(message)
    this.name = this.constructor.name
    Object.setPrototypeOf(this, DomainError.prototype)
  }

  /**
   * Convert to API response
   */
  toResponse() {
    return {
      error: this.code,
      message: this.message,
      statusCode: this.statusCode
    }
  }

  /**
   * Log for monitoring
   */
  toLog() {
    return {
      name: this.name,
      message: this.message,
      code: this.code,
      stack: this.stack
    }
  }
}

/**
 * Validation failed (422)
 */
export class ValidationError extends DomainError {
  readonly code = 'VALIDATION_ERROR'
  readonly statusCode = 422

  constructor(message: string, public field?: string) {
    super(message)
    Object.setPrototypeOf(this, ValidationError.prototype)
  }
}

/**
 * Resource not found (404)
 */
export class NotFoundError extends DomainError {
  readonly code = 'NOT_FOUND'
  readonly statusCode = 404

  constructor(message: string, public resource?: string) {
    super(message)
    Object.setPrototypeOf(this, NotFoundError.prototype)
  }
}

/**
 * Resource already exists (409)
 */
export class ConflictError extends DomainError {
  readonly code = 'CONFLICT'
  readonly statusCode = 409

  constructor(message: string) {
    super(message)
    Object.setPrototypeOf(this, ConflictError.prototype)
  }
}

/**
 * Not authenticated (401)
 */
export class UnauthorizedError extends DomainError {
  readonly code = 'UNAUTHORIZED'
  readonly statusCode = 401

  constructor(message: string = 'Authentication required') {
    super(message)
    Object.setPrototypeOf(this, UnauthorizedError.prototype)
  }
}

/**
 * No permission (403)
 */
export class ForbiddenError extends DomainError {
  readonly code = 'FORBIDDEN'
  readonly statusCode = 403

  constructor(message: string = 'Insufficient permissions') {
    super(message)
    Object.setPrototypeOf(this, ForbiddenError.prototype)
  }
}

/**
 * Business rule violation
 */
export class BusinessRuleError extends DomainError {
  readonly code = 'BUSINESS_RULE_ERROR'
  readonly statusCode = 422

  constructor(message: string) {
    super(message)
    Object.setPrototypeOf(this, BusinessRuleError.prototype)
  }
}

/**
 * Unexpected error
 */
export class UnexpectedError extends DomainError {
  readonly code = 'UNEXPECTED_ERROR'
  readonly statusCode = 500

  constructor(message: string = 'An unexpected error occurred') {
    super(message)
    Object.setPrototypeOf(this, UnexpectedError.prototype)
  }
}
```

### Step 2: Error Handlers (Strategy Pattern)

**File**: `frontend/src/core/errors/ErrorHandler.ts`

```typescript
/**
 * Error Handler Strategy Pattern
 *
 * Each error type has specific handling logic.
 * New error types can be added without modifying existing handlers.
 */

import { DomainError } from './DomainError'

export interface IErrorHandler {
  canHandle(error: Error): boolean
  handle(error: Error): void
}

/**
 * Base handler with common functionality
 */
export abstract class BaseErrorHandler implements IErrorHandler {
  abstract canHandle(error: Error): boolean
  abstract handle(error: Error): void

  /**
   * Show toast notification
   */
  protected showToast(message: string, type: 'error' | 'warning' | 'info') {
    // Integration with toast library (e.g., react-toastify)
    console.log(`[${type.toUpperCase()}] ${message}`)
  }

  /**
   * Log for monitoring
   */
  protected logError(error: Error) {
    console.error(error)
    // Send to monitoring service (e.g., Sentry)
  }

  /**
   * Retry operation
   */
  protected shouldRetry(error: Error): boolean {
    return false
  }
}

/**
 * Handle validation errors
 */
export class ValidationErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return error.constructor.name === 'ValidationError'
  }

  handle(error: DomainError) {
    const field = (error as any).field
    const fieldInfo = field ? ` (${field})` : ''
    this.showToast(`Please check your input${fieldInfo}: ${error.message}`, 'warning')
    this.logError(error)
  }
}

/**
 * Handle not found errors
 */
export class NotFoundErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return error.constructor.name === 'NotFoundError'
  }

  handle(error: DomainError) {
    const resource = (error as any).resource || 'Resource'
    this.showToast(`${resource} not found`, 'error')
    this.logError(error)
  }
}

/**
 * Handle conflict errors
 */
export class ConflictErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return error.constructor.name === 'ConflictError'
  }

  handle(error: DomainError) {
    this.showToast(`This action conflicts with existing data: ${error.message}`, 'error')
    this.logError(error)
  }
}

/**
 * Handle authorization errors
 */
export class UnauthorizedErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return error.constructor.name === 'UnauthorizedError'
  }

  handle(error: DomainError) {
    this.showToast('Your session has expired. Please log in again.', 'error')
    // Redirect to login
    window.location.href = '/login'
  }
}

/**
 * Handle permission errors
 */
export class ForbiddenErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return error.constructor.name === 'ForbiddenError'
  }

  handle(error: DomainError) {
    this.showToast('You do not have permission to perform this action', 'error')
    this.logError(error)
  }
}

/**
 * Handle network errors
 */
export class NetworkErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return error.constructor.name.includes('AxiosError') ||
           error.message.includes('network')
  }

  handle(error: Error) {
    this.showToast(
      'Network error. Please check your connection and try again.',
      'error'
    )
    this.logError(error)
  }
}

/**
 * Handle unexpected errors
 */
export class UnexpectedErrorHandler extends BaseErrorHandler {
  canHandle(error: Error): boolean {
    return true  // Catch-all
  }

  handle(error: Error) {
    console.error('Unexpected error:', error)
    this.showToast(
      'An unexpected error occurred. Our team has been notified.',
      'error'
    )
    this.logError(error)
  }
}
```

### Step 3: Global Error Handler

**File**: `frontend/src/core/errors/GlobalErrorHandler.ts`

```typescript
/**
 * Global Error Handler
 *
 * Coordinates all error handlers and provides centralized error management.
 */

import { IErrorHandler } from './ErrorHandler'

export class GlobalErrorHandler {
  private static instance: GlobalErrorHandler
  private handlers: IErrorHandler[] = []

  private constructor() {}

  static getInstance(): GlobalErrorHandler {
    if (!GlobalErrorHandler.instance) {
      GlobalErrorHandler.instance = new GlobalErrorHandler()
    }
    return GlobalErrorHandler.instance
  }

  /**
   * Register error handler
   */
  register(handler: IErrorHandler): void {
    this.handlers.push(handler)
  }

  /**
   * Handle error with registered handlers
   */
  handle(error: Error): void {
    // Find first handler that can handle this error
    const handler = this.handlers.find(h => h.canHandle(error))

    if (handler) {
      handler.handle(error)
    } else {
      // Fallback: log unknown error
      console.error('No handler for error:', error)
    }
  }

  /**
   * Register multiple handlers at once
   */
  registerHandlers(...handlers: IErrorHandler[]): void {
    handlers.forEach(h => this.register(h))
  }

  /**
   * Clear all handlers (for testing)
   */
  clear(): void {
    this.handlers = []
  }
}
```

### Step 4: Integration in App

**File**: `frontend/src/main.tsx`

```typescript
import { GlobalErrorHandler } from '@core/errors/GlobalErrorHandler'
import {
  ValidationErrorHandler,
  NotFoundErrorHandler,
  ConflictErrorHandler,
  UnauthorizedErrorHandler,
  ForbiddenErrorHandler,
  NetworkErrorHandler,
  UnexpectedErrorHandler
} from '@core/errors/ErrorHandler'

// Setup global error handling
const errorHandler = GlobalErrorHandler.getInstance()
errorHandler.registerHandlers(
  new ValidationErrorHandler(),
  new NotFoundErrorHandler(),
  new ConflictErrorHandler(),
  new UnauthorizedErrorHandler(),
  new ForbiddenErrorHandler(),
  new NetworkErrorHandler(),
  new UnexpectedErrorHandler()
)

// Setup React Query error handling
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      onError: (error) => {
        errorHandler.handle(error as Error)
      }
    },
    mutations: {
      onError: (error) => {
        errorHandler.handle(error as Error)
      }
    }
  }
})
```

### Step 5: Usage in Services

**File**: `frontend/src/application/services/user-service.ts`

```typescript
import { ValidationError, NotFoundError } from '@core/errors/DomainError'

async changePassword(userId: string, oldPassword: string, newPassword: string) {
  const user = await this.userRepository.findById(userId)

  if (!user) {
    throw new NotFoundError('User not found', 'User')
  }

  if (oldPassword.length < 8) {
    throw new ValidationError('Password must be at least 8 characters', 'password')
  }

  // ... rest of logic
}
```

### Step 6: Testing Error Handling

**File**: `frontend/src/__tests__/core/errors/ErrorHandling.test.ts`

```typescript
import { GlobalErrorHandler } from '@core/errors/GlobalErrorHandler'
import {
  ValidationError,
  NotFoundError,
  ValidationErrorHandler,
  NotFoundErrorHandler
} from '@core/errors'

describe('Error Handling - Strategy Pattern', () => {
  let handler: GlobalErrorHandler

  beforeEach(() => {
    handler = GlobalErrorHandler.getInstance()
    handler.clear()
  })

  it('should route to correct handler', () => {
    const validationHandler = new ValidationErrorHandler()
    handler.register(validationHandler)

    const spy = jest.spyOn(validationHandler, 'handle')

    const error = new ValidationError('Invalid input', 'email')
    handler.handle(error)

    expect(spy).toHaveBeenCalled()
  })

  it('should handle multiple error types', () => {
    handler.registerHandlers(
      new ValidationErrorHandler(),
      new NotFoundErrorHandler()
    )

    const validationError = new ValidationError('Invalid')
    const notFoundError = new NotFoundError('Not found')

    expect(() => handler.handle(validationError)).not.toThrow()
    expect(() => handler.handle(notFoundError)).not.toThrow()
  })
})
```

---

## ✅ Checklist

- [ ] Create error hierarchy classes
- [ ] Create error handler strategies
- [ ] Create global error handler coordinator
- [ ] Register handlers in app initialization
- [ ] Integrate with React Query
- [ ] Update services to throw domain errors
- [ ] Create comprehensive error tests
- [ ] Add error monitoring integration (Sentry)

---

## 🎯 Success Criteria

✅ All errors extend `DomainError`  
✅ Each error type has dedicated handler  
✅ Error handling consistent across app  
✅ New errors added without modifying existing handlers  
✅ Tests verify error routing  
✅ User-friendly error messages  

