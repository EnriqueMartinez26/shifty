# ⚙️ IMPROVEMENT 2: ABSTRACT SERVICE CLASSES

## 🎯 Goal
Create base `ServiceContainer` classes to enforce SRP and interface segregation.

**POO Gain**: +10%  
**Effort**: 3-4 days  
**Priority**: 🔴 CRITICAL (depends on: Improvement 1)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak Abstraction)
```typescript
// ❌ Monolithic service (violates SRP)
class UserService {
  constructor(private userRepository: IUserRepository) {}
  
  async getUsers() { ... }
  async getUserById(id: string) { ... }
  async createUser(input) { ... }
  async updateUser(id, input) { ... }
  async deleteUser(id) { ... }
  async changePassword(userId, oldPwd, newPwd) { ... }
  async resetPassword(userId, newPwd) { ... }
  async resendVerification(userId) { ... }
  // ... 30+ methods in one class
}

// Problems:
// 1. Too many reasons to change
// 2. Not testable in isolation
// 3. Violates SRP and ISP
```

### ✅ TARGET (Strong Abstraction)
```typescript
// ✅ Abstract base class enforces pattern
abstract class BaseService<T, CreateInput, UpdateInput> {
  protected abstract repository: IRepository<T>
  
  async getAll(): Promise<T[]> { ... }
  async getById(id: string): Promise<T | null> { ... }
  async create(input: CreateInput): Promise<T> { ... }
  async update(id: string, input: UpdateInput): Promise<T> { ... }
  async delete(id: string): Promise<void> { ... }
  
  protected abstract mapInputToEntity(input: CreateInput | UpdateInput): T
}

// ✅ Segregated interface for password operations
interface IUserSecurityService {
  changePassword(userId: string, oldPassword: string, newPassword: string): Promise<void>
  resetPassword(userId: string, newPassword: string): Promise<void>
}

// ✅ Service implements both interfaces (Interface Segregation)
class UserService extends BaseService<User, CreateUserInput, UpdateUserInput> {
  // CRUD operations from base class
}

class UserSecurityService implements IUserSecurityService {
  // Password operations only
}
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create BaseService Abstract Class

**File**: `frontend/src/core/services/BaseService.ts`

```typescript
/**
 * BaseService: Abstract base class for all services
 *
 * Enforces:
 * - Single Responsibility Principle (CRUD operations only)
 * - Dependency Injection (repository injection)
 * - Type Safety (generic types)
 * - Consistent error handling
 * - Logging and monitoring
 *
 * DDD Principles:
 * - mapInputToEntity: Aggregate construction
 * - Repository abstraction: Persistence independence
 */

import { IRepository } from '@domain/repositories/IRepository'

export interface IService<T, CreateInput, UpdateInput> {
  getAll(): Promise<T[]>
  getById(id: string): Promise<T | null>
  create(input: CreateInput): Promise<T>
  update(id: string, input: UpdateInput): Promise<T>
  delete(id: string): Promise<void>
}

