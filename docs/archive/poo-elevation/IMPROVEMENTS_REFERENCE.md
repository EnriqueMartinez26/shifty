# POO Improvements Reference - Consolidated

## Reference: 01-IMPROVEMENT_DI_CONTAINER.md

# 🔌 IMPROVEMENT 1: DEPENDENCY INJECTION CONTAINER

## 🎯 Goal
Centralize dependency management using a Service Container (DIP - Dependency Inversion Principle).

**POO Gain**: +8%  
**Effort**: 2-3 days  
**Priority**: 🔴 CRITICAL (blocks improvements 2-5)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak DIP)
```typescript
// ❌ Ad-hoc factory pattern (not DI)
function useUsers() {
  const userService = new UserService(
    new HttpUserRepository(apiClient)  // NEW instance every render!
  )
  return useQuery(['users'], () => userService.getUsers())
}

// Problems:
// 1. New instance on every hook call
// 2. Difficult to swap implementations (testing)
// 3. No centralized dependency graph
// 4. Violates DIP (depends on concrete implementations)
```

### ✅ TARGET (Strong DIP)
```typescript
// ✅ Proper DI container
class ServiceContainer {
  private static instance: ServiceContainer
  private services: Map<string, () => any> = new Map()
  
  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }
  
  register(key: string, factory: () => any): void {
    this.services.set(key, factory)
  }
  
  get<T>(key: string): T {
    const factory = this.services.get(key)
    if (!factory) throw new Error(`Service "${key}" not registered`)
    return factory() as T
  }
}

// Usage in hook
function useUsers() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  return useQuery(['users'], () => userService.getAll())
}
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create ServiceContainer

**File**: `frontend/src/core/di/ServiceContainer.ts`

```typescript
/**
 * ServiceContainer: Central Dependency Injection Container
 *
 * Principles:
 * - Singleton pattern (single instance across app)
 * - Factory functions (lazy instantiation)
 * - Type-safe service retrieval
 * - Centralized dependency graph
 *
 * DIP: Depend on abstractions (interfaces), not implementations
 */

export class ServiceContainer {
  private static instance: ServiceContainer | null = null
  private services: Map<string, () => any> = new Map()
  private singletons: Map<string, any> = new Map()
  private initialized: boolean = false

  private constructor() {
    // Private constructor enforces singleton
  }

  /**
   * Get or create the singleton instance
   */
  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }

  /**
   * Reset for testing purposes
   */
  static reset(): void {
    ServiceContainer.instance = null
  }

  /**
   * Register a service factory
   *
   * @param key - Service identifier
   * @param factory - Function that creates the service
   * @param options - { singleton: true } to cache instance
   *
   * Example:
   * container.register('userService', () => {
   *   return new UserService(container.get('userRepository'))
   * })
   */
  register<T = any>(
    key: string,
    factory: () => T,
    options: { singleton?: boolean } = {}
  ): void {
    if (this.services.has(key)) {
      console.warn(`Service "${key}" already registered, overwriting`)
    }

    this.services.set(key, factory)

    if (options.singleton) {
      // Pre-create singleton
      this.singletons.set(key, factory())
    }
  }

  /**
   * Retrieve a service instance
   *
   * @param key - Service identifier
   * @returns Service instance or throws if not registered
   *
   * Example:
   * const userService = container.get<UserService>('userService')
   */
  get<T = any>(key: string): T {
    // Check singleton cache first
    if (this.singletons.has(key)) {
      return this.singletons.get(key) as T
    }

    const factory = this.services.get(key)
    if (!factory) {
      throw new ServiceNotFoundError(
        `Service "${key}" not registered. Register it in dependencies.ts`
      )
    }

    return factory() as T
  }

  /**
   * Check if service is registered
   */
  has(key: string): boolean {
    return this.services.has(key) || this.singletons.has(key)
  }

  /**
   * Initialize all singleton services
   * Call this after all registrations are complete
   */
  initialize(): void {
    if (this.initialized) return

    const singletonKeys = Array.from(this.services.entries())
      .filter(([_, __]) => this.singletons.has(_))
      .map(([key, _]) => key)

    for (const key of singletonKeys) {
      this.get(key)
    }

    this.initialized = true
  }

  /**
   * Get all registered service keys (for debugging)
   */
  getRegisteredServices(): string[] {
    return Array.from(this.services.keys())
  }

  /**
   * Clear all services (for testing)
   */
  clear(): void {
    this.services.clear()
    this.singletons.clear()
    this.initialized = false
  }
}

/**
 * Custom error for missing services
 */
export class ServiceNotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ServiceNotFoundError'
  }
}
```

### Step 2: Create Dependencies Registration

**File**: `frontend/src/core/di/dependencies.ts`

```typescript
/**
 * Dependencies: Central registration of all services
 *
 * This file is THE SOURCE OF TRUTH for the dependency graph.
 * All services are registered here, making it easy to:
 * - Understand what services exist
 * - Swap implementations (for testing)
 * - Add new services
 * - Debug dependency issues
 */

import { ServiceContainer } from './ServiceContainer'

// Repositories (Infrastructure)
import { HttpUserRepository } from '@infrastructure/repositories/http-user-repository'
import { HttpStaffRepository } from '@infrastructure/repositories/http-staff-repository'
import { HttpServiceRepository } from '@infrastructure/repositories/http-service-repository'
import { HttpAppointmentRepository } from '@infrastructure/repositories/http-appointment-repository'
import { HttpBookingRepository } from '@infrastructure/repositories/http-booking-repository'

// Services (Application)
import { UserService } from '@application/services/user-service'
import { StaffService } from '@application/services/staff-service'
import { ServiceService } from '@application/services/service-service'
import { AppointmentService } from '@application/services/appointment-service'
import { BookingService } from '@application/services/booking-service'

// HTTP Client (Infrastructure)
import { apiClient } from '@infrastructure/http/client'

export function registerDependencies(): void {
  const container = ServiceContainer.getInstance()

  // ============================================================================
  // LAYER 1: INFRASTRUCTURE (External adapters)
  // ============================================================================

  // HTTP Client (singleton - reuse across app)
  container.register(
    'apiClient',
    () => apiClient,
    { singleton: true }
  )

  // Repositories (singletons - one repository per resource)
  container.register(
    'userRepository',
    () => new HttpUserRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'staffRepository',
    () => new HttpStaffRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'serviceRepository',
    () => new HttpServiceRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'appointmentRepository',
    () => new HttpAppointmentRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'bookingRepository',
    () => new HttpBookingRepository(container.get('apiClient')),
    { singleton: true }
  )

  // ============================================================================
  // LAYER 2: APPLICATION (Services)
  // ============================================================================

  // Services (singletons - one service per domain entity)
  container.register(
    'userService',
    () => new UserService(
      container.get('userRepository'),
      container.get('eventBus')  // Will add in improvement 7
    ),
    { singleton: true }
  )

  container.register(
    'staffService',
    () => new StaffService(
      container.get('staffRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  container.register(
    'serviceService',
    () => new ServiceService(
      container.get('serviceRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  container.register(
    'appointmentService',
    () => new AppointmentService(
      container.get('appointmentRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  container.register(
    'bookingService',
    () => new BookingService(
      container.get('bookingRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  // ============================================================================
  // LAYER 3: PRESENTATION (Utilities)
  // ============================================================================

  // Query client (React Query singleton)
  container.register(
    'queryClient',
    () => {
      const QueryClient = require('@tanstack/react-query').QueryClient
      return new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5 * 60 * 1000 },
          mutations: { retry: 1 }
        }
      })
    },
    { singleton: true }
  )

  // ============================================================================
  // Mark container as initialized
  // ============================================================================

  container.initialize()
}

/**
 * Convenience function to reset dependencies (for testing)
 */
export function resetDependencies(): void {
  ServiceContainer.reset()
}

/**
 * Get container instance
 */
export function getContainer(): ServiceContainer {
  return ServiceContainer.getInstance()
}
```

### Step 3: Initialize Container in App

**File**: `frontend/src/main.tsx`

```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import { registerDependencies } from '@core/di/dependencies'
import App from './App'
import './index.css'

// Initialize Dependency Injection Container
// Must be called before any services are used
registerDependencies()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

### Step 4: Create DI Hook Factory

**File**: `frontend/src/presentation/hooks/useService.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Hook to access any service from DI container
 *
 * Usage:
 * const userService = useService<UserService>('userService')
 * const userService = useService('userService')  // with type inference
 */
export function useService<T = any>(key: string): T {
  const container = ServiceContainer.getInstance()

  if (!container.has(key)) {
    throw new Error(
      `Service "${key}" not found. Make sure it's registered in dependencies.ts`
    )
  }

  return container.get<T>(key)
}

/**
 * Advanced: Hook with service validation
 */
export function useServiceWithFallback<T>(
  key: string,
  fallback: T
): T {
  const container = ServiceContainer.getInstance()

  if (!container.has(key)) {
    console.warn(`Service "${key}" not found, using fallback`)
    return fallback
  }

  return container.get<T>(key)
}
```

### Step 5: Update Hooks to Use DI

**File**: `frontend/src/presentation/hooks/use-users.ts` (Example)

```typescript
// BEFORE: ❌ New service on every hook call
// function useUsers() {
//   const userService = new UserService(
//     new HttpUserRepository(apiClient)
//   )
//   return useQuery(['users'], () => userService.getUsers())
// }

// AFTER: ✅ Using DI container
import { useQuery } from '@tanstack/react-query'
import { useService } from './useService'
import { UserService } from '@application/services/user-service'

export function useUsers() {
  // Get service from DI container (same instance)
  const userService = useService<UserService>('userService')

  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getAll(),
    staleTime: 5 * 60 * 1000
  })
}

export function useCreateUser() {
  const userService = useService<UserService>('userService')

  return useMutation({
    mutationFn: (input: CreateUserInput) => userService.create(input),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}
```

---

## 🧪 Testing DI Container

**File**: `frontend/src/__tests__/core/di/ServiceContainer.test.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

describe('ServiceContainer - DI Container', () => {
  let container: ServiceContainer

  beforeEach(() => {
    ServiceContainer.reset()
    container = ServiceContainer.getInstance()
  })

  afterEach(() => {
    container.clear()
  })

  describe('Singleton Pattern', () => {
    it('should return same instance', () => {
      const instance1 = ServiceContainer.getInstance()
      const instance2 = ServiceContainer.getInstance()

      expect(instance1).toBe(instance2)
    })
  })

  describe('Service Registration', () => {
    it('should register and retrieve service', () => {
      const mockService = { name: 'test' }
      container.register('test', () => mockService)

      expect(container.get('test')).toBe(mockService)
    })

    it('should throw error if service not registered', () => {
      expect(() => container.get('nonexistent')).toThrow()
    })

    it('should check if service exists', () => {
      container.register('exists', () => ({}))

      expect(container.has('exists')).toBe(true)
      expect(container.has('notexists')).toBe(false)
    })
  })

  describe('Singleton Services', () => {
    it('should return same instance for singleton', () => {
      let callCount = 0
      container.register(
        'singleton',
        () => {
          callCount++
          return { id: callCount }
        },
        { singleton: true }
      )

      const first = container.get('singleton')
      const second = container.get('singleton')

      expect(first).toBe(second)
      expect(callCount).toBe(1)
    })

    it('should create new instance for non-singleton', () => {
      let callCount = 0
      container.register('factory', () => {
        callCount++
        return { id: callCount }
      })

      const first = container.get('factory')
      const second = container.get('factory')

      expect(first.id).toBe(1)
      expect(second.id).toBe(2)
      expect(callCount).toBe(2)
    })
  })

  describe('Dependency Graph', () => {
    it('should resolve complex dependency graph', () => {
      // Mock repositories
      container.register('userRepository', () => ({ name: 'userRepo' }))

      // Mock service depending on repository
      container.register(
        'userService',
        () => {
          const userRepo = container.get('userRepository')
          return { repository: userRepo, name: 'userService' }
        },
        { singleton: true }
      )

      const service = container.get('userService')

      expect(service.name).toBe('userService')
      expect(service.repository.name).toBe('userRepo')
    })
  })

  describe('Type Safety', () => {
    interface UserService {
      getUsers(): Promise<any[]>
    }

    it('should maintain type safety', () => {
      const mockService: UserService = {
        getUsers: async () => []
      }

      container.register('userService', () => mockService)

      const service = container.get<UserService>('userService')
      expect(typeof service.getUsers).toBe('function')
    })
  })
})
```

---

## ✅ Checklist

- [ ] Create `ServiceContainer.ts`
- [ ] Create `dependencies.ts`
- [ ] Update `main.tsx` to call `registerDependencies()`
- [ ] Create `useService.ts` hook
- [ ] Update all hooks to use `useService()`
- [ ] Create unit tests
- [ ] Test in browser (no console errors)
- [ ] Document in team wiki

---

## 🎯 Success Criteria

✅ All services registered in one place  
✅ No `new ServiceName()` in components  
✅ All hooks use `useService()`  
✅ Tests can easily swap implementations  
✅ Build passes with zero errors  
✅ Team understands DI pattern  

---

## 📚 Learning Resources

- **SOLID**: https://en.wikipedia.org/wiki/SOLID
- **DIP**: https://en.wikipedia.org/wiki/Dependency_inversion_principle
- **Service Locator Pattern**: https://martinfowler.com/articles/service-locator.html
- **TypeScript DI**: https://inversify.io/



## Reference: 02-IMPROVEMENT_ABSTRACT_SERVICES.md

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



## Reference: 03-IMPROVEMENT_VALUE_OBJECTS.md

# 💎 IMPROVEMENT 3: VALUE OBJECT ENFORCEMENT

## 🎯 Goal
Enforce encapsulation in domain entities and value objects using proper classes with private fields.

**POO Gain**: +8%  
**Effort**: 3-4 days  
**Priority**: 🔴 CRITICAL (depends on: Improvement 2)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak Encapsulation)
```typescript
// ❌ User as plain interface (no validation)
interface User {
  id: string
  email: string
  role: 'admin' | 'staff' | 'client'
}

// Anyone can create invalid users
const badUser = {
  id: '',
  email: 'not-an-email',
  role: 'superadmin' as any  // Doesn't exist!
}

// No behavior, just data containers
```

### ✅ TARGET (Strong Encapsulation)
```typescript
// ✅ User as encapsulated class
class User {
  private id: string
  private email: Email  // Value Object
  private role: UserRole  // Value Object
  
  private constructor(props: { id: string; email: Email; role: UserRole }) {
    this.id = props.id
    this.email = props.email
    this.role = props.role
  }
  
  static create(props: { email: string; role: string }): User {
    // Validation + construction
    const email = Email.create(props.email)
    const role = UserRole.create(props.role)
    return new User({ id: generateId(), email, role })
  }
  
  // Getters enforce encapsulation
  getId(): string { return this.id }
  getEmail(): Email { return this.email }
  getRole(): UserRole { return this.role }
  
  // Behavior (domain logic)
  canAccessAdminPanel(): boolean {
    return this.role.isAdmin()
  }
}

// Email as Value Object
class Email {
  private value: string
  
  private constructor(value: string) {
    this.validate(value)
    this.value = value.toLowerCase()
  }
  
  static create(value: string): Email {
    return new Email(value)
  }
  
  private validate(value: string): void {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!regex.test(value)) {
      throw new ValidationError(`Invalid email: ${value}`)
    }
  }
  
  getValue(): string { return this.value }
  
  equals(other: Email): boolean {
    return this.value === other.getValue()
  }
}
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create Email Value Object

**File**: `frontend/src/domain/value-objects/Email.ts`

```typescript
/**
 * Email: Value Object for email addresses
 *
 * Characteristics of value objects:
 * - Immutable (value never changes)
 * - Interchangeable (two emails with same value are equal)
 * - No identity (not compared by ID)
 * - Validates on construction (fail fast)
 */

export class Email {
  private readonly value: string

  private constructor(value: string) {
    this.validate(value)
    this.value = value.toLowerCase().trim()
  }

  /**
   * Factory method for creating Email
   * Throws ValidationError if email invalid
   */
  static create(value: string): Email {
    return new Email(value)
  }

  /**
   * Restore from persistence
   */
  static fromString(value: string): Email {
    // Skip validation on restore (already validated)
    const email = Object.create(Email.prototype)
    email.value = value
    return email
  }

  /**
   * Validate email format
   */
  private validate(value: string): void {
    if (!value || value.trim() === '') {
      throw new EmailValidationError('Email cannot be empty')
    }

    // RFC 5322 simplified regex
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!regex.test(value)) {
      throw new EmailValidationError(`Invalid email format: ${value}`)
    }

    // Additional checks
    if (value.length > 254) {
      throw new EmailValidationError('Email is too long (max 254 characters)')
    }
  }

  /**
   * Get email string value
   */
  getValue(): string {
    return this.value
  }

  /**
   * Value object equality (by value, not by reference)
   */
  equals(other: Email): boolean {
    if (!(other instanceof Email)) return false
    return this.value === other.value
  }

  /**
   * Check if email is from specific domain
   */
  isDomain(domain: string): boolean {
    return this.value.endsWith(`@${domain}`)
  }

  /**
   * Get domain from email
   */
  getDomain(): string {
    return this.value.split('@')[1]
  }

  /**
   * Get local part (before @)
   */
  getLocalPart(): string {
    return this.value.split('@')[0]
  }

  /**
   * Serialize for JSON
   */
  toJSON(): string {
    return this.value
  }

  /**
   * String representation
   */
  toString(): string {
    return this.value
  }
}

export class EmailValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'EmailValidationError'
    Object.setPrototypeOf(this, EmailValidationError.prototype)
  }
}
```

### Step 2: Create UserRole Value Object

**File**: `frontend/src/domain/value-objects/UserRole.ts`

```typescript
/**
 * UserRole: Value Object for user roles
 *
 * Ensures type safety and prevents invalid roles.
 */

export type RoleType = 'admin' | 'staff' | 'client'

export class UserRole {
  private readonly value: RoleType

  private constructor(value: RoleType) {
    this.value = value
  }

  /**
   * Factory method
   */
  static create(value: string): UserRole {
    const normalized = value.toLowerCase() as RoleType

    const validRoles: RoleType[] = ['admin', 'staff', 'client']
    if (!validRoles.includes(normalized)) {
      throw new RoleValidationError(
        `Invalid role: ${value}. Must be one of: ${validRoles.join(', ')}`
      )
    }

    return new UserRole(normalized)
  }

  /**
   * Predefined roles
   */
  static admin(): UserRole {
    return new UserRole('admin')
  }

  static staff(): UserRole {
    return new UserRole('staff')
  }

  static client(): UserRole {
    return new UserRole('client')
  }

  /**
   * Get role value
   */
  getValue(): RoleType {
    return this.value
  }

  /**
   * Permission checks
   */
  isAdmin(): boolean {
    return this.value === 'admin'
  }

  isStaff(): boolean {
    return this.value === 'staff'
  }

  isClient(): boolean {
    return this.value === 'client'
  }

  /**
   * Check if role has permission
   */
  hasPermission(permission: string): boolean {
    const permissions: Record<RoleType, Set<string>> = {
      admin: new Set([
        'view_users',
        'edit_users',
        'delete_users',
        'view_reports',
        'manage_staff'
      ]),
      staff: new Set(['view_appointments', 'manage_services']),
      client: new Set(['view_appointments', 'book_appointment'])
    }

    return permissions[this.value].has(permission)
  }

  /**
   * Value object equality
   */
  equals(other: UserRole): boolean {
    if (!(other instanceof UserRole)) return false
    return this.value === other.value
  }

  /**
   * Serialize
   */
  toJSON(): string {
    return this.value
  }

  toString(): string {
    return this.value
  }
}

export class RoleValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'RoleValidationError'
    Object.setPrototypeOf(this, RoleValidationError.prototype)
  }
}
```

### Step 3: Create User Aggregate

**File**: `frontend/src/domain/entities/User.ts`

```typescript
/**
 * User: Domain Entity (Aggregate Root)
 *
 * Domain-driven design aggregate:
 * - Encapsulates user data
 * - Uses value objects (Email, UserRole)
 * - Contains business logic
 * - No getters/setters for fields (only through methods)
 */

import { Email } from '@domain/value-objects/Email'
import { UserRole } from '@domain/value-objects/UserRole'
import { generateId } from '@shared/utils/id-generator'

export interface UserProps {
  id: string
  email: Email
  role: UserRole
  name: string
  emailVerified: boolean
  createdAt: Date
  updatedAt: Date
}

export class User {
  private id: string
  private email: Email
  private role: UserRole
  private name: string
  private emailVerified: boolean
  private createdAt: Date
  private updatedAt: Date

  /**
   * Private constructor enforces factory pattern
   */
  private constructor(props: UserProps) {
    this.id = props.id
    this.email = props.email
    this.role = props.role
    this.name = props.name
    this.emailVerified = props.emailVerified
    this.createdAt = props.createdAt
    this.updatedAt = props.updatedAt
  }

  /**
   * Factory method: Create new user
   */
  static create(input: {
    email: string
    name: string
    role: string
  }): User {
    return new User({
      id: generateId(),
      email: Email.create(input.email),
      role: UserRole.create(input.role),
      name: input.name,
      emailVerified: false,
      createdAt: new Date(),
      updatedAt: new Date()
    })
  }

  /**
   * Factory method: Restore from persistence
   */
  static hydrate(dto: any): User {
    return new User({
      id: dto.id,
      email: Email.create(dto.email),
      role: UserRole.create(dto.role),
      name: dto.name,
      emailVerified: dto.emailVerified,
      createdAt: new Date(dto.createdAt),
      updatedAt: new Date(dto.updatedAt)
    })
  }

  // ========================================================================
  // GETTERS (Encapsulation)
  // ========================================================================

  getId(): string {
    return this.id
  }

  getEmail(): Email {
    return this.email
  }

  getRole(): UserRole {
    return this.role
  }

  getName(): string {
    return this.name
  }

  isEmailVerified(): boolean {
    return this.emailVerified
  }

  getCreatedAt(): Date {
    return this.createdAt
  }

  getUpdatedAt(): Date {
    return this.updatedAt
  }

  // ========================================================================
  // BUSINESS LOGIC (Domain methods)
  // ========================================================================

  /**
   * Change email (business logic)
   */
  changeEmail(newEmail: string): void {
    const email = Email.create(newEmail)

    if (email.equals(this.email)) {
      throw new Error('New email cannot be the same as current email')
    }

    this.email = email
    this.emailVerified = false  // Must verify new email
    this.updatedAt = new Date()
  }

  /**
   * Promote to admin
   */
  promoteToAdmin(): void {
    if (this.role.isAdmin()) {
      throw new Error('User is already an admin')
    }

    this.role = UserRole.admin()
    this.updatedAt = new Date()
  }

  /**
   * Demote from admin
   */
  demoteFromAdmin(): void {
    if (!this.role.isAdmin()) {
      throw new Error('User is not an admin')
    }

    this.role = UserRole.client()
    this.updatedAt = new Date()
  }

  /**
   * Check if user can access admin panel
   */
  canAccessAdminPanel(): boolean {
    return this.role.isAdmin()
  }

  /**
   * Verify email
   */
  verifyEmail(): void {
    this.emailVerified = true
    this.updatedAt = new Date()
  }

  /**
   * Mark email as unverified (when changed)
   */
  unverifyEmail(): void {
    this.emailVerified = false
    this.updatedAt = new Date()
  }

  // ========================================================================
  // VALUE OBJECT METHODS
  // ========================================================================

  /**
   * Entity equality (by ID)
   */
  equals(other: User): boolean {
    if (!(other instanceof User)) return false
    return this.id === other.id
  }

  /**
   * Serialize for API/storage
   */
  toDTO(): {
    id: string
    email: string
    role: string
    name: string
    emailVerified: boolean
    createdAt: string
    updatedAt: string
  } {
    return {
      id: this.id,
      email: this.email.getValue(),
      role: this.role.getValue(),
      name: this.name,
      emailVerified: this.emailVerified,
      createdAt: this.createdAt.toISOString(),
      updatedAt: this.updatedAt.toISOString()
    }
  }
}
```

---

## 🧪 Testing Value Objects

**File**: `frontend/src/__tests__/domain/value-objects/Email.test.ts`

```typescript
import { Email, EmailValidationError } from '@domain/value-objects/Email'

describe('Email - Value Object', () => {
  describe('Creation', () => {
    it('should create valid email', () => {
      const email = Email.create('test@example.com')
      expect(email.getValue()).toBe('test@example.com')
    })

    it('should lowercase email', () => {
      const email = Email.create('Test@EXAMPLE.COM')
      expect(email.getValue()).toBe('test@example.com')
    })

    it('should reject invalid email', () => {
      expect(() => Email.create('invalid')).toThrow(EmailValidationError)
      expect(() => Email.create('test@')).toThrow(EmailValidationError)
      expect(() => Email.create('@example.com')).toThrow(EmailValidationError)
    })

    it('should reject empty email', () => {
      expect(() => Email.create('')).toThrow(EmailValidationError)
    })
  })

  describe('Equality', () => {
    it('should be equal by value', () => {
      const email1 = Email.create('test@example.com')
      const email2 = Email.create('test@example.com')

      expect(email1.equals(email2)).toBe(true)
    })

    it('should not be equal by reference', () => {
      const email1 = Email.create('test@example.com')
      const email2 = Email.create('other@example.com')

      expect(email1.equals(email2)).toBe(false)
    })
  })

  describe('Domain extraction', () => {
    it('should get domain', () => {
      const email = Email.create('user@example.com')
      expect(email.getDomain()).toBe('example.com')
    })

    it('should get local part', () => {
      const email = Email.create('user@example.com')
      expect(email.getLocalPart()).toBe('user')
    })
  })
})
```

---

## ✅ Checklist

- [ ] Create Email value object
- [ ] Create UserRole value object
- [ ] Create Money value object
- [ ] Create Duration value object
- [ ] Refactor User entity to use value objects
- [ ] Refactor Staff entity to use value objects
- [ ] Refactor Service entity to use value objects
- [ ] Refactor Appointment entity to use value objects
- [ ] Create comprehensive value object tests
- [ ] Update DTOs to work with value objects

---

## 🎯 Success Criteria

✅ All entities use value objects  
✅ No direct field access (only through getters/methods)  
✅ Value objects enforce validation  
✅ Immutability enforced (readonly fields)  
✅ 100% of domain logic testable  
✅ Invalid states impossible to create  



## Reference: 04-IMPROVEMENT_REPOSITORIES.md

# 🏛️ IMPROVEMENT 4: REPOSITORY PATTERN HIERARCHY

## 🎯 Goal
Create abstract `BaseRepository` class to enforce Liskov Substitution Principle and guarantee contract compliance.

**POO Gain**: +6%  
**Effort**: 2-3 days  
**Priority**: 🔴 CRITICAL (depends on: Improvement 1)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak Polymorphism)
```typescript
// ❌ Inconsistent implementations
class HttpUserRepository implements IUserRepository {
  async getUsers() { return httpClient.get(...) }
  // Different error handling
  // Different caching
  // Not testable
}

// Can't easily swap for testing
```