export abstract class BaseService<T, CreateInput, UpdateInput>
  implements IService<T, CreateInput, UpdateInput>
{
  // Subclass must provide repository
  protected abstract repository: IRepository<T>

  /**
   * Retrieve all entities
   *
   * Throws:
   * - QueryError if database query fails
   */
  async getAll(): Promise<T[]> {
    try {
      const result = await this.repository.findAll()
      this.logOperation('getAll', `Retrieved ${result.length} entities`)
      return result
    } catch (error) {
      this.logError('getAll', error)
      throw this.handleRepositoryError(error)
    }
  }

  /**
   * Retrieve single entity by ID
   *
   * @param id - Entity identifier
   * @returns Entity or null if not found
   *
   * Throws:
   * - ValidationError if id is invalid
   * - QueryError if database query fails
   */
  async getById(id: string): Promise<T | null> {
    try {
      this.validateId(id)
      const result = await this.repository.findById(id)
      this.logOperation('getById', `Retrieved entity: ${id}`)
      return result
    } catch (error) {
      this.logError('getById', error)
      throw this.handleRepositoryError(error)
    }
  }

  /**
   * Create new entity
   *
   * @param input - Creation input (validated by DTO)
   * @returns Created entity
   *
   * Throws:
   * - ValidationError if input invalid
   * - DuplicateError if entity already exists
   * - PersistenceError if database fails
   */
  async create(input: CreateInput): Promise<T> {
    try {
      // Step 1: Map DTO to domain entity (this.mapInputToEntity)
      const entity = this.mapInputToEntity(input)

      // Step 2: Execute domain validations
      await this.validateEntity(entity)

      // Step 3: Persist to repository
      await this.repository.create(entity)

      // Step 4: Log operation
      this.logOperation('create', `Created entity`)

      return entity
    } catch (error) {
      this.logError('create', error)
      throw this.handleRepositoryError(error)
    }
  }

  /**
   * Update existing entity
   *
   * @param id - Entity identifier
   * @param input - Update input (validated by DTO)
   * @returns Updated entity
   *
   * Throws:
   * - ValidationError if input invalid
   * - NotFoundError if entity doesn't exist
   * - PersistenceError if database fails
   */
  async update(id: string, input: UpdateInput): Promise<T> {
    try {
      this.validateId(id)

      // Step 1: Fetch current entity
      const entity = await this.repository.findById(id)
      if (!entity) {
        throw this.createNotFoundError(id)
      }

      // Step 2: Apply updates
      const updates = this.mapInputToEntity(input)
      const updatedEntity = this.mergeUpdates(entity, updates)

      // Step 3: Validate updated entity
      await this.validateEntity(updatedEntity)

      // Step 4: Persist
      await this.repository.update(updatedEntity)

      this.logOperation('update', `Updated entity: ${id}`)

      return updatedEntity
    } catch (error) {
      this.logError('update', error)
      throw this.handleRepositoryError(error)
    }
  }

  /**
   * Delete entity
   *
   * @param id - Entity identifier
   *
   * Throws:
   * - NotFoundError if entity doesn't exist
   * - PersistenceError if database fails
   */
  async delete(id: string): Promise<void> {
    try {
      this.validateId(id)

      // Step 1: Check if entity exists
      const exists = await this.repository.findById(id)
      if (!exists) {
        throw this.createNotFoundError(id)
      }

      // Step 2: Delete
      await this.repository.delete(id)

      this.logOperation('delete', `Deleted entity: ${id}`)
    } catch (error) {
      this.logError('delete', error)
      throw this.handleRepositoryError(error)
    }
  }

  // ========================================================================
  // ABSTRACT METHODS (subclasses must implement)
  // ========================================================================

  /**
   * Map DTO/input to domain entity
   *
   * Subclass responsibility: Aggregate construction, value objects
   */
  protected abstract mapInputToEntity(
    input: CreateInput | UpdateInput
  ): T

  // ========================================================================
  // PROTECTED HELPER METHODS
  // ========================================================================

  /**
   * Validate ID format
   */
  protected validateId(id: string): void {
    if (!id || id.trim() === '') {
      throw new ValidationError('ID cannot be empty')
    }
  }

  /**
   * Validate entity (override in subclasses if needed)
   */
  protected async validateEntity(entity: T): Promise<void> {
    // Override in subclasses for custom validation
  }

  /**
   * Merge updates into existing entity
   * Override in subclasses for custom merge logic
   */
  protected mergeUpdates(entity: T, updates: T): T {
    return { ...entity, ...updates }
  }

  /**
   * Handle repository errors consistently
   */
  protected handleRepositoryError(error: any): Error {
    if (error.isRepositoryError) {
      return error
    }

    if (error instanceof Error) {
      return new RepositoryError(error.message, error.cause)
    }

    return new RepositoryError('Unknown error occurred')
  }

  /**
   * Create not found error (override for custom messages)
   */
  protected createNotFoundError(id: string): Error {
    return new NotFoundError(`Entity with ID ${id} not found`)
  }

  /**
   * Logging (can be overridden or injected)
   */
  protected logOperation(method: string, message: string): void {
    console.log(`✅ [${this.constructor.name}] ${method}: ${message}`)
  }

  protected logError(method: string, error: any): void {
    console.error(`❌ [${this.constructor.name}] ${method}:`, error)
  }
}