### ✅ TARGET (Strong Polymorphism)
```typescript
// ✅ Abstract repository enforces contract
abstract class BaseRepository<T extends Entity> {
  protected abstract mapToDomain(dto: any): T
  protected abstract mapToPersistence(entity: T): any
  
  async findAll(): Promise<T[]> {
    // Consistent error handling
    // Consistent logging
    // Guaranteed contract
  }
}

// HTTP implementation
class HttpUserRepository extends BaseRepository<User> {
  constructor(private httpClient: HttpClient) { super() }
}

// Memory implementation (for testing)
class InMemoryUserRepository extends BaseRepository<User> {
  private storage = new Map<string, User>()
}

// Both are substitutable (Liskov principle)
const userService1 = new UserService(new HttpUserRepository(client))
const userService2 = new UserService(new InMemoryUserRepository())
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create BaseRepository

**File**: `frontend/src/core/repositories/BaseRepository.ts`

```typescript
/**
 * BaseRepository: Abstract base for all repositories
 *
 * Enforces:
 * - Consistent error handling
 * - Mapper pattern (DTO ↔ Domain)
 * - Type safety
 * - Liskov Substitution Principle (LSP)
 *
 * Subclasses must implement:
 * - mapToDomain: DTO → Entity
 * - mapToPersistence: Entity → DTO
 * - Abstract query methods
 */