// ============================================================================
// CUSTOM ERRORS
// ============================================================================

export class ValidationError extends Error {
  readonly code = 'VALIDATION_ERROR'
  readonly statusCode = 422

  constructor(message: string, public field?: string) {
    super(message)
    this.name = 'ValidationError'
    Object.setPrototypeOf(this, ValidationError.prototype)
  }
}

export class NotFoundError extends Error {
  readonly code = 'NOT_FOUND'
  readonly statusCode = 404

  constructor(message: string) {
    super(message)
    this.name = 'NotFoundError'
    Object.setPrototypeOf(this, NotFoundError.prototype)
  }
}

export class RepositoryError extends Error {
  readonly code = 'REPOSITORY_ERROR'
  readonly statusCode = 500
  readonly isRepositoryError = true

  constructor(message: string, public cause?: any) {
    super(message)
    this.name = 'RepositoryError'
    Object.setPrototypeOf(this, RepositoryError.prototype)
  }
}
```

### Step 2: Segregated Service Interfaces

**File**: `frontend/src/application/services/user-service-interfaces.ts`

```typescript
/**
 * Segregated service interfaces
 *
 * ISP (Interface Segregation Principle):
 * Clients should not be forced to depend on interfaces they don't use.
 *
 * Instead of: IUserService with 20 methods
 * We have: IUserCRUDService, IUserSecurityService, IUserNotificationService
 */

import { User } from '@domain/entities/User'
import { CreateUserInput, UpdateUserInput } from '@application/dtos/user-dtos'

// Core CRUD operations (most common)
export interface IUserCRUDService {
  getAll(): Promise<User[]>
  getById(id: string): Promise<User | null>
  create(input: CreateUserInput): Promise<User>
  update(id: string, input: UpdateUserInput): Promise<User>
  delete(id: string): Promise<void>
}

// Security operations (segregated)
export interface IUserSecurityService {
  changePassword(
    userId: string,
    oldPassword: string,
    newPassword: string
  ): Promise<void>

  resetPassword(userId: string, newPassword: string): Promise<void>

  verifyEmail(userId: string, token: string): Promise<void>

  resendVerificationEmail(userId: string): Promise<void>
}

// Notification operations (segregated)
export interface IUserNotificationService {
  notifyUserCreated(userId: string): Promise<void>

  notifyPasswordChanged(userId: string): Promise<void>

  sendNotification(userId: string, message: string): Promise<void>
}

// Profile operations (segregated)
export interface IUserProfileService {
  updateProfile(userId: string, profile: any): Promise<User>

  uploadAvatar(userId: string, file: File): Promise<string>

  deleteAvatar(userId: string): Promise<void>
}
```

### Step 3: Implement Concrete Service with Segregation

**File**: `frontend/src/application/services/user-service.ts`

```typescript
import { BaseService, ValidationError } from '@core/services/BaseService'
import { User } from '@domain/entities/User'
import { IUserRepository } from '@domain/repositories/IUserRepository'
import {
  IUserCRUDService,
  IUserSecurityService,
  IUserProfileService
} from './user-service-interfaces'
import {
  CreateUserInput,
  UpdateUserInput
} from '@application/dtos/user-dtos'

/**
 * UserService: Implements multiple segregated interfaces
 *
 * This shows how one service can implement multiple interfaces
 * while extending BaseService.
 *
 * Each interface handles different concerns (SRP).
 */
class UserService
  extends BaseService<User, CreateUserInput, UpdateUserInput>
  implements IUserCRUDService, IUserSecurityService
{
  protected repository: IUserRepository

  constructor(userRepository: IUserRepository) {
    super()
    this.repository = userRepository
  }

  // ========================================================================
  // CRUD Operations (from BaseService)
  // ========================================================================
  // getAll, getById, create, update, delete inherited from BaseService

  // ========================================================================
  // SECURITY OPERATIONS (IUserSecurityService)
  // ========================================================================

  async changePassword(
    userId: string,
    oldPassword: string,
    newPassword: string
  ): Promise<void> {
    const user = await this.repository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    // Verify old password
    const isValid = await user.verifyPassword(oldPassword)
    if (!isValid) throw new ValidationError('Old password is incorrect')

    // Set new password
    user.setPassword(newPassword)

    await this.repository.update(user)
    this.logOperation('changePassword', `Password changed for user ${userId}`)
  }

  async resetPassword(userId: string, newPassword: string): Promise<void> {
    const user = await this.repository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    user.setPassword(newPassword)
    await this.repository.update(user)

    this.logOperation('resetPassword', `Password reset for user ${userId}`)
  }

  async verifyEmail(userId: string, token: string): Promise<void> {
    const user = await this.repository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    const isValid = user.verifyEmailToken(token)
    if (!isValid) throw new ValidationError('Invalid or expired token')

    user.markEmailAsVerified()
    await this.repository.update(user)

    this.logOperation('verifyEmail', `Email verified for user ${userId}`)
  }

  async resendVerificationEmail(userId: string): Promise<void> {
    const user = await this.repository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    // Generate new token
    const token = user.generateEmailVerificationToken()

    // In real app: send email
    console.log(`📧 Verification email would be sent with token: ${token}`)

    this.logOperation(
      'resendVerificationEmail',
      `Verification email resent to ${userId}`
    )
  }

  // ========================================================================
  // ABSTRACT METHOD IMPLEMENTATION
  // ========================================================================

  protected mapInputToEntity(
    input: CreateUserInput | UpdateUserInput
  ): User {
    // Create domain entity from DTO
    // This is where value objects are constructed
    return User.create({
      email: input.email,
      name: input.name,
      role: input.role
    })
  }
}

export { UserService }
```

### Step 4: Separate Service for Password Operations

**File**: `frontend/src/application/services/user-security-service.ts`

```typescript
/**
 * UserSecurityService: Dedicated to security operations
 *
 * If UserService becomes too large, extract concerns into separate services.
 * This is pure SRP: each service has ONE reason to change.
 */

import { IUserSecurityService } from './user-service-interfaces'
import { IUserRepository } from '@domain/repositories/IUserRepository'

class UserSecurityService implements IUserSecurityService {
  constructor(private userRepository: IUserRepository) {}

  async changePassword(
    userId: string,
    oldPassword: string,
    newPassword: string
  ): Promise<void> {
    const user = await this.userRepository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    const isValid = await user.verifyPassword(oldPassword)
    if (!isValid) throw new Error('Old password is incorrect')

    user.setPassword(newPassword)
    await this.userRepository.update(user)
  }

  async resetPassword(userId: string, newPassword: string): Promise<void> {
    const user = await this.userRepository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    user.setPassword(newPassword)
    await this.userRepository.update(user)
  }

  async verifyEmail(userId: string, token: string): Promise<void> {
    const user = await this.userRepository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    const isValid = user.verifyEmailToken(token)
    if (!isValid) throw new Error('Invalid or expired token')

    user.markEmailAsVerified()
    await this.userRepository.update(user)
  }

  async resendVerificationEmail(userId: string): Promise<void> {
    const user = await this.userRepository.findById(userId)
    if (!user) throw new Error(`User ${userId} not found`)

    const token = user.generateEmailVerificationToken()
    // Send email with token
  }
}

export { UserSecurityService }
```

---

## ✅ Checklist

- [ ] Create `BaseService.ts`
- [ ] Create segregated interface files
- [ ] Refactor `UserService` to extend `BaseService`
- [ ] Refactor `StaffService` to extend `BaseService`
- [ ] Refactor `ServiceService` to extend `BaseService`
- [ ] Refactor `AppointmentService` to extend `BaseService`
- [ ] Refactor `BookingService` to extend `BaseService`
- [ ] Create segregated service implementations
- [ ] Update DI container with new services
- [ ] Create comprehensive tests

---

## 🎯 Success Criteria

✅ All services extend `BaseService`  
✅ Each service implements segregated interfaces  
✅ No service has more than 5 public methods per interface  
✅ Error handling consistent across all services  
✅ 100% of CRUD operations use base class  
✅ Tests verify SRP  