export interface IRepository<T> {
  findAll(): Promise<T[]>
  findById(id: string): Promise<T | null>
  create(entity: T): Promise<void>
  update(entity: T): Promise<void>
  delete(id: string): Promise<void>
  findBy(criteria: any): Promise<T[]>
}

export abstract class BaseRepository<T> implements IRepository<T> {
  /**
   * Subclasses must provide mappers
   */
  protected abstract mapToDomain(dto: any): T
  protected abstract mapToPersistence(entity: T): any

  /**
   * Abstract query methods (subclass implements actual queries)
   */
  protected abstract performQuery(query: string, params?: any[]): Promise<any[]>
  protected abstract performQueryOne(
    query: string,
    params?: any[]
  ): Promise<any | null>
  protected abstract performMutation(query: string, params?: any[]): Promise<void>

  /**
   * Find all entities
   *
   * Subclasses override performQuery() for actual implementation
   */
  async findAll(): Promise<T[]> {
    try {
      const dtos = await this.performQuery('SELECT *')
      const entities = dtos.map(dto => this.mapToDomain(dto))
      this.logOperation('findAll', `Retrieved ${entities.length} entities`)
      return entities
    } catch (error) {
      this.logError('findAll', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Find single entity by ID
   */
  async findById(id: string): Promise<T | null> {
    try {
      this.validateId(id)
      const dto = await this.performQueryOne(
        'SELECT * WHERE id = ?',
        [id]
      )
      if (!dto) return null

      const entity = this.mapToDomain(dto)
      this.logOperation('findById', `Retrieved entity: ${id}`)
      return entity
    } catch (error) {
      this.logError('findById', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Create new entity
   */
  async create(entity: T): Promise<void> {
    try {
      const dto = this.mapToPersistence(entity)
      await this.performMutation('INSERT', [dto])
      this.logOperation('create', 'Entity created')
    } catch (error) {
      this.logError('create', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Update existing entity
   */
  async update(entity: T): Promise<void> {
    try {
      const dto = this.mapToPersistence(entity)
      await this.performMutation('UPDATE', [dto])
      this.logOperation('update', 'Entity updated')
    } catch (error) {
      this.logError('update', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Delete entity
   */
  async delete(id: string): Promise<void> {
    try {
      this.validateId(id)
      await this.performMutation('DELETE', [id])
      this.logOperation('delete', `Entity deleted: ${id}`)
    } catch (error) {
      this.logError('delete', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Find by criteria (dynamic queries)
   */
  async findBy(criteria: Record<string, any>): Promise<T[]> {
    try {
      const dtos = await this.performQuery('SELECT * WHERE ...', [criteria])
      const entities = dtos.map(dto => this.mapToDomain(dto))
      this.logOperation('findBy', `Retrieved ${entities.length} entities`)
      return entities
    } catch (error) {
      this.logError('findBy', error)
      throw this.wrapRepositoryError(error)
    }
  }

  // ========================================================================
  // PROTECTED HELPERS
  // ========================================================================

  protected validateId(id: string): void {
    if (!id || id.trim() === '') {
      throw new RepositoryError('ID cannot be empty')
    }
  }

  protected wrapRepositoryError(error: any): RepositoryError {
    if (error instanceof RepositoryError) {
      return error
    }

    if (error instanceof Error) {
      return new RepositoryError(
        `Database error: ${error.message}`,
        error
      )
    }

    return new RepositoryError('Unknown database error')
  }

  protected logOperation(method: string, message: string): void {
    console.log(`✅ [${this.constructor.name}] ${method}: ${message}`)
  }

  protected logError(method: string, error: any): void {
    console.error(`❌ [${this.constructor.name}] ${method}:`, error)
  }
}

export class RepositoryError extends Error {
  readonly isRepositoryError = true

  constructor(message: string, public cause?: any) {
    super(message)
    this.name = 'RepositoryError'
    Object.setPrototypeOf(this, RepositoryError.prototype)
  }
}
```

### Step 2: HTTP Repository Implementation

**File**: `frontend/src/infrastructure/repositories/http-user-repository.ts`

```typescript
/**
 * HttpUserRepository: HTTP implementation of User repository
 *
 * Extends BaseRepository to inherit consistent behavior.
 * Only implements storage-specific logic (HTTP calls).
 */

import { BaseRepository } from '@core/repositories/BaseRepository'
import { User } from '@domain/entities/User'
import { IUserRepository } from '@domain/repositories/IUserRepository'
import { HttpClient } from '@infrastructure/http/client'

export class HttpUserRepository
  extends BaseRepository<User>
  implements IUserRepository
{
  private endpoint = '/api/users'

  constructor(private httpClient: HttpClient) {
    super()
  }

  /**
   * Convert API response to domain entity
   */
  protected mapToDomain(dto: any): User {
    return User.hydrate({
      id: dto.id,
      email: dto.email,
      role: dto.role,
      name: dto.name,
      emailVerified: dto.email_verified,
      createdAt: dto.created_at,
      updatedAt: dto.updated_at
    })
  }

  /**
   * Convert domain entity to API request body
   */
  protected mapToPersistence(entity: User): any {
    const dto = entity.toDTO()
    return {
      id: dto.id,
      email: dto.email,
      role: dto.role,
      name: dto.name,
      email_verified: dto.emailVerified,
      created_at: dto.createdAt,
      updated_at: dto.updatedAt
    }
  }

  /**
   * HTTP GET (SELECT)
   */
  protected async performQuery(query: string, params?: any[]): Promise<any[]> {
    try {
      const response = await this.httpClient.get(this.endpoint)
      return response.data
    } catch (error) {
      throw this.handleHttpError(error)
    }
  }

  /**
   * HTTP GET by ID (SELECT WHERE ID = ?)
   */
  protected async performQueryOne(
    query: string,
    params?: any[]
  ): Promise<any | null> {
    try {
      const [id] = params || []
      const response = await this.httpClient.get(`${this.endpoint}/${id}`)
      return response.data
    } catch (error) {
      if (error.response?.status === 404) return null
      throw this.handleHttpError(error)
    }
  }

  /**
   * HTTP POST/PUT/DELETE (INSERT/UPDATE/DELETE)
   */
  protected async performMutation(query: string, params?: any[]): Promise<void> {
    try {
      const [data] = params || []

      if (query === 'INSERT') {
        await this.httpClient.post(this.endpoint, data)
      } else if (query === 'UPDATE') {
        await this.httpClient.put(`${this.endpoint}/${data.id}`, data)
      } else if (query === 'DELETE') {
        const [id] = params || []
        await this.httpClient.delete(`${this.endpoint}/${id}`)
      }
    } catch (error) {
      throw this.handleHttpError(error)
    }
  }

  /**
   * HTTP-specific error handling
   */
  private handleHttpError(error: any): Error {
    if (error.response?.status === 400) {
      return new ValidationError(error.response.data?.message || 'Validation failed')
    }

    if (error.response?.status === 404) {
      return new NotFoundError('Resource not found')
    }

    if (error.response?.status === 409) {
      return new ConflictError(error.response.data?.message || 'Conflict')
    }

    return new RepositoryError(error.message, error)
  }
}

class ValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ValidationError'
  }
}

class NotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NotFoundError'
  }
}

class ConflictError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ConflictError'
  }
}
```

### Step 3: In-Memory Repository (for Testing)

**File**: `frontend/src/infrastructure/repositories/in-memory-user-repository.ts`

```typescript
/**
 * InMemoryUserRepository: In-memory implementation for testing
 *
 * Key benefit: Can swap HttpUserRepository with InMemoryUserRepository
 * in tests without changing service code (Liskov Substitution Principle).
 */

import { BaseRepository } from '@core/repositories/BaseRepository'
import { User } from '@domain/entities/User'

export class InMemoryUserRepository extends BaseRepository<User> {
  private storage: Map<string, User> = new Map()

  /**
   * Mappers (no-op for in-memory)
   */
  protected mapToDomain(dto: any): User {
    return dto
  }

  protected mapToPersistence(entity: User): any {
    return entity
  }

  /**
   * In-memory query implementations
   */
  protected async performQuery(query: string, params?: any[]): Promise<any[]> {
    return Array.from(this.storage.values())
  }

  protected async performQueryOne(
    query: string,
    params?: any[]
  ): Promise<any | null> {
    const [id] = params || []
    return this.storage.get(id) || null
  }

  protected async performMutation(query: string, params?: any[]): Promise<void> {
    const [data] = params || []

    if (query === 'INSERT') {
      this.storage.set(data.id, data)
    } else if (query === 'UPDATE') {
      if (!this.storage.has(data.id)) throw new Error('Not found')
      this.storage.set(data.id, data)
    } else if (query === 'DELETE') {
      const [id] = params || []
      this.storage.delete(id)
    }
  }

  /**
   * Helper for testing
   */
  clear(): void {
    this.storage.clear()
  }

  seed(users: User[]): void {
    users.forEach(user => {
      this.storage.set(user.getId(), user)
    })
  }
}
```

### Step 4: Testing Repository Pattern

**File**: `frontend/src/__tests__/infrastructure/repositories/repository.test.ts`

```typescript
import { User } from '@domain/entities/User'
import { HttpUserRepository } from '@infrastructure/repositories/http-user-repository'
import { InMemoryUserRepository } from '@infrastructure/repositories/in-memory-user-repository'

/**
 * Abstract repository tests that work for ANY implementation
 *
 * This demonstrates Liskov Substitution Principle:
 * Same tests pass for both HTTP and In-Memory implementations.
 */
class RepositoryTestSuite {
  protected repository: any

  async testFindAll() {
    // Create test users
    const user1 = User.create({ email: 'user1@test.com', name: 'User 1', role: 'client' })
    const user2 = User.create({ email: 'user2@test.com', name: 'User 2', role: 'staff' })

    await this.repository.create(user1)
    await this.repository.create(user2)

    // Test findAll
    const users = await this.repository.findAll()
    expect(users).toHaveLength(2)
  }

  async testFindById() {
    const user = User.create({ email: 'test@test.com', name: 'Test', role: 'client' })
    await this.repository.create(user)

    const found = await this.repository.findById(user.getId())
    expect(found).toBeDefined()
    expect(found?.getId()).toBe(user.getId())
  }

  async testCreate() {
    const user = User.create({ email: 'new@test.com', name: 'New User', role: 'client' })
    await this.repository.create(user)

    const found = await this.repository.findById(user.getId())
    expect(found).toBeDefined()
  }

  async testUpdate() {
    const user = User.create({ email: 'test@test.com', name: 'Test', role: 'client' })
    await this.repository.create(user)

    user.promoteToAdmin()
    await this.repository.update(user)

    const found = await this.repository.findById(user.getId())
    expect(found?.getRole().isAdmin()).toBe(true)
  }

  async testDelete() {
    const user = User.create({ email: 'test@test.com', name: 'Test', role: 'client' })
    await this.repository.create(user)

    await this.repository.delete(user.getId())

    const found = await this.repository.findById(user.getId())
    expect(found).toBeNull()
  }
}

// Test In-Memory implementation
describe('InMemoryUserRepository', () => {
  const suite = new RepositoryTestSuite()

  beforeEach(() => {
    suite.repository = new InMemoryUserRepository()
  })

  it('should findAll', async () => suite.testFindAll())
  it('should findById', async () => suite.testFindById())
  it('should create', async () => suite.testCreate())
  it('should update', async () => suite.testUpdate())
  it('should delete', async () => suite.testDelete())
})

// Same tests for HTTP implementation
describe('HttpUserRepository', () => {
  const suite = new RepositoryTestSuite()
  const mockHttpClient = { /* mock */ }

  beforeEach(() => {
    suite.repository = new HttpUserRepository(mockHttpClient)
  })

  it('should findAll', async () => suite.testFindAll())
  it('should findById', async () => suite.testFindById())
  it('should create', async () => suite.testCreate())
  it('should update', async () => suite.testUpdate())
  it('should delete', async () => suite.testDelete())
})
```

---

## ✅ Checklist

- [ ] Create `BaseRepository.ts`
- [ ] Refactor `HttpUserRepository` to extend `BaseRepository`
- [ ] Refactor other HTTP repositories
- [ ] Create `InMemoryUserRepository` for testing
- [ ] Create shared repository tests
- [ ] Verify all repositories pass tests
- [ ] Test service substitution in tests

---

## 🎯 Success Criteria

✅ All repositories extend `BaseRepository`  
✅ Same tests pass for HTTP and In-Memory  
✅ Services use repositories through interfaces  
✅ Easy to swap for testing  
✅ Error handling consistent  
✅ Liskov Substitution Principle verified  



## Reference: 05-IMPROVEMENT_HOOK_FACTORIES.md

# 🎣 IMPROVEMENT 5: HOOK FACTORIES & STRATEGY PATTERN

## 🎯 Goal
Create sophisticated hook factories that leverage DI Container and support Strategy pattern for different implementations.

**POO Gain**: +4%  
**Effort**: 2-3 days  
**Priority**: 🟡 HIGH (depends on: Improvements 1-2)

---

## 🏗️ IMPLEMENTATION

### Step 1: Basic Service Hook

**File**: `frontend/src/presentation/hooks/useService.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Generic hook to access any service from DI container
 */
export function useService<T = any>(key: string): T {
  const container = ServiceContainer.getInstance()
  return container.get<T>(key)
}
```

### Step 2: Query Hooks with DI

**File**: `frontend/src/presentation/hooks/use-users.ts`

```typescript
import { useQuery, useMutation } from '@tanstack/react-query'
import { ServiceContainer } from '@core/di/ServiceContainer'
import { UserService } from '@application/services/user-service'
import { CreateUserInput } from '@application/dtos/user-dtos'

/**
 * Hook: Fetch all users
 * Pattern: Query with DI
 */
export function useUsers() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getAll(),
    staleTime: 5 * 60 * 1000,
    retry: 2
  })
}

/**
 * Hook: Fetch single user
 * Pattern: Query with parameters
 */
export function useUser(userId: string) {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return useQuery({
    queryKey: ['users', userId],
    queryFn: () => userService.getById(userId),
    enabled: !!userId
  })
}

/**
 * Hook: Create user
 * Pattern: Mutation with cache invalidation
 */
export function useCreateUser() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  const queryClient = container.get<QueryClient>('queryClient')

  return useMutation({
    mutationFn: (input: CreateUserInput) => userService.create(input),
    onSuccess: () => {
      // Invalidate cache to refetch
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error) => {
      console.error('Error creating user:', error)
    }
  })
}

/**
 * Hook: Update user
 * Pattern: Mutation with optimistic update
 */
export function useUpdateUser() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  const queryClient = container.get<QueryClient>('queryClient')

  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: any }) =>
      userService.update(id, input),
    onMutate: async ({ id, input }) => {
      // Cancel outgoing queries
      await queryClient.cancelQueries({ queryKey: ['users', id] })

      // Optimistic update
      const previous = queryClient.getQueryData(['users', id])
      queryClient.setQueryData(['users', id], { ...previous, ...input })

      return { previous }
    },
    onError: (error, variables, context) => {
      // Revert on error
      if (context?.previous) {
        queryClient.setQueryData(['users', variables.id], context.previous)
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}

/**
 * Hook: Delete user
 */
export function useDeleteUser() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  const queryClient = container.get<QueryClient>('queryClient')

  return useMutation({
    mutationFn: (userId: string) => userService.delete(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}
```

### Step 3: Strategy Pattern Hooks

**File**: `frontend/src/presentation/hooks/use-auth-flow.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Authentication strategies (Strategy pattern)
 */
export interface IAuthStrategy {
  login(email: string, password: string): Promise<any>
  logout(): Promise<void>
  register(email: string, password: string): Promise<any>
  refreshToken(): Promise<string>
}

/**
 * Hook with strategy selection
 * Pattern: Strategy Pattern + DI Container
 */
export function useAuthFlow(strategy: 'local' | 'oauth' = 'local'): IAuthStrategy {
  const container = ServiceContainer.getInstance()

  const strategies: Record<string, string> = {
    local: 'localAuthStrategy',
    oauth: 'oauthStrategy'
  }

  const strategyKey = strategies[strategy]
  if (!strategyKey) {
    throw new Error(`Unknown auth strategy: ${strategy}`)
  }

  return container.get<IAuthStrategy>(strategyKey)
}

/**
 * Local auth implementation
 */
export class LocalAuthStrategy implements IAuthStrategy {
  constructor(private authService: any) {}

  async login(email: string, password: string): Promise<any> {
    const result = await this.authService.login(email, password)
    localStorage.setItem('token', result.token)
    return result
  }

  async logout(): Promise<void> {
    localStorage.removeItem('token')
    await this.authService.logout()
  }

  async register(email: string, password: string): Promise<any> {
    return this.authService.register(email, password)
  }

  async refreshToken(): Promise<string> {
    const token = await this.authService.refreshToken()
    localStorage.setItem('token', token)
    return token
  }
}

/**
 * OAuth implementation (can be swapped at runtime)
 */
export class OAuthStrategy implements IAuthStrategy {
  constructor(private oauthService: any) {}

  async login(email: string, password: string): Promise<any> {
    return this.oauthService.startFlow()
  }

  async logout(): Promise<void> {
    return this.oauthService.logout()
  }

  async register(email: string, password: string): Promise<any> {
    throw new Error('OAuth does not support direct registration')
  }

  async refreshToken(): Promise<string> {
    return this.oauthService.refreshToken()
  }
}
```

### Step 4: Batch Operations Hooks

**File**: `frontend/src/presentation/hooks/use-batch-users.ts`

```typescript
import { useQueries } from '@tanstack/react-query'
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Hook: Batch fetch multiple users (optimization)
 * Pattern: Parallel queries via useQueries
 */
export function useBatchUsers(userIds: string[]) {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return useQueries({
    queries: userIds.map(id => ({
      queryKey: ['users', id],
      queryFn: () => userService.getById(id),
      staleTime: 5 * 60 * 1000
    }))
  })
}

/**
 * Hook: Batch operations (concurrent mutations)
 */
export function useBatchCreateUsers() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return async (inputs: CreateUserInput[]) => {
    return Promise.all(
      inputs.map(input => userService.create(input))
    )
  }
}
```

### Step 5: Composable Hooks

**File**: `frontend/src/presentation/hooks/use-paginated-users.ts`

```typescript
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Hook: Paginated data fetching (composition)
 * Pattern: Hooks composition + DI
 */
export function usePaginatedUsers(pageSize: number = 10) {
  const [page, setPage] = useState(1)
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  const { data, isLoading, error } = useQuery({
    queryKey: ['users', 'paginated', page],
    queryFn: async () => {
      const allUsers = await userService.getAll()
      const start = (page - 1) * pageSize
      const end = start + pageSize
      return {
        items: allUsers.slice(start, end),
        total: allUsers.length,
        page,
        pageSize,
        totalPages: Math.ceil(allUsers.length / pageSize)
      }
    }
  })

  return {
    data: data?.items || [],
    pagination: {
      page,
      pageSize,
      total: data?.total || 0,
      totalPages: data?.totalPages || 0
    },
    isLoading,
    error,
    goToPage: (p: number) => setPage(p),
    nextPage: () => setPage(p => p + 1),
    prevPage: () => setPage(p => Math.max(1, p - 1))
  }
}
```

### Step 6: Testing Hooks with DI

**File**: `frontend/src/__tests__/presentation/hooks/use-users.test.ts`

```typescript
import { renderHook, waitFor } from '@testing-library/react'
import { useUsers } from '@presentation/hooks/use-users'
import { ServiceContainer } from '@core/di/ServiceContainer'
import { InMemoryUserRepository } from '@infrastructure/repositories/in-memory-user-repository'
import { User } from '@domain/entities/User'

describe('useUsers Hook - DI Integration', () => {
  beforeEach(() => {
    // Reset DI container
    ServiceContainer.reset()

    // Register test implementations
    const container = ServiceContainer.getInstance()
    const repository = new InMemoryUserRepository()

    // Seed test data
    const user1 = User.create({ email: 'test1@example.com', name: 'Test 1', role: 'client' })
    const user2 = User.create({ email: 'test2@example.com', name: 'Test 2', role: 'staff' })
    repository.seed([user1, user2])

    container.register('userRepository', () => repository, { singleton: true })
    container.register('userService', () => {
      return new UserService(container.get('userRepository'))
    }, { singleton: true })

    container.initialize()
  })

  it('should fetch users from DI service', async () => {
    const { result } = renderHook(() => useUsers())

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(result.current.data).toHaveLength(2)
    expect(result.current.data[0].getName()).toBe('Test 1')
  })

  it('should use same service instance', async () => {
    const container = ServiceContainer.getInstance()
    const service1 = container.get('userService')
    const service2 = container.get('userService')

    expect(service1).toBe(service2)  // Same singleton
  })
})
```

---

## ✅ Checklist

- [ ] Create generic `useService` hook
- [ ] Create domain-specific hooks for each service
- [ ] Implement Strategy pattern hooks
- [ ] Create batch operation hooks
- [ ] Create composable hooks (pagination, etc.)
- [ ] Create comprehensive hook tests
- [ ] Verify hooks work with DI container
- [ ] Update components to use new hooks

---

## 🎯 Success Criteria

✅ All hooks use DI container  
✅ Strategy pattern hooks switchable at runtime  
✅ No service instantiation in components  
✅ Hooks fully testable with in-memory repositories  
✅ Error handling consistent  
✅ React Query best practices followed  



## Reference: 06-IMPROVEMENT_ERROR_HANDLING.md

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



## Reference: 07-IMPROVEMENT_EVENT_BUS.md

# 📢 IMPROVEMENT 7: EVENT-DRIVEN ARCHITECTURE

## 🎯 Goal
Implement Observer pattern with Event Bus to decouple services and enable reactive flows.

**POO Gain**: +4%  
**Effort**: 2-3 days  
**Priority**: 🟡 MEDIUM (depends on: Improvements 1-2)

---

## 🏗️ IMPLEMENTATION

### Step 1: Domain Events

**File**: `frontend/src/domain/events/DomainEvent.ts`

```typescript
/**
 * DomainEvent: Base class for all domain events
 *
 * Characteristics:
 * - Immutable data
 * - Timestamped
 * - Identifies what happened
 * - Contains only necessary data
 */

export abstract class DomainEvent {
  readonly occurredAt: Date
  abstract readonly eventName: string

  constructor() {
    this.occurredAt = new Date()
  }

  /**
   * Get event type for routing
   */
  getEventName(): string {
    return this.eventName
  }

  /**
   * Serialize for storage/transmission
   */
  abstract toJSON(): Record<string, any>
}

// ============================================================================
// USER DOMAIN EVENTS
// ============================================================================

export class UserCreatedEvent extends DomainEvent {
  readonly eventName = 'user.created'

  constructor(
    public readonly userId: string,
    public readonly email: string,
    public readonly name: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      userId: this.userId,
      email: this.email,
      name: this.name,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

export class UserDeletedEvent extends DomainEvent {
  readonly eventName = 'user.deleted'

  constructor(public readonly userId: string) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      userId: this.userId,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

export class UserEmailChangedEvent extends DomainEvent {
  readonly eventName = 'user.email.changed'

  constructor(
    public readonly userId: string,
    public readonly oldEmail: string,
    public readonly newEmail: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      userId: this.userId,
      oldEmail: this.oldEmail,
      newEmail: this.newEmail,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

// ============================================================================
// APPOINTMENT DOMAIN EVENTS
// ============================================================================

export class AppointmentCreatedEvent extends DomainEvent {
  readonly eventName = 'appointment.created'

  constructor(
    public readonly appointmentId: string,
    public readonly userId: string,
    public readonly staffId: string,
    public readonly scheduledAt: Date
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      appointmentId: this.appointmentId,
      userId: this.userId,
      staffId: this.staffId,
      scheduledAt: this.scheduledAt.toISOString(),
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

export class AppointmentCancelledEvent extends DomainEvent {
  readonly eventName = 'appointment.cancelled'

  constructor(
    public readonly appointmentId: string,
    public readonly reason?: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      appointmentId: this.appointmentId,
      reason: this.reason,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

// ============================================================================
// BOOKING DOMAIN EVENTS
// ============================================================================

export class BookingCompletedEvent extends DomainEvent {
  readonly eventName = 'booking.completed'

  constructor(
    public readonly bookingId: string,
    public readonly amount: number,
    public readonly currency: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      bookingId: this.bookingId,
      amount: this.amount,
      currency: this.currency,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}
```

### Step 2: Event Handlers (Observer Pattern)

**File**: `frontend/src/domain/events/EventHandler.ts`

```typescript
/**
 * EventHandler: Observer Pattern Implementation
 *
 * Each event can have multiple handlers.
 * Handlers don't know about each other (loose coupling).
 */

import { DomainEvent } from './DomainEvent'

export interface EventHandler<T extends DomainEvent = DomainEvent> {
  handle(event: T): Promise<void>
}

// ============================================================================
// USER EVENT HANDLERS
// ============================================================================

/**
 * Send welcome email when user is created
 */
export class SendWelcomeEmailHandler implements EventHandler<UserCreatedEvent> {
  constructor(private emailService: any) {}

  async handle(event: UserCreatedEvent): Promise<void> {
    console.log(`📧 Sending welcome email to ${event.email}`)
    // await this.emailService.sendWelcomeEmail(event.email, event.name)
  }
}

/**
 * Notify admins when user is created
 */
export class NotifyAdminsHandler implements EventHandler<UserCreatedEvent> {
  constructor(private notificationService: any) {}

  async handle(event: UserCreatedEvent): Promise<void> {
    console.log(`🔔 Notifying admins about new user: ${event.name}`)
    // await this.notificationService.notifyAdmins(...)
  }
}

/**
 * Update user index when email changes
 */
export class UpdateUserIndexHandler implements EventHandler<UserEmailChangedEvent> {
  constructor(private searchService: any) {}

  async handle(event: UserEmailChangedEvent): Promise<void> {
    console.log(`🔍 Updating search index for user ${event.userId}`)
    // await this.searchService.updateUser(event.userId, { email: event.newEmail })
  }
}

// ============================================================================
// APPOINTMENT EVENT HANDLERS
// ============================================================================

/**
 * Send appointment confirmation email
 */
export class SendAppointmentConfirmationHandler
  implements EventHandler<AppointmentCreatedEvent>
{
  constructor(private emailService: any) {}

  async handle(event: AppointmentCreatedEvent): Promise<void> {
    console.log(`📧 Sending appointment confirmation for ${event.appointmentId}`)
    // await this.emailService.sendAppointmentConfirmation(...)
  }
}

/**
 * Add to calendar when appointment created
 */
export class AddToCalendarHandler implements EventHandler<AppointmentCreatedEvent> {
  constructor(private calendarService: any) {}

  async handle(event: AppointmentCreatedEvent): Promise<void> {
    console.log(`📅 Adding appointment ${event.appointmentId} to calendar`)
    // await this.calendarService.addEvent(...)
  }
}

/**
 * Send cancellation notification
 */
export class SendCancellationNotificationHandler
  implements EventHandler<AppointmentCancelledEvent>
{
  constructor(private notificationService: any) {}

  async handle(event: AppointmentCancelledEvent): Promise<void> {
    console.log(
      `🚫 Sending cancellation notice for appointment ${event.appointmentId}`
    )
    // await this.notificationService.notifyAppointmentCancelled(...)
  }
}

// ============================================================================
// BOOKING EVENT HANDLERS
// ============================================================================

/**
 * Send receipt when booking completed
 */
export class SendReceiptHandler implements EventHandler<BookingCompletedEvent> {
  constructor(private emailService: any) {}

  async handle(event: BookingCompletedEvent): Promise<void> {
    console.log(`🧾 Sending receipt for booking ${event.bookingId}`)
    // await this.emailService.sendReceipt(...)
  }
}

/**
 * Update analytics when booking completed
 */
export class UpdateAnalyticsHandler implements EventHandler<BookingCompletedEvent> {
  constructor(private analyticsService: any) {}

  async handle(event: BookingCompletedEvent): Promise<void> {
    console.log(`📊 Recording booking amount: ${event.amount} ${event.currency}`)
    // await this.analyticsService.recordBooking(event.amount)
  }
}
```

### Step 3: Event Bus (Coordinator)

**File**: `frontend/src/core/events/EventBus.ts`

```typescript
/**
 * EventBus: Central event coordinator
 *
 * Implements Observer pattern:
 * - Services publish events
 * - Multiple handlers subscribe to events
 * - Loose coupling between components
 */

import { DomainEvent } from '@domain/events/DomainEvent'
import { EventHandler } from '@domain/events/EventHandler'

export class EventBus {
  private static instance: EventBus
  private handlers: Map<string, EventHandler<any>[]> = new Map()
  private eventHistory: DomainEvent[] = []

  private constructor() {}

  static getInstance(): EventBus {
    if (!EventBus.instance) {
      EventBus.instance = new EventBus()
    }
    return EventBus.instance
  }

  /**
   * Subscribe handler to event
   *
   * @param eventName - Event identifier
   * @param handler - Handler to execute on event
   *
   * Example:
   * eventBus.subscribe('user.created', new SendWelcomeEmailHandler(emailService))
   */
  subscribe<T extends DomainEvent>(
    eventName: string,
    handler: EventHandler<T>
  ): void {
    if (!this.handlers.has(eventName)) {
      this.handlers.set(eventName, [])
    }

    this.handlers.get(eventName)!.push(handler)
    console.log(
      `✅ Subscribed ${handler.constructor.name} to ${eventName}`
    )
  }

  /**
   * Subscribe multiple handlers
   */
  subscribeMultiple<T extends DomainEvent>(
    eventName: string,
    ...handlers: EventHandler<T>[]
  ): void {
    handlers.forEach(h => this.subscribe(eventName, h))
  }

  /**
   * Publish event to all subscribers
   *
   * @param event - Domain event to publish
   * @throws If any handler throws
   *
   * Example:
   * await eventBus.publish(new UserCreatedEvent(userId, email, name))
   */
  async publish<T extends DomainEvent>(event: T): Promise<void> {
    const eventName = event.getEventName()
    const handlers = this.handlers.get(eventName) || []

    console.log(
      `📢 Publishing event: ${eventName} (${handlers.length} subscribers)`
    )

    // Store event in history
    this.eventHistory.push(event)

    // Execute all handlers sequentially
    for (const handler of handlers) {
      try {
        await handler.handle(event)
      } catch (error) {
        console.error(
          `❌ Error in ${handler.constructor.name}: ${error}`
        )
        // Continue with other handlers (don't break on error)
      }
    }
  }

  /**
   * Publish event asynchronously (fire and forget)
   * Handlers execute in background, errors don't propagate
   */
  publishAsync<T extends DomainEvent>(event: T): void {
    setImmediate(() => {
      this.publish(event).catch(error => {
        console.error('Async event error:', error)
      })
    })
  }

  /**
   * Get event history (for debugging)
   */
  getEventHistory(): DomainEvent[] {
    return [...this.eventHistory]
  }

  /**
   * Clear subscriptions and history (for testing)
   */
  reset(): void {
    this.handlers.clear()
    this.eventHistory = []
  }

  /**
   * Get subscriber count for event (for debugging)
   */
  getSubscriberCount(eventName: string): number {
    return this.handlers.get(eventName)?.length || 0
  }
}
```

### Step 4: Integration in DI Container

**File**: `frontend/src/core/di/dependencies.ts` (Update)

```typescript
import { EventBus } from '@core/events/EventBus'
import {
  SendWelcomeEmailHandler,
  NotifyAdminsHandler,
  UpdateUserIndexHandler,
  SendAppointmentConfirmationHandler
} from '@domain/events/EventHandler'

export function registerDependencies(): void {
  const container = ServiceContainer.getInstance()

  // ... existing registrations ...

  // ========================================================================
  // EVENT BUS & HANDLERS
  // ========================================================================

  // Create singleton event bus
  const eventBus = EventBus.getInstance()

  // Register event handlers
  eventBus.subscribeMultiple(
    'user.created',
    new SendWelcomeEmailHandler(container.get('emailService')),
    new NotifyAdminsHandler(container.get('notificationService'))
  )

  eventBus.subscribe(
    'user.email.changed',
    new UpdateUserIndexHandler(container.get('searchService'))
  )

  eventBus.subscribeMultiple(
    'appointment.created',
    new SendAppointmentConfirmationHandler(container.get('emailService')),
    new AddToCalendarHandler(container.get('calendarService'))
  )

  container.register('eventBus', () => eventBus, { singleton: true })
}
```

### Step 5: Services Publish Events

**File**: `frontend/src/application/services/user-service.ts` (Update)

```typescript
import { UserCreatedEvent } from '@domain/events/DomainEvent'
import { EventBus } from '@core/events/EventBus'

class UserService extends BaseService<User, CreateUserInput, UpdateUserInput> {
  constructor(
    protected repository: IUserRepository,
    private eventBus: EventBus
  ) {
    super()
  }

  async create(input: CreateUserInput): Promise<User> {
    // Step 1: Create entity
    const user = User.create(input)

    // Step 2: Validate
    await this.validateEntity(user)

    // Step 3: Persist
    await this.repository.create(user)

    // Step 4: Publish event (decouple from consequences)
    await this.eventBus.publish(
      new UserCreatedEvent(
        user.getId(),
        user.getEmail().getValue(),
        user.getName()
      )
    )

    return user
  }

  async changeEmail(userId: string, newEmail: string): Promise<User> {
    const user = await this.repository.findById(userId)
    if (!user) throw new NotFoundError('User not found')

    const oldEmail = user.getEmail().getValue()
    user.changeEmail(newEmail)

    await this.repository.update(user)

    // Publish event
    await this.eventBus.publish(
      new UserEmailChangedEvent(userId, oldEmail, newEmail)
    )

    return user
  }
}

export { UserService }
```

### Step 6: Testing Event Bus

**File**: `frontend/src/__tests__/core/events/EventBus.test.ts`

```typescript
import { EventBus } from '@core/events/EventBus'
import { UserCreatedEvent } from '@domain/events/DomainEvent'
import { EventHandler } from '@domain/events/EventHandler'

describe('EventBus - Observer Pattern', () => {
  let eventBus: EventBus

  beforeEach(() => {
    EventBus.getInstance().reset()
    eventBus = EventBus.getInstance()
  })

  it('should subscribe and publish to handlers', async () => {
    const mockHandler: EventHandler = {
      handle: jest.fn()
    }

    eventBus.subscribe('user.created', mockHandler)

    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')
    await eventBus.publish(event)

    expect(mockHandler.handle).toHaveBeenCalledWith(event)
  })

  it('should execute multiple handlers', async () => {
    const handler1: EventHandler = { handle: jest.fn() }
    const handler2: EventHandler = { handle: jest.fn() }

    eventBus.subscribe('user.created', handler1)
    eventBus.subscribe('user.created', handler2)

    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')
    await eventBus.publish(event)

    expect(handler1.handle).toHaveBeenCalled()
    expect(handler2.handle).toHaveBeenCalled()
  })

  it('should not break if handler errors', async () => {
    const errorHandler: EventHandler = {
      handle: jest.fn().mockRejectedValue(new Error('Handler error'))
    }

    const okHandler: EventHandler = {
      handle: jest.fn()
    }

    eventBus.subscribe('user.created', errorHandler)
    eventBus.subscribe('user.created', okHandler)

    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')

    // Should not throw
    await expect(eventBus.publish(event)).resolves.toBeUndefined()

    // Second handler should still be called
    expect(okHandler.handle).toHaveBeenCalled()
  })

  it('should maintain event history', async () => {
    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')
    await eventBus.publish(event)

    const history = eventBus.getEventHistory()
    expect(history).toHaveLength(1)
    expect(history[0]).toBe(event)
  })
})
```

---

## 📊 Event Flow Example

```typescript
// User creates account
const user = await userService.create({ email: 'user@example.com', ... })

// Service publishes event
eventBus.publish(new UserCreatedEvent(userId, email, name))

// Multiple handlers execute:
// 1. SendWelcomeEmailHandler → sends email
// 2. NotifyAdminsHandler → notifies admins
// 3. UpdateSearchIndexHandler → updates search

// All completely decoupled from UserService
```

---

## ✅ Checklist

- [ ] Create domain event classes
- [ ] Create event handler interfaces
- [ ] Create event handlers for each event
- [ ] Create EventBus coordinator
- [ ] Register event bus in DI container
- [ ] Register event handlers
- [ ] Update services to publish events
- [ ] Create comprehensive event tests
- [ ] Add event monitoring/logging

---

## 🎯 Success Criteria

✅ Services publish domain events  
✅ Multiple handlers can subscribe to same event  
✅ No direct coupling between services  
✅ Handlers can be added without modifying services  
✅ Event history available for debugging  
✅ Error in one handler doesn't break others  



## Reference: code_ServiceContainer.ts

```typescript
/**
 * ServiceContainer.ts - Dependency Injection Container Implementation
 *
 * This is the COPY-PASTE ready implementation of DI container.
 * Location: frontend/src/core/di/ServiceContainer.ts
 */

/**
 * ServiceContainer: Central Dependency Injection Container
 *
 * Singleton pattern for managing all service dependencies across the application.
 * Follows DIP (Dependency Inversion Principle).
 */
export class ServiceContainer {
  private static instance: ServiceContainer | null = null
  private services: Map<string, () => any> = new Map()
  private singletons: Map<string, any> = new Map()
  private initialized: boolean = false

  private constructor() {
    // Private constructor enforces singleton pattern
  }

  /**
   * Get or create the singleton instance
   */
  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }

  /**
   * Reset for testing purposes only
   */
  static reset(): void {
    ServiceContainer.instance = null
  }

  /**
   * Register a service factory
   */
  register<T = any>(
    key: string,
    factory: () => T,
    options: { singleton?: boolean } = {}
  ): void {
    if (this.services.has(key)) {
      console.warn(
        `⚠️ Service "${key}" already registered, overwriting (check dependencies.ts)`
      )
    }

    this.services.set(key, factory)

    if (options.singleton) {
      // Pre-create singleton
      this.singletons.set(key, factory())
    }
  }

  /**
   * Retrieve a service instance
   *
   * If service is a singleton, returns cached instance.
   * Otherwise, calls factory function each time.
   */
  get<T = any>(key: string): T {
    // Check singleton cache first (performance optimization)
    if (this.singletons.has(key)) {
      return this.singletons.get(key) as T
    }

    const factory = this.services.get(key)
    if (!factory) {
      throw new ServiceNotFoundError(
        `Service "${key}" not registered. Available services: ${Array.from(this.services.keys()).join(', ')}`
      )
    }

    return factory() as T
  }

  /**
   * Check if service is registered
   */
  has(key: string): boolean {
    return this.services.has(key) || this.singletons.has(key)
  }

  /**
   * Initialize all registered services
   * Call this once after all registrations are complete
   */
  initialize(): void {
    if (this.initialized) return

    const singletonKeys = Array.from(this.services.entries())
      .filter(([key, _]) => this.singletons.has(key))
      .map(([key, _]) => key)

    for (const key of singletonKeys) {
      try {
        this.get(key)
      } catch (error) {
        console.error(`❌ Failed to initialize service: ${key}`, error)
        throw error
      }
    }

    this.initialized = true
    console.log(`✅ DI Container initialized with ${this.services.size} services`)
  }

  /**
   * Get all registered service keys (debugging)
   */
  getRegisteredServices(): string[] {
    return Array.from(this.services.keys())
  }

  /**
   * Clear all services (testing)
   */
  clear(): void {
    this.services.clear()
    this.singletons.clear()
    this.initialized = false
  }
}

/**
 * Custom error for missing services
 */
export class ServiceNotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ServiceNotFoundError'
    Object.setPrototypeOf(this, ServiceNotFoundError.prototype)
  }
}

```

